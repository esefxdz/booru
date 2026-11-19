"""
validation.py — Input validation utilities.

Provides secure validation for user inputs to prevent injection attacks,
path traversal, and other security vulnerabilities.
"""
import re
from urllib.parse import urlparse
from typing import Optional


class ValidationError(ValueError):
    """Raised when input validation fails."""
    pass


def validate_search_term(term: str, max_length: int = 500) -> str:
    """
    Validate search terms for booru queries.

    Booru search syntax is rich: operators like ``score:>=50``, ``id:>1500000``,
    ``order:score``, ``filetype:png/webp``, and negation tags (``-tag``) are all
    legitimate.  A regex that strips ``<``, ``>``, ``/``, or ``[`` will silently
    corrupt these queries and return wrong results with no error message.

    This function only enforces a length cap and normalises whitespace.
    The Booru API itself will reject genuinely malformed syntax.

    Args:
        term: Search term string
        max_length: Maximum allowed length

    Returns:
        Validated and whitespace-normalised search term

    Raises:
        ValidationError: If term is not a string or exceeds max_length
    """
    if not isinstance(term, str):
        raise ValidationError("Search term must be a string")

    # Normalise whitespace
    term = " ".join(term.split())

    if len(term) > max_length:
        raise ValidationError(f"Search term too long (max {max_length} characters)")

    return term


def validate_url(url: str, allow_schemes: tuple = ('http', 'https')) -> str:
    """
    Validate URLs to prevent malicious redirects or injections.

    Args:
        url: URL string to validate
        allow_schemes: Allowed URL schemes

    Returns:
        Validated URL

    Raises:
        ValidationError: If URL is invalid
    """
    if not isinstance(url, str):
        raise ValidationError("URL must be a string")

    url = url.strip()

    if not url:
        raise ValidationError("URL cannot be empty")

    try:
        parsed = urlparse(url)

        # Must have a scheme
        if not parsed.scheme:
            raise ValidationError("URL must include scheme (http/https)")

        # Scheme must be allowed
        if parsed.scheme not in allow_schemes:
            raise ValidationError(f"URL scheme '{parsed.scheme}' not allowed")

        # Must have a netloc (domain)
        if not parsed.netloc:
            raise ValidationError("URL must include a valid domain")

        # Prevent localhost/private IP access (basic protection)
        if parsed.hostname in ('localhost', '127.0.0.1', '::1'):
            raise ValidationError("Localhost URLs not allowed")

        # Basic length check
        if len(url) > 2048:
            raise ValidationError("URL too long")

    except Exception as e:
        raise ValidationError(f"Invalid URL format: {e}")

    return url


def validate_filename(filename: str, max_length: int = 255) -> str:
    """
    Validate and sanitize filenames to prevent path traversal.

    Args:
        filename: Filename to validate
        max_length: Maximum allowed length

    Returns:
        Sanitized filename

    Raises:
        ValidationError: If filename is invalid
    """
    if not isinstance(filename, str):
        raise ValidationError("Filename must be a string")

    filename = filename.strip()

    if not filename:
        raise ValidationError("Filename cannot be empty")

    if len(filename) > max_length:
        raise ValidationError(f"Filename too long (max {max_length} characters)")

    # Remove or replace dangerous characters
    # Allow alphanumeric, dots, hyphens, underscores, spaces
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)

    # Remove control characters
    sanitized = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', sanitized)

    # Prevent directory traversal
    if '..' in sanitized or sanitized.startswith('/') or '\\' in sanitized:
        raise ValidationError("Filename contains invalid path characters")

    return sanitized


def validate_directory_name(dirname: str, max_length: int = 100) -> str:
    """
    Validate directory names for safe folder creation.

    Args:
        dirname: Directory name to validate
        max_length: Maximum allowed length

    Returns:
        Sanitized directory name

    Raises:
        ValidationError: If directory name is invalid
    """
    if not isinstance(dirname, str):
        raise ValidationError("Directory name must be a string")

    dirname = dirname.strip()

    if not dirname:
        raise ValidationError("Directory name cannot be empty")

    if len(dirname) > max_length:
        raise ValidationError(f"Directory name too long (max {max_length} characters)")

    # Similar to filename but allow spaces and be more restrictive
    sanitized = re.sub(r'[<>:"/\\|?*<>]', '_', dirname)

    # Remove control characters
    sanitized = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', sanitized)

    # Prevent directory traversal
    if '..' in sanitized or sanitized.startswith('/') or '\\' in sanitized:
        raise ValidationError("Directory name contains invalid path characters")

    return sanitized


