# ruff: noqa: TRY003
"""S9-T3 review: unit tests of ``app.api.sse.SseResponse`` with a fake ASGI send and receive."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

import pytest

from app.api.sse import MAX_EVENT_BYTES, EventTooLargeError, SseResponse, sse_event

Emit = Callable[[str, dict[str, Any]], None]
Message = dict[str, Any]


class Run:
    def __init__(self) -> None:
        self.sent: list[Message] = []
        self.closed = 0
        self.error: BaseException | None = None

    @property
    def body(self) -> bytes:
        return b"".join(m.get("body", b"") for m in self.sent if m["type"] == "http.response.body")


async def _never() -> Message:
    await asyncio.Event().wait()
    return {"type": "http.disconnect"}


async def drive(
    produce: Callable[[Emit], Awaitable[None]],
    *,
    heartbeat: float = 30.0,
    send_timeout: float = 5.0,
    receive: Callable[[], Awaitable[Message]] = _never,
    send: Callable[[Message], Awaitable[None]] | None = None,
) -> Run:
    run = Run()

    async def default_send(message: Message) -> None:
        run.sent.append(message)

    def on_close() -> None:
        run.closed += 1

    response = SseResponse(
        produce, heartbeat=heartbeat, send_timeout=send_timeout, on_close=on_close
    )

    async def wrapped(message: Message) -> None:
        run.sent.append(message)
        if send is not None:
            await send(message)

    scope = {"type": "http", "method": "POST", "path": "/x", "headers": []}
    await asyncio.wait_for(response(scope, receive, wrapped if send else default_send), 10)
    return run


def _events(run: Run) -> list[str]:
    return [b.split("\n")[0] for b in run.body.decode().split("\n\n") if b.startswith("event:")]


def test_headers_forbid_caching_buffering_and_compression() -> None:
    async def produce(emit: Emit) -> None:
        emit("done", {})

    run = asyncio.run(drive(produce))
    start = run.sent[0]
    headers = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    assert start["status"] == 200
    assert headers["content-type"].startswith("text/event-stream")
    assert headers["cache-control"] == "no-store"
    assert headers["x-accel-buffering"] == "no"
    assert "content-encoding" not in headers
    assert "content-length" not in headers
    assert run.closed == 1


def test_events_are_written_in_order_and_the_body_is_closed() -> None:
    async def produce(emit: Emit) -> None:
        emit("start", {"a": 1})
        emit("done", {"b": 2})

    run = asyncio.run(drive(produce))
    assert _events(run) == ["event: start", "event: done"]
    assert run.sent[-1] == {"type": "http.response.body", "body": b""}


def test_an_idle_stream_sends_heartbeat_comments() -> None:
    async def produce(emit: Emit) -> None:
        await asyncio.sleep(0.4)
        emit("done", {})

    run = asyncio.run(drive(produce, heartbeat=0.05))
    chunks = [m["body"] for m in run.sent if m["type"] == "http.response.body" and m["body"]]
    assert sum(c.startswith(b":") for c in chunks) >= 2
    assert _events(run) == ["event: done"]


def test_a_client_that_does_not_read_is_dropped_after_the_send_timeout() -> None:
    state = {"cancelled": False}

    async def produce(emit: Emit) -> None:
        emit("start", {})
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    async def stuck(message: Message) -> None:
        if message["type"] == "http.response.body":
            await asyncio.sleep(60)

    run = asyncio.run(drive(produce, send_timeout=0.2, send=stuck))
    assert state["cancelled"] is True
    assert run.closed == 1
    assert b"event: done" not in run.body


def test_a_client_disconnect_cancels_the_producer() -> None:
    state = {"started": asyncio.Event, "cancelled": False}

    async def produce(emit: Emit) -> None:
        emit("start", {})
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    async def receive() -> Message:
        await asyncio.sleep(0.1)
        return {"type": "http.disconnect"}

    run = asyncio.run(drive(produce, receive=receive))
    assert state["cancelled"] is True
    assert run.closed == 1


def test_a_producer_exception_ends_the_stream_with_an_error_code_and_no_text() -> None:
    async def produce(emit: Emit) -> None:
        emit("start", {})
        raise RuntimeError("Zcanary secret clause text")

    run = asyncio.run(drive(produce))
    assert _events(run) == ["event: start", "event: error"]
    assert b'"error":"internal_error"' in run.body
    assert b"Zcanary" not in run.body
    assert run.closed == 1


def test_an_event_over_64_kib_raises_and_the_producer_can_go_on() -> None:
    assert MAX_EVENT_BYTES == 64 * 1024
    with pytest.raises(EventTooLargeError):
        sse_event("topic", {"x": "a" * MAX_EVENT_BYTES})
    assert len(sse_event("topic", {"x": "a" * 60000})) <= MAX_EVENT_BYTES

    async def produce(emit: Emit) -> None:
        try:
            emit("topic", {"x": "a" * MAX_EVENT_BYTES})
        except EventTooLargeError:
            emit("topic", {"x": "small"})
        emit("done", {})

    run = asyncio.run(drive(produce))
    assert _events(run) == ["event: topic", "event: done"]
    assert b"small" in run.body


def test_an_unhandled_oversized_event_ends_with_internal_error_not_a_crash() -> None:
    async def produce(emit: Emit) -> None:
        emit("topic", {"x": "a" * MAX_EVENT_BYTES})

    run = asyncio.run(drive(produce))
    assert _events(run) == ["event: error"]
    assert run.closed == 1


def test_events_use_utf8_without_escaping_so_cyrillic_counts_two_bytes() -> None:
    block = sse_event("other", {"t": "Ґ" * 100})
    assert "Ґ".encode() * 100 in block
    assert block.count(b"\ndata:") == 1


def test_a_failing_final_write_when_the_client_is_gone_does_not_raise() -> None:
    async def produce(emit: Emit) -> None:
        emit("done", {})

    async def gone(message: Message) -> None:
        if message["type"] == "http.response.body" and not message["body"]:
            raise OSError("client gone")

    run = asyncio.run(drive(produce, send=gone))
    assert b"event: done" in run.body
    assert run.closed == 1


def test_a_failing_event_write_when_the_client_is_gone_does_not_raise_and_cancels() -> None:
    state = {"cancelled": False}

    async def produce(emit: Emit) -> None:
        emit("start", {})
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    async def gone(message: Message) -> None:
        if message["type"] == "http.response.body":
            raise OSError("client gone")

    run = asyncio.run(drive(produce, send=gone))
    assert state["cancelled"] is True
    assert run.closed == 1
