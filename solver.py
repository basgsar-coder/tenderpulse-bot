#!/usr/bin/env python3
"""
TenderPulse Contextual LLM Solver & Budget Guard Engine
- Clones target repositories with safe naming and shallow flags.
- Rejects symlinks and enforces 128KB file size caps.
- Blacklists sensitive security files (.github/workflows, lockfiles, etc.).
- Enforces atomic file-locked budget reservation ($5.00 cap) with fail-closed StateError.
- Calls OpenAI or Gemini with sanitized headers (no key in query string).
- Validates patches with `git apply --check` before returning.
- Zero fake fallbacks: if LLM fails, returns None.
"""

import os
import sys
import json
import re
import tempfile
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from contextlib import contextmanager
from typing import Dict, Any, Optional, Tuple, List

BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "state.json"
STATE_LOCK_FILE = BASE_DIR / "state.lock"
PATCHES_DIR = BASE_DIR / "patches"
DRY_RUN_PATCHES_DIR = BASE_DIR / "dry_run_patches"
ENV_FILE = BASE_DIR / ".env"

DEFAULT_BUDGET_CAP = 5.00
AVG_CALL_COST_USD = 0.005
MAX_FILE_BYTES = 128 * 1024  # 128 KB hard cap

REPO_RE = re.compile(r"^[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+$")
HUNK_HEADER_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")

# Blacklisted sensitive files (Fix 16)
PROTECTED_PATHS = [
    ".github/workflows",
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "poetry.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "setup.py",
    "pyproject.toml",
    "Dockerfile",
    "docker-compose.yml"
]

class StateError(Exception):
    """Raised when state.json is missing, unparseable, or invalid (Fail-Closed)."""
    pass

@contextmanager
def file_lock(lock_path: Path):
    """Cross-platform advisory file lock for atomic budget state management (Fix 4)."""
    lock_file = open(lock_path, "w")
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        lock_file.close()

def load_env_keys() -> Dict[str, str]:
    keys = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                keys[k.strip()] = v.strip().strip('"').strip("'")
    for k in ["OPENAI_API_KEY", "GEMINI_API_KEY", "BOUNTY_BOT_TOKEN", "GITHUB_TOKEN"]:
        val = os.environ.get(k)
        if val:
            keys[k] = val
    return keys

def load_state() -> Dict[str, Any]:
    """Loads state.json fail-closed. If corrupt, raises StateError (Fix 4)."""
    if not STATE_FILE.exists():
        raise StateError(f"state.json does not exist at {STATE_FILE}. Fail-closed.")
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "llm_spend_this_month" not in data:
            raise StateError("state.json is malformed or missing required keys.")
        return data
    except Exception as e:
        if isinstance(e, StateError):
            raise
        raise StateError(f"state.json parsing failure: {type(e).__name__}") from e

def save_state(state: Dict[str, Any]):
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")

def reserve_budget(estimated_usd: float = AVG_CALL_COST_USD) -> Tuple[bool, str]:
    """
    Atomically reserves budget in state.json BEFORE making any external LLM call (Fix 4).
    Fails closed if state is corrupt or budget exceeded.
    """
    with file_lock(STATE_LOCK_FILE):
        state = load_state()
        current_spend = state.get("llm_spend_this_month", 0.0)
        budget_cap = state.get("monthly_budget_cap", DEFAULT_BUDGET_CAP)
        
        if current_spend + estimated_usd > budget_cap:
            return False, f"Budget exceeded: ${current_spend:.4f} + ${estimated_usd:.4f} > ${budget_cap:.2f} cap."
            
        # Atomically reserve the estimated spend upfront
        state["llm_spend_this_month"] = round(current_spend + estimated_usd, 6)
        save_state(state)
        return True, f"Budget reserved: ${state['llm_spend_this_month']:.4f} / ${budget_cap:.2f}"

def reconcile_budget(reserved_usd: float, actual_usd: float):
    """Adjusts spend ledger if actual token consumption differs from estimate."""
    with file_lock(STATE_LOCK_FILE):
        state = load_state()
        diff = actual_usd - reserved_usd
        state["llm_spend_this_month"] = round(state.get("llm_spend_this_month", 0.0) + diff, 6)
        save_state(state)

def release_budget_reservation(reserved_usd: float):
    """Releases reserved funds if the LLM call failed or was rejected."""
    with file_lock(STATE_LOCK_FILE):
        state = load_state()
        state["llm_spend_this_month"] = max(0.0, round(state.get("llm_spend_this_month", 0.0) - reserved_usd, 6))
        save_state(state)

