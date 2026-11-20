"""Programmatic session login for boorus that use cookies instead of API keys."""

import logging
import httpx
from core import settings


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


async def perform_login(
    site_url: str,
    api_type: str,
    username: str,
    password: str,
    bypass_session=None,  # Optional BypassSession for CF-protected login pages
) -> dict[str, str]:
    """POST the credentials and return {cookie_name: value} for the session cookies found.

    *bypass_session* supplies cf_clearance and the User-Agent for Cloudflare-protected logins.
    Returns {} on failure.
    """
    cfg = _LOGIN_CONFIGS.get(api_type)
    if not cfg:
        return {}

    path = cfg["path"]
    params = cfg.get("params", {})
    raw_fields = cfg.get("fields", {})

    fields = {
        k: v.replace("{username}", username).replace("{password}", password)
        for k, v in raw_fields.items()
    }

    url = site_url + path

    from core.validation import is_private_host, same_site
    from urllib.parse import urljoin, urlparse
    parsed_site = urlparse(site_url)
    if parsed_site.scheme != "https" and not is_private_host(parsed_site.hostname or ""):
        logging.error("[session_login] Refusing to send a password over plain http to %s",
                      parsed_site.hostname)
        return {}

    headers = {
        "User-Agent": settings.manager.get_user_agent(),
        "Referer": site_url + "/",
    }
    if bypass_session is not None:
        headers["User-Agent"] = bypass_session.user_agent
        if bypass_session.cookies:
            # As a header on our own request only; a client-level jar would
            # send these domain-less cookies to every redirect target.
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in bypass_session.cookies.items())

    site_host = (parsed_site.hostname or "").lower().rstrip(".")

    def _on_site(cookie_domain: str) -> bool:
        d = (cookie_domain or "").lstrip(".").lower()
        if site_host and "." not in site_host and ":" not in site_host:
            # Dotless site (localhost, nas): the cookiejar stores host-only
            # cookies as "<host>.local". Exact host only, no site_key logic.
            return d in (site_host, site_host + ".local")
        return bool(d) and same_site(f"https://{d}/", site_url)

    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=False,
                                     timeout=15.0) as client:
            if cfg.get("method", "POST") == "POST":
                r = await client.post(url, data=fields, params=params)
            else:
                r = await client.get(url, params={**params, **fields})

            # Follow redirects by hand: same site only, and never re-POST
            # the credentials (httpx would for 307/308).
            for _ in range(5):
                if not r.is_redirect:
                    break
                nxt = urljoin(str(r.url), r.headers.get("location", ""))
                if not same_site(nxt, site_url):
                    logging.warning("[session_login] Not following login redirect to %s",
                                    urlparse(nxt).hostname)
                    break
                client.headers.pop("Cookie", None)   # the jar carries site cookies now
                r = await client.get(nxt)

            harvested = {}
            target_names = set(get_session_cookie_names(api_type))
            for cookie in client.cookies.jar:
                if cookie.name in target_names and cookie.value and _on_site(cookie.domain):
                    harvested[cookie.name] = cookie.value
            return harvested

    except Exception as e:
        logging.error(f"[session_login] Login attempt failed for {api_type} at {url}: {e}")
        return {}
