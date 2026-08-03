"""Structured logging setup with secret redaction helpers."""

from __future__ import annotations

import logging
import re
from typing import Any

_SECRET_KEYS = frozenset(
    {
        "password",
        "mqtt_password",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "secret",
        "product_auth_secret",
        "mimo_api_key",
    }
)

_BEARER_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-+/=]+")
_KEY_VALUE_RE = re.compile(
    r"(?i)\b(password|token|api[_-]?key|authorization|secret)\b\s*[:=]\s*([^\s,;]+)"
)


def redact_secrets(value: Any) -> Any:
    """Recursively redact secret-looking values from structures and strings."""
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in _SECRET_KEYS:
                redacted[key] = "***"
            else:
                redacted[key] = redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        text = _BEARER_RE.sub(r"\1***", value)
        text = _KEY_VALUE_RE.sub(r"\1=***", text)
        return text
    return value


class RedactingFilter(logging.Filter):
    """Ensure formatted log messages do not leak obvious secrets."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_secrets(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = redact_secrets(record.args)
            elif isinstance(record.args, tuple):
                record.args = tuple(redact_secrets(arg) for arg in record.args)
        return True


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    handler.addFilter(RedactingFilter())
    root.addHandler(handler)
    root.setLevel(level.upper())
    # Also attach filter to root so child loggers inherit redaction on emit path
    root.addFilter(RedactingFilter())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
