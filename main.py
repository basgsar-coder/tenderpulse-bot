#!/usr/bin/env python3
"""
TenderPulse Bounty Hunter Orchestrator (main.py)
Orchestrates scanning GitHub for bounties, budget checks, patch generation,
and submission of pull requests / fix comments.
"""

import sys
import os
import argparse
import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# Ensure Windows console compatibility
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from bounty_scanner import run_scanner, load_github_token
from solver import solve_issue, load_state

def submit_live_pr(solution: Dict[str, Any], token: str) -> bool:
    """
    Submits draft comment or pull request to the target issue using GitHub REST API.
    """
    repo = solution.get("repo")
    issue_number = solution.get("issue_number")
    pr_body = solution.get("pr_body")
    patch_content = solution.get("patch_content")
    
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}/comments"
    headers = {
        "User-Agent": "TenderPulse-BountyHunter/1.0",
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json"
    }
    
    payload = {
        "body": f"{pr_body}\n\n### Proposed Solution Patch:\n```diff\n{patch_content}\n```"
    }
    
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status in (200, 201):
                print(f"[MAIN LIVE] Successfully posted resolution to {repo}#{issue_number}!")
                return True
    except Exception as e:
        print(f"[MAIN LIVE] Error submitting to {repo}#{issue_number}: {e}")
        
    return False

def main():
    parser = argparse.ArgumentParser(description="TenderPulse Autonomous GitHub Bounty Hunter")
    parser.add_argument("--live", action="store_true", help="Submit live PRs/comments to GitHub (requires GITHUB_TOKEN)")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Run without posting to GitHub (default)")
    parser.add_argument("--limit", type=int, default=3, help="Max bounties to attempt solving per cycle")
    args = parser.parse_args()

    # If --live is explicitly requested, disable dry-run
    if args.live:
        args.dry_run = False

    print("=" * 60)
    print("[TenderPulse] Autonomous GitHub Bounty Hunter")
    print(f"Mode: {'LIVE SUBMISSION' if not args.dry_run else 'DRY RUN (Local Simulation)'}")
    print("=" * 60)

    token = load_github_token()
    if not token and not args.dry_run:
        print("[MAIN ERROR] Live mode requested but GITHUB_TOKEN is not configured in .env. Falling back to dry-run.")
        args.dry_run = True

    # 1. State and Budget Status
    state = load_state()
    current_spend = state.get("llm_spend_this_month", 0.0)
    budget_cap = state.get("monthly_budget_cap", 5.0)
    print(f"[BUDGET STATUS] Spend this month: ${current_spend:.4f} / ${budget_cap:.2f} cap")

    # 2. Scan Bounties
    bounties = run_scanner()
    if not bounties:
        print("[MAIN] No matching bounties found in this cycle. Sleeping until next schedule.")
        return 0

    # Sort bounties by amount descending
    sorted_bounties = sorted(bounties, key=lambda x: x.get("bounty_amount", 0.0), reverse=True)
    candidates = sorted_bounties[:args.limit]

    print(f"\n[MAIN] Selected top {len(candidates)} candidate bounties for resolution:")
    for b in candidates:
        print(f"  * [${b['bounty_amount']:.2f}] {b['repo']}#{b['issue_number']}: {b['title'][:55]}")

    # 3. Solve Candidates
    solved_count = 0
    for issue in candidates:
        print("\n" + "-" * 50)
        solution = solve_issue(issue, dry_run=args.dry_run)
        if not solution:
            continue

        solved_count += 1
        if args.dry_run:
            print("[MAIN DRY RUN] Proposed fix generated successfully.")
            print(f"  Patch saved: {solution['patch_file']}")
        else:
            print("[MAIN LIVE] Dispatching solution to GitHub...")
            submit_live_pr(solution, token)

    print("\n" + "=" * 60)
    final_state = load_state()
    print(f"Cycle Complete. Solved {solved_count} bounties.")
    print(f"Total Discovered: {final_state.get('bounties_discovered')}")
    print(f"Total Solved: {final_state.get('bounties_solved')}")
    print(f"Monthly LLM Spend: ${final_state.get('llm_spend_this_month'):.4f} / ${final_state.get('monthly_budget_cap'):.2f}")
    print("=" * 60)
    return 0

if __name__ == "__main__":
    sys.exit(main())
