"""S6-T3 AC4: no client address in logs (T1, rule 3)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

import pytest
from fastapi import FastAPI

from tests.asgi_stream import AsgiRun, chunks, drive
from tests.limits.test_client_slots import EXTRACT, SEGMENT, Held, scope_for

V4 = "203.0.113.77"
V6 = "2001:db8:abcd:1234::77"
V6_PREFIX_PARTS = ("abcd:1234", "ABCD:1234", "2001:db8:abcd", "2001:0db8:abcd:1234")


def all_log_text(caplog: pytest.LogCaptureFixture) -> str:
    parts: list[str] = [caplog.text]
    for record in caplog.records:
        parts.append(record.getMessage())
        parts.append(repr(record.args))
        parts.append(repr(record.__dict__))
    return "\n".join(parts)


def response_text(run: AsgiRun) -> str:
    return repr(run.sent)


async def traffic(app: FastAPI, ip: str, extra: list[tuple[str, str]] | None) -> list[AsgiRun]:
    runs: list[AsgiRun] = []
    runs.append(await drive(app, scope_for(EXTRACT, ip, extra=extra), chunks(b"x" * 16)))
    held = Held(app, EXTRACT, ip, extra=extra)
    await held.reading_body()
    runs.append(await drive(app, scope_for(EXTRACT, ip, extra=extra), chunks(b"x" * 16)))  # busy
    runs.append(await held.finish())
    bad = b"not json"
    runs.append(await drive(app, scope_for(SEGMENT, ip, length=len(bad), extra=extra), chunks(bad)))
    return runs


def test_ipv4_peer_in_development_is_not_logged_or_returned(
    make_app: Callable[..., FastAPI], log_capture: pytest.LogCaptureFixture
) -> None:
    app = make_app(environment="development")

    runs = asyncio.run(traffic(app, V4, None))

    assert any(run.status == 503 for run in runs)  # the busy path was exercised
    assert V4 not in all_log_text(log_capture)
    assert all(V4 not in response_text(run) for run in runs)


def test_forwarded_ipv4_in_production_is_not_logged_or_returned(
    make_app: Callable[..., FastAPI], log_capture: pytest.LogCaptureFixture
) -> None:
    app = make_app(environment="production")
    extra = [("x-forwarded-for", f"6.6.6.6, {V4}")]

    runs = asyncio.run(traffic(app, "10.0.0.1", extra))

    assert any(run.status == 503 for run in runs)
    text = all_log_text(log_capture)
    assert V4 not in text
    assert "6.6.6.6" not in text
    assert all(V4 not in response_text(run) for run in runs)


def test_forwarded_ipv6_and_its_prefix_are_not_logged_or_returned(
    make_app: Callable[..., FastAPI], log_capture: pytest.LogCaptureFixture
) -> None:
    app = make_app(environment="production")
    extra = [("x-forwarded-for", V6)]

    runs = asyncio.run(traffic(app, "10.0.0.1", extra))

    assert any(run.status == 503 for run in runs)
    text = all_log_text(log_capture)
    assert V6 not in text
    for part in V6_PREFIX_PARTS:
        assert part not in text
    assert all(V6 not in response_text(run) for run in runs)


def test_ipv6_peer_in_development_is_not_logged(
    make_app: Callable[..., FastAPI], log_capture: pytest.LogCaptureFixture
) -> None:
    app = make_app(environment="development")

    asyncio.run(traffic(app, V6, None))

    text = all_log_text(log_capture)
    assert V6 not in text
    assert "abcd:1234" not in text


def test_invalid_forwarded_value_is_not_logged(
    make_app: Callable[..., FastAPI], log_capture: pytest.LogCaptureFixture
) -> None:
    app = make_app(environment="production")
    garbage = "CANARY-garbage-203.0.113.77-value"

    asyncio.run(traffic(app, "10.0.0.1", [("x-forwarded-for", garbage)]))

    text = all_log_text(log_capture)
    assert "CANARY-garbage" not in text
    assert V4 not in text


def test_limiter_logs_nothing_at_info_with_an_address(
    make_app: Callable[..., FastAPI], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.WARNING, logger="httpx")
    app = make_app(environment="development")

    asyncio.run(traffic(app, V4, None))

    assert V4 not in caplog.text
