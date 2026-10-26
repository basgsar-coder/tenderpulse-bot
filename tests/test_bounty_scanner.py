#!/usr/bin/env python3
"""
Unit tests for the TenderPulse GitHub Bounty Scanner
Tests price regex extraction, capability filtering, and GitHub REST API parsing with mocked HTTP responses.
"""

import unittest
import sys
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import bounty_scanner

class TestBountyScanner(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_db_file = Path(self.temp_dir.name) / "test_bounties.db"
        self.orig_db_file = bounty_scanner.DB_FILE
        bounty_scanner.DB_FILE = self.temp_db_file

    def tearDown(self):
        bounty_scanner.DB_FILE = self.orig_db_file
        self.temp_dir.cleanup()

    def test_extract_bounty_amount(self):
        cases = [
            ("Bug bounty: $150.00 for fixing this memory leak", 150.0),
            ("Algora $50 bounty on this issue", 50.0),
            ("Offering $250 to whoever submits a clean PR", 250.0),
            ("100 USDC reward for documentation fix", 100.0),
            ("No price mentioned here", 0.0),
        ]
        for text, expected in cases:
            extracted = bounty_scanner.extract_bounty_amount(text)
            self.assertEqual(extracted, expected, f"Failed on text: '{text}'")

    def test_matches_capabilities(self):
        self.assertTrue(bounty_scanner.matches_capabilities(
            "Fix Python CLI argument parser", "Fails on boolean flags", ["bug"]
        ))
        self.assertTrue(bounty_scanner.matches_capabilities(
            "Update API documentation", "Markdown syntax cleanup", ["docs"]
        ))
        self.assertFalse(bounty_scanner.matches_capabilities(
            "Design vector graphic logo", "Need SVG icon for website", ["design", "art"]
        ))

    def test_spam_filtering(self):
        self.assertTrue(bounty_scanner.is_spam_or_blocked("zhangjiayang6835-cyber/bounty-plaza"))
        self.assertTrue(bounty_scanner.is_spam_or_blocked("Rohank143/BountyScout"))
        self.assertTrue(bounty_scanner.is_spam_or_blocked("some-user/crypto-faucet-bot"))
        self.assertFalse(bounty_scanner.is_spam_or_blocked("pallets/click"))
        self.assertFalse(bounty_scanner.is_spam_or_blocked("psf/requests"))

    @patch("urllib.request.urlopen")
    def test_search_github_bounties_with_mock_response(self, mock_urlopen):
        mock_response_data = {
            "total_count": 1,
            "items": [
                {
                    "id": 123456789,
                    "number": 88,
                    "title": "Fix Python regex parser memory leak ($100 bounty)",
                    "body": "There is a memory leak in the token loop. Offering $100 bounty.",
                    "html_url": "https://github.com/example-org/repo/issues/88",
                    "repository_url": "https://api.github.com/repos/example-org/repo",
                    "labels": [{"name": "bounty"}, {"name": "python"}, {"name": "bug"}]
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_response_data).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        results = bounty_scanner.search_github_bounties("test query", token="test_token")
        self.assertEqual(len(results), 1)
        item = results[0]
        self.assertEqual(item["repo"], "example-org/repo")
        self.assertEqual(item["issue_number"], 88)
        self.assertEqual(item["bounty_amount"], 100.0)

    def test_persist_bounties_in_database(self):
        sample_bounties = [
            {
                "id": "item_1",
                "repo": "test/repo1",
                "issue_number": 10,
                "title": "Bounty issue 1",
                "url": "https://github.com/test/repo1/issues/10",
                "bounty_amount": 75.0,
                "currency": "USD",
                "labels": "bounty, python",
                "body_preview": "Sample body preview"
            }
        ]
        stored_count = bounty_scanner.persist_bounties(sample_bounties)
        self.assertEqual(stored_count, 1)

        # Verify record in SQLite
        conn = sqlite3.connect(self.temp_db_file)
        cursor = conn.cursor()
        cursor.execute("SELECT id, bounty_amount FROM bounties WHERE id = 'item_1'")
        row = cursor.fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], "item_1")
        self.assertEqual(row[1], 75.0)

if __name__ == "__main__":
    unittest.main()