def validate_integer(value: str, min_val: Optional[int] = None, max_val: Optional[int] = None) -> int:
    """
    Validate and convert string to integer.

    Args:
        value: String representation of integer
        min_val: Minimum allowed value (optional)
        max_val: Maximum allowed value (optional)

    Returns:
        Validated integer

    Raises:
        ValidationError: If value is invalid
    """
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
    """
    Sanitize tag lists for booru searches.

    Args:
        tags: Raw tag string

    Returns:
        Sanitized tag string
    """
    if not isinstance(tags, str):
        return ""

    # Remove excessive whitespace
    tags = re.sub(r'\s+', ' ', tags.strip())

    # Basic length limit
    if len(tags) > 1000:
        tags = tags[:1000]

    return tags

# ---------------------------------------------------------------------------
# Server-supplied data: URLs, post ids, file extensions
# ---------------------------------------------------------------------------
# Everything below handles values that come from a booru's API response.
# A malicious or compromised server controls them, so they are forced into a
# known-safe shape before being used in a request or a file path.

import hashlib as _hashlib
import os as _os
from pathlib import Path as _Path
from urllib.parse import urljoin as _urljoin

#: Extensions we are willing to write to disk. Anything else becomes ".bin"
#: so a server cannot make us write e.g. ``.bat``, ``.exe`` or ``.lnk``.
ALLOWED_MEDIA_EXTS = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp", ".jxl",
    ".mp4", ".webm", ".mkv", ".mov", ".m4v",
    ".zip",  # Danbooru ugoira
})

_POST_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


def require_http_url(url: str, base: Optional[str] = None) -> str:
    """Return *url* as an absolute http(s) URL, or raise ValidationError.

    Protocol-relative (``//host/x``) and relative (``/x``, ``x``) URLs are
    resolved against *base* when given. Rejects ``file:``, ``data:`` and any
    other scheme, which urllib, mpv and VLC would otherwise happily open.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValidationError("URL is empty")
    url = url.strip()
    if any(c in url for c in "\r\n\x00"):
        raise ValidationError("URL contains control characters")
    if url.startswith("//"):
        url = "https:" + url
    elif base and not urlparse(url).scheme:
        url = _urljoin(base.rstrip("/") + "/", url)
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValidationError(f"Refusing non-http(s) URL: {url[:80]!r}")
    return url


def safe_post_id(post_id) -> str:
    """Return a filename-safe form of a server-supplied post id.

    Ordinary ids (digits, or short alphanumeric hashes) are kept as-is.
    Anything else (path separators, "..", empty) is replaced with a stable
    hash so it can never contain a path separator.
    """
    s = str(post_id if post_id is not None else "").strip()
    if _POST_ID_RE.match(s):
        return s
    return "id_" + _hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()[:16]


def media_extension(url: str, default: str = ".jpg") -> str:
    """Return the lowercased, allow-listed extension of *url*'s path.

    No extension -> *default*. An extension not in ALLOWED_MEDIA_EXTS -> ".bin".
    """
    path = urlparse(url or "").path
    ext = _os.path.splitext(path)[1].lower()
    if not ext:
        return default
    return ext if ext in ALLOWED_MEDIA_EXTS else ".bin"


def safe_media_path(folder, post_id, url: str, prefix: str = "", default_ext: str = ".jpg") -> _Path:
    """Build ``folder / f"{prefix}{id}{ext}"`` and prove it stays in *folder*.

    Raises ValidationError if the result would escape *folder* (it cannot with
    the sanitising above, but this is the last line of defence).
    """
    folder = _Path(folder)
    name = f"{prefix}{safe_post_id(post_id)}{media_extension(url, default_ext)}"
    dest = folder / name
    if dest.resolve().parent != folder.resolve():
        raise ValidationError(f"Refusing to write outside {folder}: {name!r}")
    return dest


# ---------------------------------------------------------------------------
# Cookie scoping
# ---------------------------------------------------------------------------
# Bypass/session cookies are stored as a flat {name: value} dict without the
# domain they were issued for. These helpers decide whether a request URL is
# "the same site" as the booru, so cookies are never sent to third parties.

import ipaddress as _ipaddress

# Second-level labels that are public suffixes under a ccTLD (co.uk, com.au...).
_SLD_SUFFIXES = frozenset({"co", "com", "net", "org", "ac", "gov", "edu", "ne", "or", "go"})


def site_key(host: str) -> str:
    """Approximate registrable domain of *host* ("img3.gelbooru.com" -> "gelbooru.com").

    IP addresses and single-label hosts are returned unchanged. This is a
    small heuristic, not the full Public Suffix List; it errs on the side of
    a *longer* key (fewer hosts match) for ccTLD second-level suffixes.
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


def same_site(url: str, site_url: str) -> bool:
    """True if *url* belongs to the same registrable domain as *site_url*."""
    try:
        a = urlparse(url or "").hostname
        b = urlparse(site_url or "").hostname
    except ValueError:
        return False
    if not a or not b:
        return False
    return site_key(a) == site_key(b)
