#!/usr/bin/env python3
"""
Pre-commit Secret Guard
Scans staged or tracked files for prohibited secrets or private key patterns.
Fails with exit code 1 if any violation is detected.
"""

import sys
import os
import re
import subprocess
from pathlib import Path

# Prohibited patterns constructed without literal trigger strings
PROHIBITED_PATTERNS = [
    (re.compile(r"EVM_" + r"PRIVATE_KEY"), "EVM private key reference"),
    (re.compile(r"STRIPE_" + r"SECRET_KEY"), "Stripe secret key reference"),
    (re.compile(r"-----BEGIN .* PRIVATE KEY-----"), "PEM formatted private key"),
]

EXCLUDED_FILES = {
    "scripts/secret_guard.py",
    "tests/test_secret_guard.py"
}

def scan_content(content: str, filename: str = "") -> list:
    violations = []
    # Normalize path separators
    normalized_name = filename.replace("\\", "/")
    for excluded in EXCLUDED_FILES:
        if normalized_name.endswith(excluded):
            return []

    for pattern, desc in PROHIBITED_PATTERNS:
        matches = pattern.findall(content)
        if matches:
            violations.append(f"{desc} (matched '{matches[0]}') in {filename}")
    return violations

def get_staged_files():
    try:
        res = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True, text=True, check=True
        )
        return [f.strip() for f in res.stdout.splitlines() if f.strip()]
    except Exception:
        return []

def main():
    target_files = sys.argv[1:]
    if not target_files:
        target_files = get_staged_files()
        
    if not target_files:
        # If no specific files passed and no staged files, exit clean
        return 0

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
            print(f"[SECRET_GUARD] Warning: Could not read {filepath}: {e}")

    if total_violations:
        print("\n" + "=" * 60)
        print("[BLOCKED] COMMIT REJECTED BY PRE-COMMIT SECRET GUARD")
        print("Prohibited secrets or private key patterns detected:")
        for v in total_violations:
            print(f"  - {v}")
        print("Action required: Remove the secret from tracked files and add it to .env (which must be in .gitignore).")
        print("=" * 60 + "\n")
        sys.exit(1)

    return 0

if __name__ == "__main__":
    main()
