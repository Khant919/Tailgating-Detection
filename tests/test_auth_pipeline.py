"""
tests/test_auth_pipeline.py
============================
Unit tests for the TwoFactorAuthenticator 2FA pipeline.
"""

import os
import time
import unittest
import numpy as np
from src.auth_pipeline import TwoFactorAuthenticator


class TestTwoFactorAuthenticator(unittest.TestCase):

    def setUp(self):
        self.authenticator = TwoFactorAuthenticator(known_faces_dir="known_faces", expiration_seconds=0.2)

    def test_active_sessions_expiration(self):
        """Tests that active sessions expire after expiration_seconds."""
        self.authenticator.active_sessions["Alice"] = time.time() - 1.0  # 1s ago (expired)
        self.authenticator._cleanup_expired_sessions()
        self.assertNotIn("Alice", self.authenticator.active_sessions)

    def test_scan_qr_empty_sessions(self):
        """Tests that scan_qr returns False/None early if no active sessions exist."""
        dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
        granted, name = self.authenticator.scan_qr(dummy_frame)
        self.assertFalse(granted)
        self.assertIsNone(name)


if __name__ == "__main__":
    unittest.main()
