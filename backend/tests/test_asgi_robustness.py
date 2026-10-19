"""S1-T1b AC2, AC8, AC9: behavior seen by the ASGI server (uvicorn).

These tests call the app as a raw ASGI callable, so that any exception that
escapes the app is visible (uvicorn would log it with its message).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from tests.helpers import (
    access_lines,
    ai_contrast_records,
    all_log_text,
    call_asgi,
    http_scope,
    new_canary,
    response_body,
    response_status,
    run_asgi,
)

GROUP_PATH = "/api/test/group"
STREAM_PATH = "/api/test/stream"
SLOW_PATH = "/api/test/slow"
FIRST_CHUNK = b"first-chunk"


def _status_token(line: str) -> str:
    return line.split()[2]


def _sent_text(messages: list[dict[str, Any]]) -> str:
    return repr(messages)


# --------------------------------------------------------------------------
# AC2: exception groups are handled like any other Exception.
# --------------------------------------------------------------------------


def _group_app(make_app: Callable[..., FastAPI], group: BaseException) -> FastAPI:
    app = make_app()

    async def _raise_group() -> None:
        raise group

    app.add_api_route(GROUP_PATH, _raise_group, methods=["GET"])
    return app


def _flat_group(canary: str) -> BaseExceptionGroup[Exception]:
    return BaseExceptionGroup("g", [RuntimeError(canary)])


def _nested_group(canary: str) -> BaseExceptionGroup[Exception]:
    return BaseExceptionGroup(
        "outer", [ExceptionGroup("inner", [ValueError(canary)]), KeyError(canary)]
    )


@pytest.mark.parametrize("build_group", [_flat_group, _nested_group], ids=["flat", "nested"])
def test_exception_group_raw_asgi_does_not_propagate(
    make_app: Callable[..., FastAPI],
    build_group: Callable[[str], BaseException],
) -> None:
    app = _group_app(make_app, build_group(new_canary()))

    run_asgi(app, http_scope("GET", GROUP_PATH))  # must not raise


@pytest.mark.parametrize("build_group", [_flat_group, _nested_group], ids=["flat", "nested"])
def test_exception_group_raw_asgi_returns_500_generic_body(
    make_app: Callable[..., FastAPI],
    build_group: Callable[[str], BaseException],
) -> None:
    app = _group_app(make_app, build_group(new_canary()))

    messages = run_asgi(app, http_scope("GET", GROUP_PATH))

    assert response_status(messages) == 500
    assert json.loads(response_body(messages)) == {"error": "internal_error"}


@pytest.mark.parametrize("build_group", [_flat_group, _nested_group], ids=["flat", "nested"])
def test_exception_group_canary_absent_from_logs_and_response(
    make_app: Callable[..., FastAPI],
    log_capture: pytest.LogCaptureFixture,
    build_group: Callable[[str], BaseException],
) -> None:
    canary = new_canary()
    app = _group_app(make_app, build_group(canary))
    log_capture.clear()

    messages = run_asgi(
        app,
        http_scope("GET", GROUP_PATH, headers=[(b"x-provider-key", canary.encode())]),
    )

    assert canary not in all_log_text(log_capture)
    assert canary not in _sent_text(messages)


# --------------------------------------------------------------------------
# AC8: access log accuracy when the app fails mid-stream or is cancelled.
# --------------------------------------------------------------------------


def _stream_app(make_app: Callable[..., FastAPI], canary: str) -> FastAPI:
    app = make_app()

    async def _chunks() -> AsyncIterator[bytes]:
        yield FIRST_CHUNK
        message = f"stream failed, key {canary}"
        raise RuntimeError(message)

    async def _stream() -> StreamingResponse:
        return StreamingResponse(_chunks(), media_type="application/octet-stream")

    app.add_api_route(STREAM_PATH, _stream, methods=["GET"])
    return app


def test_stream_failure_after_first_chunk_does_not_propagate(
    make_app: Callable[..., FastAPI],
) -> None:
    app = _stream_app(make_app, new_canary())

    run_asgi(app, http_scope("GET", STREAM_PATH))  # must not raise


def test_stream_failure_after_first_chunk_keeps_sent_status_and_chunk(
    make_app: Callable[..., FastAPI],
) -> None:
    app = _stream_app(make_app, new_canary())

    messages = run_asgi(app, http_scope("GET", STREAM_PATH))

    starts = [m for m in messages if m["type"] == "http.response.start"]
    assert len(starts) == 1  # no second (500) response start after streaming began
    assert starts[0]["status"] == 200
    assert response_body(messages).startswith(FIRST_CHUNK)


def test_stream_failure_canary_absent_from_logs_and_response(
    make_app: Callable[..., FastAPI], log_capture: pytest.LogCaptureFixture
) -> None:
    canary = new_canary()
    app = _stream_app(make_app, canary)
    log_capture.clear()

    messages = run_asgi(app, http_scope("GET", STREAM_PATH))

    assert canary not in all_log_text(log_capture)
    assert canary not in _sent_text(messages)


def test_stream_failure_logs_exactly_one_unhandled_exception_line(
    make_app: Callable[..., FastAPI], log_capture: pytest.LogCaptureFixture
) -> None:
    app = _stream_app(make_app, new_canary())
    log_capture.clear()

    run_asgi(app, http_scope("GET", STREAM_PATH))

    lines = [
        r.getMessage()
        for r in ai_contrast_records(log_capture)
        if "unhandled_exception" in r.getMessage()
    ]
    assert len(lines) == 1, lines


def test_stream_failure_access_line_shows_sent_status_and_aborted(
    make_app: Callable[..., FastAPI], log_capture: pytest.LogCaptureFixture
) -> None:
    app = _stream_app(make_app, new_canary())
    log_capture.clear()

    run_asgi(app, http_scope("GET", STREAM_PATH))

    lines = access_lines(log_capture, "GET", STREAM_PATH)
    assert len(lines) == 1, lines
    assert _status_token(lines[0]) == "200"
    assert " aborted=1" in lines[0]


def test_normal_request_access_line_has_no_aborted_flag(
    make_app: Callable[..., FastAPI], log_capture: pytest.LogCaptureFixture
) -> None:
    app = make_app()
    log_capture.clear()

    run_asgi(app, http_scope("GET", "/api/health"))

    lines = access_lines(log_capture, "GET", "/api/health")
    assert len(lines) == 1, lines
    assert _status_token(lines[0]) == "200"
    assert "aborted" not in lines[0]


def test_cancelled_request_before_response_access_line_status_is_dash(
    make_app: Callable[..., FastAPI], log_capture: pytest.LogCaptureFixture
) -> None:
    app = make_app()
    entered: dict[str, asyncio.Event] = {}

    async def _slow() -> None:
        entered["event"].set()
        await asyncio.Event().wait()  # waits until cancelled

    app.add_api_route(SLOW_PATH, _slow, methods=["GET"])

    async def scenario() -> list[dict[str, Any]]:
        entered["event"] = asyncio.Event()
        task = asyncio.ensure_future(call_asgi(app, http_scope("GET", SLOW_PATH)))
        await asyncio.wait_for(entered["event"].wait(), timeout=5)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            return await task
        return []

    log_capture.clear()
    asyncio.run(scenario())

    lines = access_lines(log_capture, "GET", SLOW_PATH)
    assert len(lines) == 1, lines
    assert _status_token(lines[0]) == "-"


# --------------------------------------------------------------------------
# AC9: control characters in logged method and path become U+FFFD.
# --------------------------------------------------------------------------

CONTROL_CHARS = ["\x00", "\x07", "\n", "\r", "\x1b", "\x7f"]


@pytest.mark.parametrize("char", CONTROL_CHARS, ids=[f"0x{ord(c):02x}" for c in CONTROL_CHARS])
def test_access_log_control_char_in_path_replaced_with_fffd(
    make_app: Callable[..., FastAPI], log_capture: pytest.LogCaptureFixture, char: str
) -> None:
    app = make_app()
    log_capture.clear()

    run_asgi(app, http_scope("GET", f"/api/x{char}y"))

    lines = access_lines(log_capture, "GET", "/api/x�y")
    assert len(lines) == 1, [r.getMessage() for r in ai_contrast_records(log_capture)]


@pytest.mark.parametrize("char", CONTROL_CHARS, ids=[f"0x{ord(c):02x}" for c in CONTROL_CHARS])
def test_access_log_control_char_in_path_not_logged_raw_or_as_question_mark(
    make_app: Callable[..., FastAPI], log_capture: pytest.LogCaptureFixture, char: str
) -> None:
    app = make_app()
    log_capture.clear()

    run_asgi(app, http_scope("GET", f"/api/x{char}y"))

    text = "\n".join(r.getMessage() for r in ai_contrast_records(log_capture))
    assert char not in text
    assert "/api/x?y" not in text


def test_access_log_control_char_in_method_replaced_with_fffd(
    make_app: Callable[..., FastAPI], log_capture: pytest.LogCaptureFixture
) -> None:
    app = make_app()
    log_capture.clear()

    run_asgi(app, http_scope("GE\x1bT", "/api/health"))

    messages = [r.getMessage() for r in ai_contrast_records(log_capture)]
    assert any(m.startswith("GE�T /api/health ") for m in messages), messages
    assert not any("\x1b" in m for m in messages)


def test_unhandled_exception_line_control_char_in_path_replaced_with_fffd(
    make_app: Callable[..., FastAPI], log_capture: pytest.LogCaptureFixture
) -> None:
    app = make_app()
    path = "/api/test/bo\nom"

    async def _raise() -> None:
        raise RuntimeError("boom")

    app.add_api_route(path, _raise, methods=["GET"])
    log_capture.clear()

    run_asgi(app, http_scope("GET", path))

    lines = [
        r.getMessage()
        for r in ai_contrast_records(log_capture)
        if "unhandled_exception" in r.getMessage()
    ]
    assert len(lines) == 1, lines
    assert "/api/test/bo�om" in lines[0]
    assert "\n" not in lines[0]
