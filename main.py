#!/usr/bin/env python3
"""
TenderPulse Bounty Hunter Orchestrator (main.py)
- Enforces BOUNTY_BOT_TOKEN for live mode (fails closed if missing).
- Preflights issues: verifies state is open, unlocked, and unassigned.
- Checks idempotency marker `<!-- tenderpulse:{issue_id} -->` before submitting.
- Enforces MAX_SUBMISSIONS_PER_DAY = 3 and 7-day cooldown per repository.
- Avoids state mutation in --dry-run mode.
- Computes dynamic markdown fence length to prevent fence escaping.
- Only marks issue as processed AFTER successful 2xx HTTP submission.
"""

import sys
import os
import argparse
import json
import time
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# Ensure Windows console compatibility
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from bounty_scanner import run_scanner, load_auth_token, RateLimited, DB_FILE
from solver import solve_issue, load_state, save_state, file_lock, STATE_LOCK_FILE, StateError

MAX_SUBMISSIONS_PER_DAY = 3
MIN_SECONDS_BETWEEN_SAME_REPO = 7 * 86400  # 7 days cooldown

def get_submission_history() -> List[Dict[str, Any]]:
    state = load_state()
    return state.get("recent_submissions", [])

def can_submit_to_repo(repo_name: str) -> Tuple[bool, str]:
    """Checks daily submission cap and per-repo 7-day cooldown (Fix 10)."""
    now = time.time()
    one_day_ago = now - 86400
    state = load_state()
    history = state.get("recent_submissions", [])

    # Filter to last 24h
    recent_24h = [s for s in history if s.get("timestamp", 0) > one_day_ago]
    if len(recent_24h) >= MAX_SUBMISSIONS_PER_DAY:
        return False, f"Daily limit reached ({len(recent_24h)}/{MAX_SUBMISSIONS_PER_DAY} in 24h)."

    # Check same-repo cooldown
    repo_submissions = [s for s in history if s.get("repo", "").lower() == repo_name.lower()]
    if repo_submissions:
        last_time = max(s.get("timestamp", 0) for s in repo_submissions)
        elapsed = now - last_time
        if elapsed < MIN_SECONDS_BETWEEN_SAME_REPO:
            days_left = round((MIN_SECONDS_BETWEEN_SAME_REPO - elapsed) / 86400, 1)
            return False, f"Repo {repo_name} is on cooldown ({days_left} days remaining)."

    return True, "Submission capacity available."

