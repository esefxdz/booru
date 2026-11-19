"""
tests/test_session_fingerprint.py — Unit tests for session cache invalidation.

Tests that the session fingerprint changes when cookies, UA, proxy, or method
change — and that get_session() reuses sessions when nothing has changed.
"""

import unittest

from ui import settings_view as settings
from cloudflare_bypasser import store, get_session, invalidate_session


class TestSessionFingerprint(unittest.TestCase):

    def setUp(self):
        settings.manager.bypass_data.pop("_test_fp_", None)
        invalidate_session("_test_fp_")

    def tearDown(self):
        settings.manager.bypass_data.pop("_test_fp_", None)
        invalidate_session("_test_fp_")

    # ── Same fingerprint → same session ───────────────────────────

    def test_same_fingerprint_returns_cached_session(self):
        store.save_bypass("_test_fp_", {"cf_clearance": "abc"}, "TestUA/1.0")
        s1 = get_session("_test_fp_")
        s2 = get_session("_test_fp_")
        self.assertIs(s1, s2, "get_session should return the same cached instance")

    # ── Cookie change → new session ───────────────────────────────

    def test_cookie_change_invalidates_session(self):
        store.save_bypass("_test_fp_", {"cf_clearance": "abc"}, "TestUA/1.0")
        s1 = get_session("_test_fp_")

        # Change the stored cookies
        store.save_bypass("_test_fp_", {"cf_clearance": "xyz"}, "TestUA/1.0")
        s2 = get_session("_test_fp_")
        self.assertIsNot(s1, s2, "cookie change should create a new session")

    # ── UA change → new session ───────────────────────────────────

    def test_ua_change_invalidates_session(self):
        store.save_bypass("_test_fp_", {"cf_clearance": "abc"}, "UA_One/1.0")
        s1 = get_session("_test_fp_")

        store.save_bypass("_test_fp_", {"cf_clearance": "abc"}, "UA_Two/2.0")
        s2 = get_session("_test_fp_")
        self.assertIsNot(s1, s2, "UA change should create a new session")

    # ── invalidate_session clears cache ───────────────────────────

    def test_invalidate_clears_session(self):
        store.save_bypass("_test_fp_", {"cf_clearance": "abc"}, "UA")
        s1 = get_session("_test_fp_")
        invalidate_session("_test_fp_")
        s2 = get_session("_test_fp_")
        self.assertIsNot(s1, s2, "invalidate_session should force a new BypassSession")

    # ── No stored data → session still created ────────────────────

    def test_no_stored_data_creates_session(self):
        """Even with no bypass data, get_session returns a working session."""
        s = get_session("_test_fp_")
        self.assertIsNotNone(s)
        self.assertEqual(s.cookies, {})


class TestEngineOrder(unittest.TestCase):
    """Engine selection logic."""

    def test_auto_method_returns_all_engines(self):
        from cloudflare_bypasser.fingerprint import ENGINE_ORDER
        from cloudflare_bypasser.session import BypassSession
        s = BypassSession(method="auto")
        order = s._get_engine_order()
        self.assertEqual(order, list(ENGINE_ORDER))

    def test_locked_method_returns_only_that_engine(self):
        from cloudflare_bypasser.session import BypassSession
        s = BypassSession(method="urllib")
        order = s._get_engine_order()
        self.assertEqual(order, ["urllib"])

    def test_invalid_method_falls_back_to_auto(self):
        from cloudflare_bypasser.session import BypassSession
        s = BypassSession(method="nonexistent_engine")
        order = s._get_engine_order()
        # Should fall back to auto → all engines
        self.assertGreater(len(order), 1)


if __name__ == "__main__":
    unittest.main()
