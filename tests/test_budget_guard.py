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
        
        solver.STATE_FILE = self.temp_dir_path / "state.json"
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
        solver.STATE_FILE.write_text(json.dumps(initial_state), encoding="utf-8")

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

    def test_file_locking_context_manager(self):
        """Verifies that file_lock acquires and releases the lock file cleanly."""
        lock_path = self.temp_dir_path / "test.lock"
        with solver.file_lock(lock_path):
            self.assertTrue(lock_path.exists())

    def test_git_apply_rejects_malformed_patch(self):
        """Proves that validate_patch rejects a malformed or invalid patch via git apply --check."""
        repo_dir = self.temp_dir_path / "test_repo"
        repo_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize a real git repo
        subprocess.run(["git", "init"], cwd=str(repo_dir), capture_output=True, check=True)
        target_file = repo_dir / "example.py"
        target_file.write_text("def hello():\n    return 'world'\n", encoding="utf-8")
        subprocess.run(["git", "add", "example.py"], cwd=str(repo_dir), capture_output=True, check=True)
        subprocess.run(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@test.local", "commit", "-m", "init"],
            cwd=str(repo_dir), capture_output=True, check=True
        )

        # 1. Test malformed patch syntax (garbage lines)
        malformed_patch = """--- a/example.py
+++ b/example.py
@@ -1,2 +1,2 @@
-def hello():
+invalid hunk without context and wrong headers
"""
        valid = solver.validate_patch(repo_dir, malformed_patch)
        self.assertFalse(valid, "validate_patch MUST reject malformed patch headers")

        # 2. Test valid unified diff patch that matches repository content
        valid_patch = """--- a/example.py
+++ b/example.py
@@ -1,2 +1,3 @@
 def hello():
+    print('greeting')
     return 'world'
"""
        valid_res = solver.validate_patch(repo_dir, valid_patch)
        self.assertTrue(valid_res, "validate_patch MUST accept valid unified diff matching repo lines")

if __name__ == "__main__":
    unittest.main()
