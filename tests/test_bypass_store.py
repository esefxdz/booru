"""
tests/test_bypass_store.py — Unit tests for cloudflare_bypasser.store.

Tests persistence round-trips: save → get_cookies → get_user_agent →
has_active_bypass → clear_bypass.
"""

import unittest

from ui import settings_view as settings
from cloudflare_bypasser import store


class TestBypassStore(unittest.TestCase):

    def setUp(self):
        """Ensure clean state before each test."""
        # Wipe any existing bypass data for our test booru
        settings.manager.bypass_data.pop("_test_booru_", None)

    def tearDown(self):
        """Clean up after each test."""
        settings.manager.bypass_data.pop("_test_booru_", None)

    # ── save / get round-trip ─────────────────────────────────────

    def test_save_and_get_cookies(self):
        store.save_bypass("_test_booru_", {"cf_clearance": "test_token"}, "Mozilla/5.0 TestUA")
        cookies = store.get_cookies("_test_booru_")
        self.assertEqual(cookies, {"cf_clearance": "test_token"})

    def test_save_and_get_user_agent(self):
        store.save_bypass("_test_booru_", {"cf_clearance": "x"}, "CustomUA/1.0")
        ua = store.get_user_agent("_test_booru_")
        self.assertEqual(ua, "CustomUA/1.0")

    def test_get_user_agent_default(self):
        """When no bypass data exists, returns the default Chrome UA."""
        ua = store.get_user_agent("_test_booru_")
        self.assertIn("Chrome", ua)
        self.assertIn("Mozilla", ua)

    # ── has_active_bypass ─────────────────────────────────────────

    def test_has_active_bypass_true(self):
        store.save_bypass("_test_booru_", {"cf_clearance": "abc"}, "UA")
        self.assertTrue(store.has_active_bypass("_test_booru_"))

    def test_has_active_bypass_false_empty(self):
        self.assertFalse(store.has_active_bypass("_test_booru_"))

    def test_has_active_bypass_false_cleared(self):
        store.save_bypass("_test_booru_", {"cf_clearance": "abc"}, "UA")
        store.clear_bypass("_test_booru_")
        self.assertFalse(store.has_active_bypass("_test_booru_"))

    # ── clear_bypass ──────────────────────────────────────────────

    def test_clear_removes_cookies(self):
        store.save_bypass("_test_booru_", {"cf_clearance": "x", "session": "y"}, "UA")
        store.clear_bypass("_test_booru_")
        cookies = store.get_cookies("_test_booru_")
        self.assertEqual(cookies, {})

    def test_clear_idempotent(self):
        """Clearing a non-existent entry should not raise."""
        store.clear_bypass("_test_booru_nonexistent_")

    # ── Multiple cookies ──────────────────────────────────────────

    def test_multiple_cookies(self):
        cookies = {"cf_clearance": "tok", "__cf_bm": "bm", "session": "sess"}
        store.save_bypass("_test_booru_", cookies, "UA")
        self.assertEqual(store.get_cookies("_test_booru_"), cookies)

    # ── Legacy data migration (cf_clearance stored directly) ────

    def test_legacy_cf_clearance_format(self):
        """Older versions stored cf_clearance directly, not inside a cookies dict."""
        settings.manager.bypass_data["_test_booru_"] = {"cf_clearance": "old_token"}
        cookies = store.get_cookies("_test_booru_")
        self.assertIn("cf_clearance", cookies)
        self.assertEqual(cookies["cf_clearance"], "old_token")


if __name__ == "__main__":
    unittest.main()
