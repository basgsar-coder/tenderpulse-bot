#!/usr/bin/env python3
"""
Unit tests for Pre-Commit & CI Secret Guard
Verifies detection across 7 credential classes and confirms matched secret values are never echoed in violation messages.
"""

import unittest
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from scripts.secret_guard import scan_content

class TestHardenedSecretGuard(unittest.TestCase):
    def test_clean_content_produces_zero_violations(self):
        clean_code = "def add(a, b): return a + b\n"
        violations = scan_content(clean_code, "clean.py")
        self.assertEqual(len(violations), 0)

    def test_github_tokens_detected_without_secret_leak(self):
        # Classic PAT
        classic_pat = "".join(["ghp_", "1234567890abcdef1234567890abcdef1234"])
        content = f"TOKEN = '{classic_pat}'"
        violations = scan_content(content, "config.py")
        self.assertGreater(len(violations), 0)
        self.assertIn("Classic", violations[0])
        self.assertNotIn(classic_pat, violations[0], "Secret value MUST NOT be printed in violation message")

        # Fine-Grained PAT
        fine_pat = "".join(["github_pat_", "A" * 85])
        content_fg = f"PAT = '{fine_pat}'"
        violations_fg = scan_content(content_fg, "deploy.py")
        self.assertGreater(len(violations_fg), 0)
        self.assertIn("Fine-Grained", violations_fg[0])
        self.assertNotIn(fine_pat, violations_fg[0])

    def test_llm_and_cloud_keys_detected(self):
        # OpenAI key
        openai_key = "".join(["sk-", "proj-", "1234567890abcdefghijklmnopqr"])
        v_openai = scan_content(f"KEY = '{openai_key}'", "ai.py")
        self.assertGreater(len(v_openai), 0)
        self.assertIn("OpenAI", v_openai[0])
        self.assertNotIn(openai_key, v_openai[0])

        # Gemini key
        gemini_key = "".join(["AIza", "SyD1234567890abcdefghijklmnopqrstuv"])
        v_gemini = scan_content(f"GEMINI = '{gemini_key}'", "ai.py")
        self.assertGreater(len(v_gemini), 0)
        self.assertIn("Gemini", v_gemini[0])
        self.assertNotIn(gemini_key, v_gemini[0])

        # AWS Access Key
        aws_key = "".join(["AKIA", "IOSFODNN7EXAMPLE"])
        v_aws = scan_content(f"AWS_KEY = '{aws_key}'", "aws.py")
        self.assertGreater(len(v_aws), 0)
        self.assertIn("AWS", v_aws[0])
        self.assertNotIn(aws_key, v_aws[0])

    def test_raw_private_keys_and_pem_detected(self):
        # 64-hex key
        raw_key = "".join(["0x", "a" * 64])
        v_raw = scan_content(f"PRIV = '{raw_key}'", "wallet.py")
        self.assertGreater(len(v_raw), 0)
        self.assertIn("Private Key", v_raw[0])
        self.assertNotIn(raw_key, v_raw[0])

        # PEM block
        pem_block = "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----"
        v_pem = scan_content(pem_block, "server.key")
        self.assertGreater(len(v_pem), 0)
        self.assertIn("PEM", v_pem[0])

if __name__ == "__main__":
    unittest.main()
