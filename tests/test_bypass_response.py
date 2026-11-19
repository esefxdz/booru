"""
tests/test_bypass_response.py — Unit tests for BypassResponse.
"""

import unittest
import json

from ui import settings_view as settings  # noqa: F401  # avoid circular import
from cloudflare_bypasser.engines import BypassResponse


class TestBypassResponseConstruction(unittest.TestCase):

    def test_simple_200(self):
        r = BypassResponse(b"hello", "hello", 200, "http://example.com", None, "curl_cffi", {})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, b"hello")
        self.assertEqual(r.text, "hello")
        self.assertEqual(r.url, "http://example.com")
        self.assertEqual(r.engine_used, "curl_cffi")
        self.assertIsNone(r._json_data)
        self.assertEqual(r.cookies, {})

    def test_with_cookies(self):
        cookies = {"cf_clearance": "abc123", "session": "xyz"}
        r = BypassResponse(b"", "", 200, "http://x.com", None, "httpx", cookies)
        self.assertEqual(r.cookies, cookies)

    def test_with_json_data(self):
        data = {"posts": [1, 2, 3]}
        r = BypassResponse(b"", "", 200, "http://x.com", data, "requests", {})
        self.assertEqual(r._json_data, data)

    def test_zero_status_total_failure(self):
        r = BypassResponse(b"", "", 0, "http://x.com", None, "none", {})
        self.assertEqual(r.status_code, 0)
        self.assertIsNone(r._json_data)


class TestBypassResponseIsBlocked(unittest.TestCase):

    def test_200_not_blocked(self):
        r = BypassResponse(b"ok", "ok", 200, "http://x.com", None, "curl_cffi", {})
        self.assertFalse(r.is_blocked)

    def test_403_short_is_blocked(self):
        body = b"<html>cloudflare</html>"
        r = BypassResponse(body, body.decode(), 403, "http://x.com", None, "curl_cffi", {})
        self.assertTrue(r.is_blocked)

    def test_403_short_body_blocked(self):
        """Any 403 with body under 200 bytes is treated as a CF block (heuristic)."""
        body = b"Access denied"
        r = BypassResponse(body, body.decode(), 403, "http://x.com", None, "curl_cffi", {})
        self.assertTrue(r.is_blocked)

    def test_403_large_body_not_cf(self):
        """A large 403 body without CF markers is a real server response."""
        body = b"<html>" + b"x" * 500 + b"<h1>Forbidden</h1></html>"
        r = BypassResponse(body, body.decode(), 403, "http://x.com", None, "curl_cffi", {})
        self.assertFalse(r.is_blocked)

    def test_503_with_cf_challenge(self):
        body = b"<title>Just a moment...</title>"
        r = BypassResponse(body, body.decode(), 503, "http://x.com", None, "cloudscraper", {})
        self.assertTrue(r.is_blocked)

    def test_cf_ray_with_challenge(self):
        body = b"cf-ray: 12345\nchallenge detected"
        r = BypassResponse(body, body.decode(), 403, "http://x.com", None, "httpx", {})
        self.assertTrue(r.is_blocked)

    def test_attention_required(self):
        body = b"<title>Attention Required! | Cloudflare</title>"
        r = BypassResponse(body, body.decode(), 403, "http://x.com", None, "urllib", {})
        self.assertTrue(r.is_blocked)


class TestBypassResponseJson(unittest.TestCase):

    def test_json_from_preset_data(self):
        data = {"key": "value"}
        r = BypassResponse(b"", "", 200, "http://x.com", data, "curl_cffi", {})
        self.assertEqual(r.json(), data)

    def test_json_parses_text(self):
        payload = {"a": 1, "b": [2, 3]}
        text = json.dumps(payload)
        r = BypassResponse(text.encode(), text, 200, "http://x.com", None, "curl_cffi", {})
        self.assertEqual(r.json(), payload)

    def test_json_invalid_raises(self):
        r = BypassResponse(b"not json", "not json", 200, "http://x.com", None, "curl_cffi", {})
        with self.assertRaises(json.JSONDecodeError):
            r.json()

    def test_json_cached(self):
        data = {"x": 1}
        r = BypassResponse(b"", "", 200, "http://x.com", data, "curl_cffi", {})
        first = r.json()
        second = r.json()
        self.assertIs(first, second)


class TestBypassResponseRepr(unittest.TestCase):

    def test_repr(self):
        r = BypassResponse(b"x", "x", 200, "http://example.com/posts", None, "curl_cffi", {})
        s = repr(r)
        self.assertIn("200", s)
        self.assertIn("curl_cffi", s)


if __name__ == "__main__":
    unittest.main()