def preflight_check_issue(repo: str, issue_number: int, token: str) -> Tuple[bool, str]:
    """
    Performs preflight checks on target issue: open, unlocked, unassigned (Fix 10).
    """
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}"
    headers = {
        "User-Agent": "TenderPulse-BountyHunter/2.0",
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("state") != "open":
                return False, f"Issue is {data.get('state')}, not open."
            if data.get("locked"):
                return False, "Issue conversation is locked."
            if data.get("assignee") is not None or data.get("assignees"):
                return False, "Issue is already assigned to a developer."
            return True, "Preflight OK"
    except Exception as e:
        return False, f"Preflight error: {type(e).__name__}"

def has_idempotency_marker(repo: str, issue_number: int, marker: str, token: str) -> bool:
    """Checks if we already commented on this issue by looking for our marker (Fix 1)."""
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments?per_page=50"
    headers = {
        "User-Agent": "TenderPulse-BountyHunter/2.0",
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            comments = json.loads(resp.read().decode("utf-8"))
            for c in comments:
                if marker in c.get("body", ""):
                    return True
    except Exception:
        pass
    return False

def submit_live_pr(solution: Dict[str, Any], token: str) -> bool:
    """
    Submits draft resolution comment with dynamic backtick fencing and idempotency markers (Fix 1, 16).
    """
    repo = solution.get("repo")
    issue_number = solution.get("issue_number")
    issue_id = solution.get("issue_id")
    patch_content = solution.get("patch_content", "")
    target_file = solution.get("target_file", "source file")
    marker = f"<!-- tenderpulse:{issue_id} -->"

    # Check idempotency marker first (Fix 1)
    if has_idempotency_marker(repo, issue_number, marker, token):
        print(f"[MAIN LIVE] Idempotency marker found on {repo}#{issue_number}. Skipping duplicate.")
        return True

    # Calculate longest run of backticks to prevent markdown injection (Fix 16)
    backtick_runs = re.findall(r"`+", patch_content)
    max_run = max([len(r) for r in backtick_runs], default=0)
    fence = "`" * max(3, max_run + 1)

    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
    headers = {
        "User-Agent": "TenderPulse-BountyHunter/2.0",
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json"
    }

    body = (
        f"{marker}\n"
        f"### Proposed Solution Patch\n\n"
        f"Automated contextual fix generated for issue #{issue_number}.\n"
        f"- Target file: `{target_file}`\n"
        f"- Unified diff validated with `git apply --check`.\n\n"
        f"{fence}diff\n"
        f"{patch_content}\n"
        f"{fence}\n"
    )

    req = urllib.request.Request(url, data=json.dumps({"body": body}).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status in (200, 201):
                print(f"[MAIN LIVE SUCCESS] Submitted resolution to {repo}#{issue_number}!")
                return True
            else:
                print(f"[MAIN LIVE FAILED] Server returned status {resp.status}")
                return False
    except Exception as e:
        print(f"[MAIN LIVE ERROR] Failed submission to {repo}#{issue_number}: {type(e).__name__}")
        return False

def mark_processed_live(issue_id: str, repo: str):
    """Marks issue as processed and appends to submission rate tracker in state.json (Fix 1, 10)."""
    with file_lock(STATE_LOCK_FILE):
        state = load_state()
        processed = state.get("processed_issue_ids", [])
        if issue_id not in processed:
            processed.append(issue_id)
        state["processed_issue_ids"] = processed
        state["bounties_solved"] = state.get("bounties_solved", 0) + 1

        history = state.get("recent_submissions", [])
        history.append({
            "issue_id": issue_id,
            "repo": repo,
            "timestamp": time.time()
        })
        state["recent_submissions"] = history[-50:]  # Keep last 50
        save_state(state)

def main():
    parser = argparse.ArgumentParser(description="TenderPulse Autonomous GitHub Bounty Hunter")
    parser.add_argument("--live", action="store_true", help="Submit live PRs/comments to GitHub (requires BOUNTY_BOT_TOKEN)")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Run without posting or updating state (default)")
    parser.add_argument("--limit", type=int, default=1, help="Max bounties to attempt solving per cycle")
    args = parser.parse_args()

    if args.live:
        args.dry_run = False

    print("=" * 60)
    print("[TenderPulse] Hardened Autonomous GitHub Bounty Hunter")
    print(f"Mode: {'LIVE SUBMISSION' if not args.dry_run else 'DRY RUN (No state mutation)'}")
    print("=" * 60)

    token = os.environ.get("BOUNTY_BOT_TOKEN") or load_auth_token()
    
    # Fail closed if live mode requested without token (Fix 1)
    if not args.dry_run and not token:
        print("[MAIN FATAL] Live mode requested but BOUNTY_BOT_TOKEN is missing. Aborting run.")
        sys.exit(1)

    # Verify state integrity fail-closed (Fix 4)
    try:
        state = load_state()
    except StateError as se:
        print(f"[MAIN FATAL] State integrity failure: {se}")
        sys.exit(1)

    # Rate limit and scan
    try:
        bounties = run_scanner()
    except RateLimited as rl:
        print(f"[MAIN ABORT] GitHub Search API rate limited: {rl}. Aborting cycle before any spend.")
        return 0

    if not bounties:
        print("[MAIN] No verified, open bounties found matching criteria.")
        return 0

    # Sort bounties by amount descending
    sorted_bounties = sorted(bounties, key=lambda x: x.get("bounty_amount", 0.0), reverse=True)
    candidates = sorted_bounties[:args.limit]

    solved_count = 0
    for issue in candidates:
        repo = issue.get("repo")
        issue_number = issue.get("issue_number")
        issue_id = str(issue.get("id"))

        # Skip if already processed
        if issue_id in state.get("processed_issue_ids", []):
            print(f"[MAIN] Issue {repo}#{issue_number} already processed. Skipping.")
            continue

        # Check daily cap and repo cooldown in live mode (Fix 10)
        if not args.dry_run:
            can_submit, reason = can_submit_to_repo(repo)
            if not can_submit:
                print(f"[MAIN CAP] Skipping {repo}#{issue_number}: {reason}")
                continue

            # Preflight check on GitHub issue (Fix 10)
            preflight_ok, preflight_msg = preflight_check_issue(repo, issue_number, token)
            if not preflight_ok:
                print(f"[MAIN PREFLIGHT] Skipping {repo}#{issue_number}: {preflight_msg}")
                continue

        # Solve issue
        print("\n" + "-" * 50)
        solution = solve_issue(issue, dry_run=args.dry_run)
        if not solution:
            continue

        if args.dry_run:
            print("[MAIN DRY RUN] Patch generated and validated locally.")
            print(f"  Dry-run patch saved to: {solution['patch_file']}")
            print(f"  (Note: dry_run leaves state.json unmutated)")
            solved_count += 1
        else:
            print(f"[MAIN LIVE] Submitting resolution comment to {repo}#{issue_number}...")
            success = submit_live_pr(solution, token)
            if success:
                mark_processed_live(issue_id, repo)
                solved_count += 1
            else:
                print(f"[MAIN WARNING] Submission failed for {repo}#{issue_number}. Not marked as processed.")

    print("\n" + "=" * 60)
    final_state = load_state()
    print(f"Cycle Complete. Solved {solved_count} bounties.")
    print(f"Monthly LLM Spend: ${final_state.get('llm_spend_this_month', 0.0):.4f} / ${final_state.get('monthly_budget_cap', 5.0):.2f}")
    print("=" * 60)
    return 0

if __name__ == "__main__":
    sys.exit(main())
