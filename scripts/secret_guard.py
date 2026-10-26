#!/usr/bin/env python3
"""
Pre-commit & CI Secret Guard
Scans staged or all tracked files for high-entropy secrets and credential patterns.
Never prints matched secrets to stdout/logs to prevent secret exfiltration into CI records.
"""

import sys
import os
import re
import subprocess
from pathlib import Path
from typing import List, Tuple

PROHIBITED_RULES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"ghp_[A-Za-z0-9_]{36,}"), "GitHub Personal Access Token (Classic)"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{82,}"), "GitHub Fine-Grained Personal Access Token"),
    (re.compile(r"sk-[A-Za-z0-9_-]{20,}"), "OpenAI Secret Key"),
    (re.compile(r"AIza[0-9A-Za-z_-]{35}"), "Google Cloud / Gemini API Key"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS Access Key ID"),
    (re.compile(r"0x[a-fA-F0-9]{64}"), "Raw 64-hex Private Key"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "PEM-formatted Private Key Header"),
]

EXCLUDED_FILES = {
    "scripts/secret_guard.py",
    "tests/test_secret_guard.py"
}

def scan_content(content: str, filename: str = "") -> List[str]:
    violations = []
    norm_name = filename.replace("\\", "/")
    for excluded in EXCLUDED_FILES:
        if norm_name.endswith(excluded):
            return []

    for pattern, rule_name in PROHIBITED_RULES:
        if pattern.search(content):
            # Report rule name and file path ONLY - NEVER echo the secret string
            violations.append(f"[{rule_name}] in {filename}")
    return violations

def get_target_files(args: List[str]) -> List[str]:
    if args:
        return args
        
    # Check staged files first (pre-commit hook mode)
    try:
        res = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True, text=True, check=True
        )
        staged = [f.strip() for f in res.stdout.splitlines() if f.strip()]
        if staged:
            return staged
    except Exception:
        pass
        
    # Fallback: scan all tracked files via git ls-files (CI mode)
    try:
        res = subprocess.run(
            ["git", "ls-files"],
            capture_output=True, text=True, check=True
        )
        tracked = [f.strip() for f in res.stdout.splitlines() if f.strip()]
        if tracked:
            return tracked
    except Exception:
        pass

    # Filesystem fallback
    target_files = []
    base = Path.cwd()
    for p in base.rglob("*"):
        if p.is_file() and ".git" not in p.parts and not p.name.endswith(".db"):
            target_files.append(str(p.relative_to(base)))
    return target_files

def main():
    target_files = get_target_files(sys.argv[1:])
    total_violations = []

    for filepath in target_files:
        p = Path(filepath)
        if not p.is_file():
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
            violations = scan_content(content, str(filepath))
            total_violations.extend(violations)
        except Exception as e:
            print(f"[SECRET_GUARD] Warning: Could not read {filepath}: {type(e).__name__}")

    if total_violations:
        print("\n" + "=" * 60)
        print("[BLOCKED] SECRET GUARD DETECTED CREDENTIALS IN TRACKED FILES")
        print("Violation summary (sensitive contents suppressed for safety):")
        for v in total_violations:
            print(f"  - {v}")
        print("Action required: Remove the secret immediately and place it in .env.")
        print("=" * 60 + "\n")
        sys.exit(1)

    return 0

if __name__ == "__main__":
    main()
