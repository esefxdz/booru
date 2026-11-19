"""
tests/test_cookie_extraction.py — Unit tests for _extract_cookies and engine utilities.
"""

import unittest

from cloudflare_bypasser.engines import _extract_cookies


class TestExtractCookies(unittest.TestCase):
    """Cookie extraction from various response-like objects."""

    def test_empty_response_no_cookies(self):
        """A response with no cookie attributes returns empty dict."""
        class FakeResp:
            pass
        result = _extract_cookies(FakeResp())
        self.assertEqual(result, {})

    def test_dict_cookies(self):
        """A response with .cookies as a plain dict."""
        class FakeResp:
            cookies = {"cf_clearance": "abc", "session": "xyz"}
        result = _extract_cookies(FakeResp())
        self.assertEqual(result, {"cf_clearance": "abc", "session": "xyz"})

    def test_jar_with_items(self):
        """A response with .cookies that supports .items()."""
        class FakeJar:
            def items(self):
                return [("cf_clearance", "val1"), ("__cf_bm", "val2")]
        class FakeResp:
            cookies = FakeJar()
        result = _extract_cookies(FakeResp())
        self.assertEqual(result, {"cf_clearance": "val1", "__cf_bm": "val2"})

    def test_jar_with_get_dict(self):
        """curl_cffi Cookies objects support .get_dict()."""
        class FakeJar:
            def get_dict(self):
                return {"a": "1", "b": "2"}
        class FakeResp:
            cookies = FakeJar()
        result = _extract_cookies(FakeResp())
        self.assertEqual(result, {"a": "1", "b": "2"})

    def test_set_cookie_header_parsing(self):
        """Fallback parsing of Set-Cookie header string."""
        class FakeResp:
            cookies = None
            headers = {"Set-Cookie": "cf_clearance=token123"}
        result = _extract_cookies(FakeResp())
        self.assertIn("cf_clearance", result)
        self.assertEqual(result["cf_clearance"], "token123")

    def test_malformed_response_no_crash(self):
        """A response that raises during cookie access returns empty dict."""
        class BrokenResp:
            @property
            def cookies(self):
                raise RuntimeError("boom")
        result = _extract_cookies(BrokenResp())
        self.assertEqual(result, {})

    def test_set_cookie_filters_attributes(self):
        """Set-Cookie attributes (path, domain, etc.) are filtered out."""
        class FakeResp:
            cookies = None
            headers = {
                "Set-Cookie": "cf_clearance=abc; path=/; domain=.example.com; HttpOnly; Secure"
            }
        result = _extract_cookies(FakeResp())
        self.assertEqual(result, {"cf_clearance": "abc"})
        self.assertNotIn("path", result)
        self.assertNotIn("domain", result)
        self.assertNotIn("HttpOnly", result)
        self.assertNotIn("Secure", result)


class TestGetAvailableEngines(unittest.TestCase):
    """Engine availability detection."""

    def test_urllib_always_available(self):
        from cloudflare_bypasser.fingerprint import get_available_engines
        engines = get_available_engines()
        self.assertIn("urllib", engines, "urllib (stdlib) should always be available")

    def test_engine_order_is_valid(self):
        from cloudflare_bypasser.fingerprint import ENGINE_ORDER, get_available_engines
        available = get_available_engines()
        # Every engine in ENGINE_ORDER that is available should be listed
        for engine in ENGINE_ORDER:
            if engine == "curl_cffi":
                continue  # may or may not be installed
            if engine == "cloudscraper":
                continue
            if engine == "httpx":
                continue
            if engine == "requests":
                continue
            # urllib is always available
            self.assertIn(engine, available)


if __name__ == "__main__":
    unittest.main()
