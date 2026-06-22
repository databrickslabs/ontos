import logging
import sys
from typing import Any, Optional


def setup_logging(
    level: int = logging.INFO,
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    log_file: Optional[str] = None
) -> None:
    """Configure logging for the application.
    
    Args:
        level: Logging level (default: INFO)
        format: Log message format
        log_file: Optional file path to write logs to
    """
    handlers = [logging.StreamHandler(sys.stdout)]

    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=level,
        format=format,
        handlers=handlers
    )

    # Force uvicorn loggers to use the same format so all lines include timestamps
    formatter = logging.Formatter(format)
    for uvicorn_logger_name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uv_logger = logging.getLogger(uvicorn_logger_name)
        uv_logger.handlers.clear()
        uv_handler = logging.StreamHandler(sys.stdout)
        uv_handler.setFormatter(formatter)
        uv_logger.addHandler(uv_handler)
        if log_file:
            uv_file_handler = logging.FileHandler(log_file)
            uv_file_handler.setFormatter(formatter)
            uv_logger.addHandler(uv_file_handler)
        uv_logger.propagate = False

def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the specified name.

    Args:
        name: Logger name, typically __name__ from the calling module

    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)


# Substrings (case-insensitive) that mark a config key as secret-bearing.
# Curated to be specific enough to avoid clobbering benign keys like
# WORKSPACE_DEPLOYMENT_PATH (`path` is intentionally NOT in this set).
_SENSITIVE_KEY_SUBSTRINGS = (
    "secret",
    "token",
    "password",
    "passwd",
    "credential",
    "api_key",
    "apikey",
    "private_key",
    "client_secret",
    "bearer",
    "github_pat",
    "mcp_token",
)

_REDACTED = "***REDACTED***"


def _is_sensitive_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    k = key.lower()
    return any(s in k for s in _SENSITIVE_KEY_SUBSTRINGS)


def redact_sensitive_keys(payload: Any) -> Any:
    """Return a copy of ``payload`` with values for secret-shaped keys masked.

    Safe to log. Recurses into nested dicts and lists. Non-container values
    pass through unchanged. The original payload is never mutated, so callers
    can still hand the real values to downstream handlers.

    The match is a case-insensitive substring check on the key name, so
    ``github_pat``, ``MCP_GITHUB_TOKEN``, and ``my_api_key`` all redact.
    """
    if isinstance(payload, dict):
        return {
            k: (_REDACTED if _is_sensitive_key(k) else redact_sensitive_keys(v))
            for k, v in payload.items()
        }
    if isinstance(payload, list):
        return [redact_sensitive_keys(item) for item in payload]
    return payload