def clone_repository(repo_name: str, target_dir: Path) -> bool:
    """Clones target repo safely with name validation, shallow flags, and no prompts (Fix 15)."""
    if not REPO_RE.match(repo_name):
        print(f"[SOLVER ERROR] Rejected unsafe repo name format: {repo_name}")
        return False

    repo_url = f"https://github.com/{repo_name}.git"
    print(f"[SOLVER] Cloning {repo_name} (depth=1, no-tags, single-branch)...")
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    
    try:
        res = subprocess.run(
            ["git", "clone", "--depth", "1", "--filter=blob:none", "--no-tags", "--single-branch", repo_url, str(target_dir)],
            capture_output=True,
            text=True,
            timeout=45,
            env=env
        )
        if res.returncode == 0:
            print(f"[SOLVER] Cloned {repo_name} successfully.")
            return True
        else:
            print(f"[SOLVER] Clone failed: {res.stderr.strip()[:100]}")
            return False
    except Exception as e:
        print(f"[SOLVER] Clone exception: {type(e).__name__}")
        return False

def is_protected_path(rel_path: str) -> bool:
    """Checks if target file is on the sensitive files blacklist (Fix 16)."""
    norm = rel_path.replace("\\", "/").lower()
    return any(norm == p.lower() or norm.startswith(p.lower()) for p in PROTECTED_PATHS)

def safe_target(repo_path: Path, candidate: Path) -> Optional[Path]:
    """
    Validates that candidate is inside repo_path, not a symlink, and <= 128KB (Fix 2, 14, 16).
    """
    if candidate.is_symlink():
        print(f"[SECURITY] Rejected symlink: {candidate}")
        return None
        
    try:
        resolved = candidate.resolve()
        repo_resolved = repo_path.resolve()
        if not (resolved == repo_resolved or repo_resolved in resolved.parents):
            print(f"[SECURITY] Path escape detected for {candidate}")
            return None
    except Exception:
        return None

    # Size cap check (Fix 2, 14)
    try:
        size = candidate.stat().st_size
        if size > MAX_FILE_BYTES:
            print(f"[SECURITY] File size exceeds 128KB cap ({size} bytes): {candidate}")
            return None
    except Exception:
        return None

    # Check blacklist
    rel = candidate.relative_to(repo_path).as_posix()
    if is_protected_path(rel):
        print(f"[SECURITY] Rejected protected path: {rel}")
        return None

    return candidate

def find_candidate_files(repo_path: Path, issue_title: str, issue_body: str) -> List[Path]:
    """Locates and validates candidate source files referenced in issue context."""
    found = []
    combined = f"{issue_title} {issue_body}"
    patterns = re.findall(r"[\w\-\/\\]+\.(?:py|md|js|ts|json|yml|yaml)\b", combined)
    
    for pat in patterns:
        clean_pat = pat.replace("\\", "/").lstrip("/")
        candidate = repo_path / clean_pat
        if candidate.is_file():
            safe = safe_target(repo_path, candidate)
            if safe and safe not in found:
                found.append(safe)
        else:
            base_name = Path(clean_pat).name
            for m in repo_path.glob(f"**/{base_name}"):
                if m.is_file():
                    safe = safe_target(repo_path, m)
                    if safe and safe not in found:
                        found.append(safe)

    # Fallback to general python/markdown source files
    if not found:
        for ext in ["*.py", "*.md"]:
            for f in repo_path.glob(f"**/{ext}"):
                if ".git" not in f.parts and f.is_file():
                    safe = safe_target(repo_path, f)
                    if safe and safe not in found:
                        found.append(safe)
                        if len(found) >= 2:
                            break
            if found:
                break
                
    return found[:2]

def call_openai_api(api_key: str, prompt: str) -> Tuple[Optional[str], Optional[float]]:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an automated expert software engineer fixing an open-source bug. "
                    "Return ONLY a clean, valid unified diff patch modifying the single specified file. "
                    "The diff MUST start with '--- a/' and '+++ b/'. "
                    "Do NOT wrap in markdown fences or quotes. No explanations. Raw diff only."
                )
            },
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 1500
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            choice = data["choices"][0]
            # Fix 14: Check finish reason for token truncation
            if choice.get("finish_reason") == "length":
                print("[SOLVER ERROR] LLM response truncated due to max_tokens limit.")
                return None, None
            content = choice["message"]["content"]
            # Estimate actual cost from token usage
            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 500)
            comp_tokens = usage.get("completion_tokens", 300)
            actual_cost = (prompt_tokens * 0.00000015) + (comp_tokens * 0.00000060)
            return content.strip(), actual_cost
    except Exception as e:
        print(f"[SOLVER LLM ERROR] OpenAI call failed: {type(e).__name__}")
        return None, None

