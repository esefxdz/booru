"""Validation and sanitising for user input and server-supplied URLs, ids and extensions."""
import re
from urllib.parse import urlparse
from typing import Optional


class ValidationError(ValueError):
    """Raised when input validation fails."""
    pass


def validate_search_term(term: str, max_length: int = 500) -> str:
    """Cap length and normalise whitespace; deliberately no character filtering (<, >, / are valid operators)."""
    if not isinstance(term, str):
        raise ValidationError("Search term must be a string")

    term = " ".join(term.split())

    if len(term) > max_length:
        raise ValidationError(f"Search term too long (max {max_length} characters)")

    return term


def validate_url(url: str, allow_schemes: tuple = ('http', 'https')) -> str:
    """Return the stripped URL or raise ValidationError."""
    if not isinstance(url, str):
        raise ValidationError("URL must be a string")

    url = url.strip()

    if not url:
        raise ValidationError("URL cannot be empty")

    try:
        parsed = urlparse(url)

        if not parsed.scheme:
            raise ValidationError("URL must include scheme (http/https)")

        if parsed.scheme not in allow_schemes:
            raise ValidationError(f"URL scheme '{parsed.scheme}' not allowed")

        if not parsed.netloc:
            raise ValidationError("URL must include a valid domain")

        if parsed.hostname in ('localhost', '127.0.0.1', '::1'):
            raise ValidationError("Localhost URLs not allowed")

        if len(url) > 2048:
            raise ValidationError("URL too long")

    except Exception as e:
        raise ValidationError(f"Invalid URL format: {e}")

    return url


def validate_filename(filename: str, max_length: int = 255) -> str:
    """Sanitise a filename; raises ValidationError on path traversal."""
    if not isinstance(filename, str):
        raise ValidationError("Filename must be a string")

    filename = filename.strip()

    if not filename:
        raise ValidationError("Filename cannot be empty")

    if len(filename) > max_length:
        raise ValidationError(f"Filename too long (max {max_length} characters)")

    sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)
    sanitized = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', sanitized)

    if '..' in sanitized or sanitized.startswith('/') or '\\' in sanitized:
        raise ValidationError("Filename contains invalid path characters")

    return sanitized


def validate_directory_name(dirname: str, max_length: int = 100) -> str:
    """Sanitise a directory name; raises ValidationError on path traversal."""
    if not isinstance(dirname, str):
        raise ValidationError("Directory name must be a string")

    dirname = dirname.strip()

    if not dirname:
        raise ValidationError("Directory name cannot be empty")

    if len(dirname) > max_length:
        raise ValidationError(f"Directory name too long (max {max_length} characters)")

    sanitized = re.sub(r'[<>:"/\\|?*<>]', '_', dirname)
    sanitized = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', sanitized)

    if '..' in sanitized or sanitized.startswith('/') or '\\' in sanitized:
        raise ValidationError("Directory name contains invalid path characters")

    return sanitized


def validate_integer(value: str, min_val: Optional[int] = None, max_val: Optional[int] = None) -> int:
    """Parse *value* as an int within optional bounds, or raise ValidationError."""
    if not isinstance(value, str):
        raise ValidationError("Value must be a string")

    try:
        int_val = int(value.strip())
    except ValueError:
        raise ValidationError("Value must be a valid integer")

    if min_val is not None and int_val < min_val:
        raise ValidationError(f"Value must be at least {min_val}")

    if max_val is not None and int_val > max_val:
        raise ValidationError(f"Value must be at most {max_val}")

    return int_val


def sanitize_tag_list(tags: str) -> str:
    """Collapse whitespace and cap at 1000 characters."""
    if not isinstance(tags, str):
        return ""

    tags = re.sub(r'\s+', ' ', tags.strip())

    if len(tags) > 1000:
        tags = tags[:1000]

    return tags


# Everything below handles server-controlled values; force them into a safe
# shape before use in a request or file path.

import hashlib as _hashlib
import os as _os
from pathlib import Path as _Path
from urllib.parse import urljoin as _urljoin

# Extensions we write to disk; anything else becomes ".bin" (no .bat/.exe/.lnk from a server).
ALLOWED_MEDIA_EXTS = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp", ".jxl",
    ".mp4", ".webm", ".mkv", ".mov", ".m4v",
    ".zip",  # Danbooru ugoira
})

_POST_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


def _ambiguous_authority(url: str) -> bool:
    r"""True for URLs whose host parsers disagree on, e.g. ``https://evil.example\@booru.com/``.

    urllib.parse sees booru.com but urllib3 sees evil.example, which would defeat same-site checks.
    """
    if "\\" in url:
        return True
    try:
        p = urlparse(url)
    except ValueError:
        return True
    return "@" in (p.netloc or "") or p.username is not None or p.password is not None


