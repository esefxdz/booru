"""
adapters/session_login.py

Session-based login support for boorus that require cookies instead of API keys.

Most booru engines share nearly identical login patterns — this module centralises
that logic so per-site adapters only need to declare what's different.

Login flow:
  1. Caller provides username + password
  2. We POST to the site's login endpoint
  3. We harvest the session cookie from the response
  4. Caller stores the cookie value in settings.manager.session_keys[booru]
  5. downloader._get_client_args() injects it into every subsequent request
"""

import httpx


# ---------------------------------------------------------------------------
# Cookie name mapping: which cookie does each api_type use?
# ---------------------------------------------------------------------------
SESSION_COOKIE_NAMES: dict[str, list[str]] = {
    "gelbooru":   ["PHPSESSID"],
    "shimmie2":   ["shm_session", "PHPSESSID"],
    "moebooru":   ["_session_id"],
    "danbooru":   [],   # danbooru uses API key, not session cookies
    "philomena":  [],   # philomena uses API key
    "e621":       [],   # e621 uses API key + Basic Auth
    "szurubooru": [],   # uses token header, not cookies
    "zerochan":   ["z_key", "PHPSESSID"],
    "html_scraper": ["PHPSESSID"],
}

# Login path and POST field names per api_type
_LOGIN_CONFIGS: dict[str, dict] = {
    "gelbooru": {
        "path": "/index.php",
        "params": {"page": "account", "s": "login", "code": "00"},
        "fields": {"user": "{username}", "pass": "{password}"},
        "method": "POST",
    },
    "shimmie2": {
        "path": "/user_admin/login",
        "params": {},
        "fields": {"user": "{username}", "pass": "{password}"},
        "method": "POST",
    },
    "moebooru": {
        "path": "/user/login.json",
        "params": {},
        "fields": {"user[name]": "{username}", "user[password]": "{password}"},
        "method": "POST",
    },
    "zerochan": {
        "path": "/login",
        "params": {},
        "fields": {"ref": "/", "login": "{username}", "password": "{password}"},
        "method": "POST",
    },
    "html_scraper": {
        "path": "/index.php",
        "params": {"page": "account", "s": "login", "code": "00"},
        "fields": {"user": "{username}", "pass": "{password}"},
        "method": "POST",
    },
}


def get_session_cookie_names(api_type: str) -> list[str]:
    """Return the list of session cookie names for a given API type."""
    return SESSION_COOKIE_NAMES.get(api_type, ["PHPSESSID"])


def get_login_url(site_url: str, api_type: str) -> str:
    """Return the login page URL for a given booru site."""
    cfg = _LOGIN_CONFIGS.get(api_type)
    if not cfg:
        return site_url
    return site_url + cfg["path"]


def supports_session_login(api_type: str) -> bool:
    """Returns True if this api_type supports automated session login."""
    return api_type in _LOGIN_CONFIGS and bool(_LOGIN_CONFIGS[api_type].get("fields"))


async def perform_login(site_url: str, api_type: str, username: str, password: str) -> dict[str, str]:
    """
    Attempts a programmatic login (POST credentials) and returns a dict of
    {cookie_name: cookie_value} for any session cookies found in the response.

    Returns an empty dict on failure.
    Falls back gracefully — the caller should use InAppBrowser if this returns empty.
    """
    cfg = _LOGIN_CONFIGS.get(api_type)
    if not cfg:
        return {}

    path = cfg["path"]
    params = cfg.get("params", {})
    raw_fields = cfg.get("fields", {})

    # Substitute username/password into field values
    fields = {
        k: v.replace("{username}", username).replace("{password}", password)
        for k, v in raw_fields.items()
    }

    url = site_url + path
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": site_url + "/",
    }

    try:
        async with httpx.AsyncClient(
            headers=headers,
            follow_redirects=True,
            timeout=15.0,
        ) as client:
            if cfg.get("method", "POST") == "POST":
                r = await client.post(url, data=fields, params=params)
            else:
                r = await client.get(url, params={**params, **fields})

            # Harvest cookies from the response + the client's cookie jar
            harvested = {}
            target_names = set(get_session_cookie_names(api_type))

            for cookie in r.cookies.jar:
                if cookie.name in target_names and cookie.value:
                    harvested[cookie.name] = cookie.value

            for cookie in client.cookies.jar:
                if cookie.name in target_names and cookie.value:
                    harvested[cookie.name] = cookie.value

            return harvested

    except Exception as e:
        print(f"[session_login] Login attempt failed for {api_type} at {url}: {e}")
        return {}