def call_gemini_api(api_key: str, prompt: str) -> Tuple[Optional[str], Optional[float]]:
    """Calls Gemini API passing the key in HTTP header, never in query string (Fix 12)."""
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key
    }
    payload = {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            "You are an automated expert software engineer fixing an open-source bug. "
                            "Return ONLY a clean, valid unified diff patch modifying the single specified file. "
                            "The diff MUST start with '--- a/' and '+++ b/'. "
                            "Do NOT wrap in markdown fences or quotes. No explanations. Raw diff only.\n\n"
                            + prompt
                        )
                    }
                ]
            }
        ]
    }
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            candidate = data["candidates"][0]
            # Fix 14: Check finish reason
            if candidate.get("finishReason") in ("MAX_TOKENS", "LENGTH"):
                print("[SOLVER ERROR] Gemini response truncated due to token limit.")
                return None, None
            content = candidate["content"]["parts"][0]["text"]
            return content.strip(), AVG_CALL_COST_USD
    except Exception as e:
        print(f"[SOLVER LLM ERROR] Gemini call failed: {type(e).__name__}")
        return None, None

def extract_unified_diff(raw_text: str, rel_path: str) -> Optional[str]:
    """
    Strictly extracts a single-file unified diff matching rel_path with valid hunk headers (Fix 3).
    Rejects garbage or multi-file diffs.
    """
    clean = raw_text.strip()
    if clean.startswith("```"):
        clean = re.sub(r"^```(?:diff)?\n?", "", clean)
        clean = re.sub(r"\n?```$", "", clean)
        clean = clean.strip()

    header_a = f"--- a/{rel_path}"
    header_b = f"+++ b/{rel_path}"
    
    if header_a not in clean or header_b not in clean:
        # Check if generic header was provided
        if "--- a/" in clean and "+++ b/" in clean:
            lines = clean.splitlines()
            new_lines = []
            for line in lines:
                if line.startswith("--- a/"):
                    new_lines.append(header_a)
                elif line.startswith("+++ b/"):
                    new_lines.append(header_b)
                else:
                    new_lines.append(line)
            clean = "\n".join(new_lines)
        else:
            return None

    # Ensure hunk header exists
    lines = clean.splitlines()
    has_hunk = any(HUNK_HEADER_RE.match(line) for line in lines)
    if not has_hunk:
        return None

    # Check for multi-file attempt (only one '--- a/' allowed)
    if clean.count("--- a/") > 1:
        return None

    start_idx = clean.find(header_a)
    return clean[start_idx:].strip()

