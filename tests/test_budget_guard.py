#!/usr/bin/env python3
"""
Unit tests for the TenderPulse LLM Budget Guard
Asserts that monthly spend is strictly capped at $5.00 and calls are blocked when cap is reached.
"""

import unittest
import sys
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import solver

class TestBudgetGuard(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_state_file = Path(self.temp_dir.name) / "state.json"
        self.orig_state_file = solver.STATE_FILE
        solver.STATE_FILE = self.temp_state_file

    def tearDown(self):
        solver.STATE_FILE = self.orig_state_file
        self.temp_dir.cleanup()

    def test_budget_allows_call_when_spend_is_zero(self):
        # Initial spend: $0.00, cap: $5.00
        initial_state = {
            "llm_spend_this_month": 0.0,
            "monthly_budget_cap": 5.0,
            "bounties_solved": 0
        }
        self.temp_state_file.write_text(json.dumps(initial_state), encoding="utf-8")

        allowed, msg = solver.check_budget_guard(0.005)
        self.assertTrue(allowed, "Budget guard must approve call when spend is $0.00")
        self.assertIn("approved", msg.lower())

    def test_budget_blocks_call_when_cap_exceeded(self):
        # Current spend: $4.998, call cost: $0.005 -> $5.003 > $5.00
        near_limit_state = {
            "llm_spend_this_month": 4.998,
            "monthly_budget_cap": 5.0,
            "bounties_solved": 10
        }
        self.temp_state_file.write_text(json.dumps(near_limit_state), encoding="utf-8")

        allowed, msg = solver.check_budget_guard(0.005)
        self.assertFalse(allowed, "Budget guard must strictly block call when spend exceeds $5.00")
        self.assertIn("blocked", msg.lower())
        self.assertIn("exceeded", msg.lower())

    def test_record_spend_updates_state(self):
        initial_state = {
            "llm_spend_this_month": 1.0,
            "monthly_budget_cap": 5.0,
            "bounties_solved": 2
        }
        self.temp_state_file.write_text(json.dumps(initial_state), encoding="utf-8")

        solver.record_spend(0.05)
        updated = solver.load_state()
        self.assertAlmostEqual(updated["llm_spend_this_month"], 1.05, places=4)

if __name__ == "__main__":
    unittest.main()
