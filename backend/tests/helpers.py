"""Helpers shared by the backend tests (no fixtures here)."""

from __future__ import annotations

import logging
import secrets

import pytest
from fastapi import FastAPI

SETTINGS_ENV_VARS = ("ENVIRONMENT", "ALLOWED_ORIGINS", "ALLOW_PRIVATE_PROVIDER_URLS")

ALLOWED_ORIGIN = "https://app.example"
OTHER_ORIGIN = "https://evil.example"

LOG_NAMESPACE = "ai_contrast"


class BoomError(RuntimeError):
    """Exception type with a distinctive class name raised by test routes."""


def add_raising_route(app: FastAPI, path: str, message: str) -> None:
    """Add a test-only GET route that raises ``BoomError(message)``."""

    async def _raise() -> None:
        raise BoomError(message)

    app.add_api_route(path, _raise, methods=["GET"])


def new_canary() -> str:
    """A unique fake provider key used to detect leaks."""
    return f"sk-CANARY-{secrets.token_hex(16)}"


def new_marker(prefix: str = "marker") -> str:
    """A unique string that must never show up where it is checked."""
    return f"{prefix}{secrets.token_hex(12)}"


def ai_contrast_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.name == LOG_NAMESPACE or r.name.startswith(LOG_NAMESPACE + ".")
    ]


def all_log_text(caplog: pytest.LogCaptureFixture) -> str:
    """Everything that a log handler could see: formatted text, messages,
    arguments, exception info and extra attributes of every record."""
    parts = [caplog.text]
    for record in caplog.records:
        parts.append(record.getMessage())
        parts.append(repr(record.__dict__))
        if record.exc_info and record.exc_info[1] is not None:
            parts.append(str(record.exc_info[1]))
        if record.exc_text:
            parts.append(record.exc_text)
    return "\n".join(parts)