def validate_patch(repo_path: Path, patch_text: str) -> bool:
    """
    Writes patch to .tp_validate.patch and executes `git apply --check --ignore-whitespace` (Fix 3).
    Cleans up temporary file and returns True only if returncode == 0.
    """
    validate_file = repo_path / ".tp_validate.patch"
    try:
        validate_file.write_text(patch_text, encoding="utf-8")
        res = subprocess.run(
            ["git", "apply", "--check", "--ignore-whitespace", ".tp_validate.patch"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=10
        )
        return res.returncode == 0
    except Exception as e:
        print(f"[VALIDATION ERROR] Exception running git apply: {type(e).__name__}")
        return False
    finally:
        if validate_file.exists():
            try:
                validate_file.unlink()
            except Exception:
                pass

def solve_issue(issue: Dict[str, Any], dry_run: bool = True) -> Optional[Dict[str, Any]]:
    """
    Clones repo, safely resolves files, checks/reserves budget atomically,
    calls LLM, validates patch with `git apply --check`, and outputs patch.
    Zero synthetic fallbacks: returns None on failure (Fix 3, 4, 11).
    """
    issue_id = str(issue.get("id"))
    repo_name = issue.get("repo")
    issue_num = issue.get("issue_number")
    claim_url = issue.get("claim_url", "https://algora.io")
    platform = issue.get("platform", "Bounty Platform")

    # In dry-run mode, we do NOT mutate state.json or deduct budget (Fix 11)
    reserved = False
    if not dry_run:
        allowed, msg = reserve_budget(AVG_CALL_COST_USD)
        if not allowed:
            print(f"[SOLVER BLOCKED] {msg}")
            return None
        reserved = True
        print(f"[SOLVER BUDGET] {msg}")

    try:
        with tempfile.TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            if not clone_repository(repo_name, temp_dir):
                if reserved:
                    release_budget_reservation(AVG_CALL_COST_USD)
                return None

            candidates = find_candidate_files(temp_dir, issue.get("title", ""), issue.get("full_body", ""))
            if not candidates:
                print(f"[SOLVER] No accessible, safe source files in {repo_name}.")
                if reserved:
                    release_budget_reservation(AVG_CALL_COST_USD)
                return None

            target_file = candidates[0]
            rel_target = target_file.relative_to(temp_dir).as_posix()
            print(f"[SOLVER] Target file selected: {rel_target}")

            # Read file bytes up to 128KB cap (Fix 14)
            file_bytes = target_file.read_bytes()[:MAX_FILE_BYTES]
            file_content = file_bytes.decode("utf-8", errors="ignore")

            # Wrap untrusted inputs in security tags (Fix 16)
            prompt = (
                f"Target File: {rel_target}\n\n"
                f"<untrusted_issue>\n"
                f"Title: {issue.get('title')}\n"
                f"Body: {issue.get('full_body', '')}\n"
                f"</untrusted_issue>\n\n"
                f"Original File Content:\n```\n{file_content}\n```\n\n"
                f"Task: Output a raw unified diff patch modifying `{rel_target}` that cleanly resolves the issue. "
                f"Do not modify any other file. Start strictly with '--- a/{rel_target}'."
            )

            keys = load_env_keys()
            raw_patch = None
            actual_cost = None

            # Try OpenAI
            openai_key = keys.get("OPENAI_API_KEY")
            if openai_key and not openai_key.startswith("sk_test_") and "YOUR" not in openai_key:
                raw_patch, actual_cost = call_openai_api(openai_key, prompt)

            # Try Gemini
            if not raw_patch:
                gemini_key = keys.get("GEMINI_API_KEY")
                if gemini_key and "YOUR" not in gemini_key:
                    raw_patch, actual_cost = call_gemini_api(gemini_key, prompt)

            # Fix 3: No fake semantic code fallback! If LLM failed, return None
            if not raw_patch:
                print(f"[SOLVER] LLM inference unavailable or returned no output. Skipping {repo_name}#{issue_num}.")
                if reserved:
                    release_budget_reservation(AVG_CALL_COST_USD)
                return None

            # Reconcile actual spend (Fix 4)
            if reserved and actual_cost is not None:
                reconcile_budget(AVG_CALL_COST_USD, actual_cost)

            # Extract clean unified diff
            clean_patch = extract_unified_diff(raw_patch, rel_target)
            if not clean_patch:
                print(f"[SOLVER ERROR] Could not extract valid unified diff format for {rel_target}.")
                return None

            # Validate patch with git apply --check (Fix 3)
            if not validate_patch(temp_dir, clean_patch):
                print(f"[SOLVER ERROR] Patch failed `git apply --check` against {rel_target}. Discarding.")
                return None

            print(f"[SOLVER SUCCESS] Patch passed `git apply --check` for {rel_target}!")

            # Fix 7: Log manual claim instruction
            print(f"[PAYOUT] Manual claim required for {platform}: {claim_url}")

            # Save patch
            out_dir = DRY_RUN_PATCHES_DIR if dry_run else PATCHES_DIR
            out_dir.mkdir(parents=True, exist_ok=True)
            patch_file = out_dir / f"bounty_{issue_num}_{issue_id}.patch"
            patch_file.write_text(clean_patch, encoding="utf-8")

            return {
                "issue_id": issue_id,
                "repo": repo_name,
                "issue_number": issue_num,
                "bounty_amount": issue.get("bounty_amount"),
                "claim_url": claim_url,
                "platform": platform,
                "patch_file": str(patch_file),
                "patch_content": clean_patch,
                "target_file": rel_target
            }

    except Exception as e:
        print(f"[SOLVER UNHANDLED ERROR] {type(e).__name__}: {e}")
        if reserved:
            release_budget_reservation(AVG_CALL_COST_USD)
        return None
