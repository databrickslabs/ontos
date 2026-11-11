"""
HTML/Markdown sanitization utilities for preventing XSS attacks.

This module provides centralized sanitization functions using bleach
to clean user input and LLM-generated content before rendering in the UI.
"""

import re
from typing import Optional
from urllib.parse import urlparse

import bleach

# Branding constraints (issue #240)
APP_DISPLAY_NAME_MAX_LEN = 64
APP_SHORT_NAME_MAX_LEN = 16
BRANDING_URL_SCHEMES = ('http', 'https')
APP_TAGLINE_MAX_LEN = 80
_HEX_COLOR_RE = re.compile(r'^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$')

# HTML/Markdown sanitization configuration
ALLOWED_TAGS = [
    'a', 'b', 'i', 'em', 'strong',
    'p', 'ul', 'ol', 'li',
    'blockquote', 'code', 'pre'
]

ALLOWED_ATTRIBUTES = {
    'a': ['href', 'title']
}


def sanitize_markdown_input(user_input: str) -> str:
    """
    Sanitize markdown/HTML input to prevent XSS attacks.

    Args:
        user_input: String containing potentially unsafe HTML/markdown content

    Returns:
        Sanitized string with only allowed HTML tags and attributes

    Example:
        >>> sanitize_markdown_input("<script>alert('xss')</script><b>safe</b>")
        "<b>safe</b>"
    """
    return bleach.clean(
        user_input,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        strip=True
    )


def sanitize_app_display_name(
    value: Optional[str], *, max_len: int = APP_DISPLAY_NAME_MAX_LEN, field: str = 'display name',
) -> Optional[str]:
    """Validate and clean a branding display/short name.

    Strips surrounding whitespace and control characters (incl. newlines/tabs),
    enforces a max length, and returns ``None`` for empty/whitespace-only input
    so callers can treat "cleared" as "fall back to default product name".

    Raises ``ValueError`` (caught by the settings route -> 400) when the
    cleaned value exceeds ``max_len``.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    cleaned = ''.join(ch for ch in value if ch.isprintable()).strip()
    if not cleaned:
        return None
    if len(cleaned) > max_len:
        raise ValueError(f"{field} must be at most {max_len} characters")
    return cleaned


def validate_branding_url(value: Optional[str], *, field: str = 'URL') -> Optional[str]:
    """Validate a branding image URL (custom logo, favicon).

    Returns ``None`` for empty input. Accepts a root-relative path to an asset
    served by the app itself (``/branding/acme/logo.svg``), or an http/https URL
    with a host (rejecting ``javascript:``, ``data:``, ``file:``, etc.). Raises
    ``ValueError`` on invalid input; the settings route maps this to a 400.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    cleaned = value.strip()
    if not cleaned:
        return None
    if _is_app_asset_path(cleaned):
        return cleaned
    try:
        parsed = urlparse(cleaned)
    except Exception as exc:
        raise ValueError(f"{field} is not a valid URL") from exc
    if parsed.scheme not in BRANDING_URL_SCHEMES:
        raise ValueError(
            f"{field} must use http or https (got '{parsed.scheme or 'no scheme'}')"
        )
    if not parsed.netloc:
        raise ValueError(f"{field} is missing a host")
    return cleaned


def _is_app_asset_path(value: str) -> bool:
    """True for a same-origin, root-relative path such as ``/branding/x.svg``.

    Protocol-relative URLs (``//host``), backslashes, whitespace and control
    characters are rejected so the value can't point at another origin, and
    ``..`` segments (also percent-encoded) so it can't climb out of its folder.
    """
    if not value.startswith('/') or value.startswith('//'):
        return False
    path = value.split('?', 1)[0].split('#', 1)[0]
    if any(seg.lower() in ('..', '%2e%2e', '.%2e', '%2e.') for seg in path.split('/')):
        return False
    return all(ch.isprintable() and not ch.isspace() and ch != '\\' for ch in value)


def validate_hex_color(value: Optional[str], *, field: str = 'color') -> Optional[str]:
    """Validate a theme color given as ``#rgb`` or ``#rrggbb``.

    Returns the color as lowercase ``#rrggbb``, or ``None`` for empty input.
    Raises ``ValueError`` for anything else (the value ends up in injected CSS).
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    cleaned = value.strip()
    if not cleaned:
        return None
    if not _HEX_COLOR_RE.match(cleaned):
        raise ValueError(f"{field} must be a hex color like #2563eb")
    if len(cleaned) == 4:
        cleaned = '#' + ''.join(ch * 2 for ch in cleaned[1:])
    return cleaned.lower()


def coerce_hex_color(value: Optional[str]) -> Optional[str]:
    """Like ``validate_hex_color`` but returns ``None`` for invalid input.

    Used where a value may come straight from the environment (never validated
    on the way in), so a typo falls back to the default theme instead of failing.
    """
    try:
        return validate_hex_color(value)
    except ValueError:
        return None
