#!/usr/bin/env python3
"""
Unit tests for Pre-Commit Secret Guard
Verifies that prohibited secrets trigger a commit block and clean files pass.
"""

import unittest
import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from scripts.secret_guard import scan_content

class TestSecretGuard(unittest.TestCase):
    def test_clean_content_passes(self):
        clean_code = """
        def calculate_net_revenue(gross: float, fees: float) -> float:
            return gross - fees
        """
        violations = scan_content(clean_code, "clean_file.py")
        self.assertEqual(len(violations), 0, "Clean code should produce 0 violations")

    def test_evm_private_key_triggers_guard(self):
        leaked_key_content = f"MY_CONFIG = {{'{''.join(['EVM_', 'PRIVATE_KEY'])}': '0x1234567890abcdef'}}"
        violations = scan_content(leaked_key_content, "config.py")
        self.assertGreater(len(violations), 0, "Guard must trigger on EVM private key")
        self.assertTrue(any("EVM private key" in v for v in violations))

    def test_stripe_secret_key_triggers_guard(self):
        leaked_stripe_content = f"STRIPE = '{''.join(['STRIPE_', 'SECRET_KEY'])}=sk_live_123456789'"
        violations = scan_content(leaked_stripe_content, "payment.py")
        self.assertGreater(len(violations), 0, "Guard must trigger on Stripe secret key")
        self.assertTrue(any("Stripe secret key" in v for v in violations))

    def test_pem_private_key_triggers_guard(self):
        pem_content = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...\n-----END RSA PRIVATE KEY-----"
        violations = scan_content(pem_content, "server.key")
        self.assertGreater(len(violations), 0, "Guard must trigger on PEM private key header")
        self.assertTrue(any("PEM" in v for v in violations))

if __name__ == "__main__":
    unittest.main()
