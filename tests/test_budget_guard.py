#!/usr/bin/env python3
"""
Unit tests for the TenderPulse Budget Guard & Patch Validation Engine
Asserts that:
1. `git apply --check` rejects malformed, invalid, or mismatched patches.
2. The budget guard uses atomic file locking, reserves spend upfront, and fails closed (raising StateError) on corrupted state.json.
"""

import unittest
import sys
import json
import tempfile
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import solver

class TestBudgetGuardAndPatchValidation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_dir_path = Path(self.temp_dir.name)
        
        self.orig_state_file = solver.STATE_FILE
        self.orig_lock_file = solver.STATE_LOCK_FILE
        
        self.temp_state_file = self.temp_dir_path / "state.json"
        solver.STATE_FILE = self.temp_state_file
        solver.STATE_LOCK_FILE = self.temp_dir_path / "state.lock"

        # Initialize valid state
        initial_state = {
            "llm_spend_this_month": 0.0,
            "monthly_budget_cap": 5.0,
            "bounties_discovered": 0,
            "bounties_solved": 0,
            "processed_issue_ids": [],
            "recent_submissions": []
        }
        self.temp_state_file.write_text(json.dumps(initial_state), encoding="utf-8")

        # Set up git repo for patch validation tests
        self.repo_path = self.temp_dir_path / "test_repo"
        self.repo_path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init"], cwd=str(self.repo_path), capture_output=True, check=True)
        sample_file = self.repo_path / "sample.py"
        sample_file.write_text("def f():\n    return 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "sample.py"], cwd=str(self.repo_path), capture_output=True, check=True)
        subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@test.local", "commit", "-m", "init"],
            cwd=str(self.repo_path), capture_output=True, check=True
        )

    def tearDown(self):
        solver.STATE_FILE = self.orig_state_file
        solver.STATE_LOCK_FILE = self.orig_lock_file
        self.temp_dir.cleanup()

    def test_budget_reserves_upfront_under_cap(self):
        allowed, msg = solver.reserve_budget(0.005)
        self.assertTrue(allowed, "Budget guard must approve spend under cap")
        state = solver.load_state()
        self.assertAlmostEqual(state["llm_spend_this_month"], 0.005, places=4)

    def test_budget_blocks_when_cap_exceeded(self):
        state = solver.load_state()
        state["llm_spend_this_month"] = 4.999
        solver.save_state(state)

        allowed, msg = solver.reserve_budget(0.005)
        self.assertFalse(allowed, "Budget guard must reject when spend + estimate exceeds cap")
        self.assertIn("exceeded", msg.lower())

    def test_budget_fails_closed_on_corrupt_state(self):
        # Write corrupted garbage to state.json
        solver.STATE_FILE.write_text("{corrupt_json: invalid###}", encoding="utf-8")

        with self.assertRaises(solver.StateError):
            solver.load_state()

        with self.assertRaises(solver.StateError):
            solver.reserve_budget(0.005)

    def test_corrupt_state_fails_closed(self):
        """Exact test from Audit Fix 22: corrupt state.json raises StateError fail-closed."""
        self.temp_state_file.write_text("{not json", encoding="utf-8")
        with self.assertRaises(solver.StateError):
            solver.load_state()

    def test_file_locking_context_manager(self):
        """Verifies that file_lock acquires and releases the lock file cleanly."""
        lock_path = self.temp_dir_path / "test.lock"
        with solver.file_lock(lock_path):
            self.assertTrue(lock_path.exists())

    def test_extract_rejects_prose_without_diff(self):
        """Exact test from Audit Fix 22: prose without diff raises ValueError."""
        with self.assertRaises(ValueError):
            solver.extract_unified_diff("Here is a long explanation.", "app.py")

    def test_extract_rejects_multiple_files(self):
        """Exact test from Audit Fix 22: diff touching multiple files raises ValueError."""
        raw = (
            "--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-x\n+y\n"
            "--- a/.github/workflows/ci.yml\n+++ b/.github/workflows/ci.yml\n"
            "@@ -1 +1 @@\n-a\n+b\n"
        )
        with self.assertRaises(ValueError):
            solver.extract_unified_diff(raw, "app.py")

    def test_invalid_patch_fails_git_apply_check(self):
        """Exact test from Audit Fix 22: invalid synthetic patch fails git apply --check."""
        patch = solver.synthesize_semantic_code_fix(
            "sample.py", 'def f():\n    return 1\n', {"issue_number": 1, "title": "x"}
        )
        ok, _ = solver.validate_patch(patch, "sample.py", self.repo_path)
        self.assertFalse(ok)

    def test_valid_issue_boundary_checks(self):
        """Audit Fix 19: Boundary validation for issue fields."""
        self.assertTrue(solver.valid_issue({
            "repo": "owner/repo",
            "issue_number": 12,
            "id": "123456",
            "bounty_amount": 50.0
        }))
        self.assertFalse(solver.valid_issue({"repo": "bad repo", "issue_number": 1, "id": "1", "bounty_amount": 10}))
        self.assertFalse(solver.valid_issue({"repo": "a/b", "issue_number": -1, "id": "1", "bounty_amount": 10}))
        self.assertFalse(solver.valid_issue({"repo": "a/b", "issue_number": 1, "id": "None", "bounty_amount": 10}))
        self.assertFalse(solver.valid_issue({"repo": "a/b", "issue_number": 1, "id": "1", "bounty_amount": 0}))

    def test_git_apply_rejects_malformed_patch(self):
        """Proves that validate_patch rejects a malformed or invalid patch via git apply --check."""
        # 1. Test malformed patch syntax (garbage lines)
        malformed_patch = """--- a/sample.py
+++ b/sample.py
@@ -1,2 +1,2 @@
-def f():
+invalid hunk without context and wrong headers
"""
        valid = solver.validate_patch(self.repo_path, malformed_patch)
        self.assertFalse(valid, "validate_patch MUST reject malformed patch headers")

        # 2. Test valid unified diff patch that matches repository content
        valid_patch = """--- a/sample.py
+++ b/sample.py
@@ -1,2 +1,3 @@
 def f():
+    print('greeting')
     return 1
"""
        valid_res = solver.validate_patch(self.repo_path, valid_patch)
        self.assertTrue(valid_res, "validate_patch MUST accept valid unified diff matching repo lines")

if __name__ == "__main__":
    unittest.main()
