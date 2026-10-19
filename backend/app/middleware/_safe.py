"""Helpers that make request data safe to put in a log line."""

from __future__ import annotations

from starlette.types import Scope

MAX_LOGGED_PATH_LENGTH = 256
MAX_LOGGED_METHOD_LENGTH = 16


def _printable(value: str, limit: int) -> str:
    """Replace control and other non-printable characters (log injection) and truncate."""
    cleaned = "".join(char if char.isprintable() else "?" for char in value[:limit])
    if len(value) > limit:
        cleaned += "..."
    return cleaned


def log_path(scope: Scope) -> str:
    """The request path for logs. Never includes the query string."""
    path = scope.get("path", "")
    return _printable(path if isinstance(path, str) else "", MAX_LOGGED_PATH_LENGTH)


def log_method(scope: Scope) -> str:
    method = scope.get("method", "")
    return _printable(method if isinstance(method, str) else "", MAX_LOGGED_METHOD_LENGTH)
