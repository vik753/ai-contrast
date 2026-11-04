"""Cloudflare Turnstile server-side verification (ADR 0016 point 7, threat model T10).

One POST to the constant siteverify URL through the guarded AI client wrapper (no redirect,
capped body, header allowlist, SSRF guard). The secret and the token go only in the JSON
body; no ``remoteip`` is sent, so the client address never leaves the server. Errors carry
fixed texts: the secret, the token and the URL never appear in them.

This module only reports what Turnstile said. The caller compares ``hostname``, ``action``
and the age of ``challenge_ts`` and keeps the replay table.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from pydantic import SecretStr

from app.net.ai_client import AITransport, ai_client

SITEVERIFY_URL: Final = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
MAX_RESPONSE_BYTES: Final = 64 * 1024
_CONNECT_TIMEOUT_SECONDS: Final = 5.0
_READ_TIMEOUT_SECONDS: Final = 10.0
_HTTP_OK: Final = 200


class TurnstileError(Exception):
    """The verification call failed or its answer is not valid. Holds a fixed text."""


@dataclass(frozen=True, slots=True)
class TurnstileVerdict:
    success: bool
    hostname: str | None
    action: str | None
    challenge_ts: float | None  # UTC epoch seconds


def _optional_text(data: dict[str, object], name: str) -> str | None:
    value = data.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TurnstileError("unexpected answer")  # noqa: TRY003
    return value


def _timestamp(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise TurnstileError("unexpected answer") from None  # noqa: TRY003
    if moment.tzinfo is None:
        raise TurnstileError("unexpected answer")  # noqa: TRY003
    return moment.astimezone(UTC).timestamp()


def _verdict(content: bytes) -> TurnstileVerdict:
    try:
        data = json.loads(content)
    except (ValueError, RecursionError):
        raise TurnstileError("unexpected answer") from None  # noqa: TRY003
    if not isinstance(data, dict) or not isinstance(data.get("success"), bool):
        raise TurnstileError("unexpected answer")  # noqa: TRY003
    return TurnstileVerdict(
        success=data["success"],
        hostname=_optional_text(data, "hostname"),
        action=_optional_text(data, "action"),
        challenge_ts=_timestamp(_optional_text(data, "challenge_ts")),
    )


async def verify(
    token: str, secret: SecretStr, *, transport: AITransport | None = None
) -> TurnstileVerdict:
    """Ask Turnstile about ``token``. ``transport`` is a test-only hook."""
    try:
        async with ai_client(
            connect_timeout=_CONNECT_TIMEOUT_SECONDS,
            read_timeout=_READ_TIMEOUT_SECONDS,
            transport=transport,
            max_response_bytes=MAX_RESPONSE_BYTES,
        ) as client:
            response = await client.post(
                SITEVERIFY_URL,
                json={"secret": secret.get_secret_value(), "response": token},
            )
    except Exception:  # noqa: BLE001 - every transport error has a text that may hold the secret
        raise TurnstileError("request failed") from None  # noqa: TRY003
    if response.status_code != _HTTP_OK:
        raise TurnstileError("unexpected status")  # noqa: TRY003
    return _verdict(response.content)