def require_http_url(url: str, base: Optional[str] = None) -> str:
    """Return *url* as an absolute http(s) URL (relative ones resolved against *base*), or raise ValidationError."""
    if not isinstance(url, str) or not url.strip():
        raise ValidationError("URL is empty")
    url = url.strip()
    if any(c in url for c in "\r\n\x00"):
        raise ValidationError("URL contains control characters")
    if _ambiguous_authority(url):
        raise ValidationError(f"Refusing ambiguous URL: {url[:80]!r}")
    if url.startswith("//"):
        url = "https:" + url
    elif base and not urlparse(url).scheme:
        url = _urljoin(base.rstrip("/") + "/", url)
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValidationError(f"Refusing non-http(s) URL: {url[:80]!r}")
    return url


def safe_post_id(post_id) -> str:
    """Return a filename-safe post id; unusual ids become a stable hash."""
    s = str(post_id if post_id is not None else "").strip()
    if _POST_ID_RE.match(s):
        return s
    return "id_" + _hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()[:16]


def media_extension(url: str, default: str = ".jpg") -> str:
    """Allow-listed extension of *url*'s path: *default* if none, ".bin" if not allowed."""
    path = urlparse(url or "").path
    ext = _os.path.splitext(path)[1].lower()
    if not ext:
        return default
    return ext if ext in ALLOWED_MEDIA_EXTS else ".bin"


def safe_media_path(folder, post_id, url: str, prefix: str = "", default_ext: str = ".jpg") -> _Path:
    """Build ``folder / f"{prefix}{id}{ext}"``; raises ValidationError if it would escape *folder*."""
    folder = _Path(folder)
    name = f"{prefix}{safe_post_id(post_id)}{media_extension(url, default_ext)}"
    dest = folder / name
    if dest.resolve().parent != folder.resolve():
        raise ValidationError(f"Refusing to write outside {folder}: {name!r}")
    return dest


# Cookie scoping: cookies are stored without their domain, so these helpers
# decide whether a URL is the booru's own site.

import ipaddress as _ipaddress

# Second-level labels that are public suffixes under a ccTLD (co.uk, com.au...).
_SLD_SUFFIXES = frozenset({"co", "com", "net", "org", "ac", "gov", "edu", "ne", "or", "go"})


def site_key(host: str) -> str:
    """Approximate registrable domain ("img3.gelbooru.com" -> "gelbooru.com").

    A heuristic, not the Public Suffix List; errs toward a longer key.
    """
    host = (host or "").strip().lower().rstrip(".")
    try:
        _ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    if len(labels[-1]) == 2 and labels[-2] in _SLD_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def is_private_host(host: str) -> bool:
    """True for localhost / loopback / LAN addresses (self-hosted boorus)."""
    host = (host or "").strip().lower().rstrip(".")
    if host in ("localhost",) or host.endswith(".local") or host.endswith(".lan"):
        return True
    try:
        ip = _ipaddress.ip_address(host)
    except ValueError:
        # Bare intranet names ("nas") are private; digit-leading ones are excluded
        # because the OS resolver reads "134744072" as an IPv4 address.
        return bool(re.fullmatch(r"[a-z_][a-z0-9_-]*", host))
    return ip.is_private or ip.is_loopback or ip.is_link_local


def same_site(url: str, site_url: str) -> bool:
    """True if *url* belongs to the same registrable domain as *site_url*."""
    if _ambiguous_authority(url or "") or _ambiguous_authority(site_url or ""):
        return False
    try:
        a = urlparse(url or "").hostname
        b = urlparse(site_url or "").hostname
    except ValueError:
        return False
    if not a or not b:
        return False
    return site_key(a) == site_key(b)


import urllib.request as _urllib_request


class SameSiteRedirectHandler(_urllib_request.HTTPRedirectHandler):
    """Drop Cookie/Authorization on cross-site redirects and refuse non-http(s) targets."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            require_http_url(newurl)
        except ValidationError:
            return None
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and not same_site(newurl, req.full_url):
            for h in ("Cookie", "Authorization"):
                new.remove_header(h)
                new.unredirected_hdrs.pop(h, None)
            # Request stores header names capitalized.
            for k in list(new.headers):
                if k.lower() in ("cookie", "authorization"):
                    del new.headers[k]
        return new


# Query parameters that carry credentials (adapters' build_params).
_SECRET_PARAM_RE = re.compile(
    r"(?<=[?&;])(api_key|key|user_id|login|pass_hash|password_hash|password|"
    r"access_token|token)=[^&#\s'\"]*",
    re.IGNORECASE,
)


def redact_secrets(text) -> str:
    """Mask credential query-parameter values in *text* for logging."""
    return _SECRET_PARAM_RE.sub(lambda m: m.group(1) + "=***", str(text))
