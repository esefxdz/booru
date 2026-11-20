"""Credentials sent as query parameters never reach the log, even at DEBUG."""
import logging
import socket

import pytest

from core import settings  # noqa: F401  # avoid circular import
from cloudflare_bypasser import engines
from core.validation import redact_secrets

SECRET_PARAMS = {"api_key": "SECRETKEY123", "user_id": "SECRETUID9", "login": "SECRETLOGIN",
                 "pass_hash": "SECRETHASH", "tags": "cat"}


def _dead_url():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()                       # nothing listens: connection refused
    return f"http://127.0.0.1:{port}/index.php"


@pytest.mark.parametrize("engine", ["urllib", "requests"])
def test_failed_request_debug_log_has_no_credentials(engine, caplog):
    fn = {"urllib": engines._try_urllib_sync, "requests": engines._try_requests_sync}[engine]
    if engine == "requests" and not engines._HAS_REQUESTS:
        pytest.skip("requests not installed")
    caplog.set_level(logging.DEBUG, logger="cloudflare_bypasser")
    assert fn(_dead_url(), dict(SECRET_PARAMS), {}, {}, "", 2) is None
    text = caplog.text
    assert "failed for" in text                      # the line was logged
    assert "SECRET" not in text, text
    assert "tags=cat" in text or "index.php" in text


def test_redact_secrets_masks_only_credential_params():
    url = "https://x.org/a?tags=key_art&api_key=AB&key=CD&user_id=1&page=2&password=p"
    assert redact_secrets(url) == ("https://x.org/a?tags=key_art&api_key=***&key=***"
                                   "&user_id=***&page=2&password=***")
