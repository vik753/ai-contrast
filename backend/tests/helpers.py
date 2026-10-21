"""Helpers shared by the backend tests (no fixtures here)."""

from __future__ import annotations

import asyncio
import logging
import secrets
from typing import Any

import pytest
from fastapi import FastAPI

SETTINGS_ENV_VARS = (
    "ENVIRONMENT",
    "ALLOWED_ORIGINS",
    "ALLOW_PRIVATE_PROVIDER_URLS",
    # Stage 2 (S2-T1) upload limits.
    "MAX_FILE_BYTES",
    "MAX_JSON_BODY_BYTES",
    "MAX_CONCURRENT_EXTRACTIONS",
    "MAX_ZIP_ENTRIES",
    "MAX_ZIP_UNCOMPRESSED_BYTES",
    "MAX_ZIP_RATIO",
    "EXTRACT_BODY_TIMEOUT_SECONDS",
    "EXTRACT_MIN_RATE_BYTES_PER_SECOND",
    "EXTRACT_RATE_GRACE_SECONDS",
    # Stage 3 (S3-T1) parsing sandbox and text caps.
    "EXTRACT_WORKER_MEMORY_MB",
    "EXTRACT_WORKER_CPU_SECONDS",
    "EXTRACT_WORKER_WALL_SECONDS",
    "EXTRACT_MAX_RESULT_BYTES",
    "EXTRACT_MAX_TEXT_CHARS",
    "EXTRACT_MAX_BLOCKS",
    # S3-T1 test-only worker hook: never set in the server environment.
    "AI_CONTRAST_WORKER_TEST_HOOK",
)

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


# ---------------------------------------------------------------------------
# Raw ASGI driving (no test client between the app and the "server").
# ---------------------------------------------------------------------------

Message = dict[str, Any]


def http_scope(
    method: str = "GET",
    path: str = "/",
    *,
    headers: list[tuple[bytes, bytes]] | None = None,
    query_string: bytes = b"",
) -> dict[str, Any]:
    """A minimal ASGI 3 HTTP scope, as uvicorn would build it."""
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8", "surrogateescape"),
        "query_string": query_string,
        "root_path": "",
        "headers": headers or [(b"host", b"testserver")],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }


async def call_asgi(app: Any, scope: dict[str, Any], body: bytes = b"") -> list[Message]:
    """Run one request through ``app`` and return every message it sent.

    Any exception raised by the app propagates to the caller, exactly as it
    would reach uvicorn.
    """
    sent: list[Message] = []
    request_messages = [{"type": "http.request", "body": body, "more_body": False}]

    async def receive() -> Message:
        if request_messages:
            return request_messages.pop(0)
        await asyncio.Event().wait()  # never returns: client stays connected
        raise AssertionError("unreachable")

    async def send(message: Message) -> None:
        sent.append(message)

    await app(scope, receive, send)
    return sent


def run_asgi(app: Any, scope: dict[str, Any], body: bytes = b"") -> list[Message]:
    return asyncio.run(call_asgi(app, scope, body))


def response_status(messages: list[Message]) -> int | None:
    for message in messages:
        if message["type"] == "http.response.start":
            return int(message["status"])
    return None


def response_body(messages: list[Message]) -> bytes:
    return b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")


def access_lines(caplog: pytest.LogCaptureFixture, method: str, path: str) -> list[str]:
    """ai_contrast log messages that look like the access line of one request:
    ``<method> <path> <status> ...``."""
    prefix = f"{method} {path} "
    return [
        r.getMessage() for r in ai_contrast_records(caplog) if r.getMessage().startswith(prefix)
    ]
