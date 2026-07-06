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