#!/usr/bin/env python3
"""
Unit tests for the TenderPulse Verified Bounty Scanner
Asserts that:
1. Payout platforms (Algora & IssueHunt) are strictly required and parsed.
2. Spam repositories are blocked by normalized regex.
3. HTTP 403/429 and rate-exhaustion headers raise RateLimited exceptions.
"""

import unittest
import sys
import json
import sqlite3
import tempfile
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import bounty_scanner

class TestVerifiedBountyScanner(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_db_file = Path(self.temp_dir.name) / "test_bounties.db"
        self.orig_db_file = bounty_scanner.DB_FILE
        bounty_scanner.DB_FILE = self.temp_db_file

    def tearDown(self):
        bounty_scanner.DB_FILE = self.orig_db_file
        self.temp_dir.cleanup()

    def test_detect_platform_algora_and_issuehunt(self):
        # 1. Valid Algora bounty text
        algora_text = (
            "Please fix this memory bug.\n"
            "Bounty: $150.00\n"
            "Claim bounty on Algora: https://console.algora.io/bounties/bnty_12345abc"
        )
        detected = bounty_scanner.detect_platform(algora_text)
        self.assertIsNotNone(detected)
        self.assertEqual(detected[0], "Algora")
        self.assertEqual(detected[1], 150.0)
        self.assertEqual(detected[2], "https://console.algora.io/bounties/bnty_12345abc")

        # 2. Valid IssueHunt bounty text
        issuehunt_text = (
            "Reward offered for this task!\n"
            "Funded with $100 bounty on IssueHunt:\n"
            "https://issuehunt.io/r/facebook/react/issues/456"
        )
        detected_ih = bounty_scanner.detect_platform(issuehunt_text)
        self.assertIsNotNone(detected_ih)
        self.assertEqual(detected_ih[0], "IssueHunt")
        self.assertEqual(detected_ih[1], 100.0)
        self.assertEqual(detected_ih[2], "https://issuehunt.io/r/facebook/react/issues/456")

        # 3. Unverified bounty without recognized platform URL (MUST be rejected)
        unverified_text = "I will pay $50 to anyone who fixes this via PayPal or cash"
        detected_none = bounty_scanner.detect_platform(unverified_text)
        self.assertIsNone(detected_none, "Bounties lacking recognized escrow URLs must be rejected")

    def test_spam_repo_normalized_regex(self):
        spam_cases = [
            "zhangjiayang6835-cyber/bounty-plaza",
            "Rohank143/BountyScout",
            "bot-user/bounty.alert",
            "org/bounty_bot_v2",
            "scammer/free-airdrop",
            "crypto/faucet-collector",
        ]
        for name in spam_cases:
            self.assertTrue(bounty_scanner.is_spam_repo(name), f"Failed to block spam repo: {name}")

        legit_cases = [
            "pallets/click",
            "psf/requests",
            "tiangolo/fastapi",
            "facebook/react",
            "bounty-hunter-legit-tool/useful-lib"  # Not matching spam suffix/pattern
        ]
        for name in legit_cases:
            self.assertFalse(bounty_scanner.is_spam_repo(name), f"Incorrectly blocked legit repo: {name}")

    @patch("urllib.request.urlopen")
    def test_rate_limited_exception_raised_on_403_or_429(self, mock_urlopen):
        # Simulate GitHub 403 rate limit response
        headers = {"X-RateLimit-Reset": "1730000000", "Retry-After": "60"}
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://api.github.com/search/issues",
            code=403,
            msg="rate limit exceeded",
            hdrs=headers,
            fp=None
        )

        with self.assertRaises(bounty_scanner.RateLimited):
            bounty_scanner.search_github_bounties("test query", token="test_token")

    @patch("urllib.request.urlopen")
    def test_rate_limit_raises(self, mock_urlopen):
        """Exact test from Audit Fix 22: Mock HTTPError 403 with X-RateLimit-Remaining: 0."""
        headers = {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1730000000"}
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://api.github.com/search/issues",
            code=403,
            msg="rate limit exceeded",
            hdrs=headers,
            fp=None
        )
        with self.assertRaises(bounty_scanner.RateLimited):
            bounty_scanner.github_json("https://api.github.com/search/issues", "token")

    @patch("urllib.request.urlopen")
    def test_search_github_bounties_filters_unverified(self, mock_urlopen):
        mock_response = {
            "total_count": 2,
            "items": [
                {
                    "id": 111,
                    "number": 10,
                    "title": "Legit Algora Bounty ($50)",
                    "body": "Fix this bug https://console.algora.io/bounties/bnty_abc123 $50 bounty",
                    "html_url": "https://github.com/legit-org/repo/issues/10",
                    "repository_url": "https://api.github.com/repos/legit-org/repo",
                    "labels": [{"name": "bounty"}]
                },
                {
                    "id": 222,
                    "number": 20,
                    "title": "Scam Bounty without link",
                    "body": "I will give $1000 for this",
                    "html_url": "https://github.com/scam-org/repo/issues/20",
                    "repository_url": "https://api.github.com/repos/scam-org/repo",
                    "labels": [{"name": "bounty"}]
                }
            ]
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_response).encode("utf-8")
        mock_resp.headers = {"X-RateLimit-Remaining": "10"}
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        results = bounty_scanner.search_github_bounties("test", token="dummy")
        self.assertEqual(len(results), 1, "Only verified Algora/IssueHunt bounties should be returned")
        self.assertEqual(results[0]["id"], "111")
        self.assertEqual(results[0]["platform"], "Algora")

if __name__ == "__main__":
    unittest.main()
