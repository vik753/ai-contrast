"""A Server-Sent Events response with the guards of ADR 0019 point 1.

Headers: ``text/event-stream``, ``Cache-Control: no-store``, ``X-Accel-Buffering: no``, no
``Content-Encoding``. Events are ``event: <name>`` and one ``data:`` line of JSON, at most
64 KiB per event. An idle stream sends a comment every ``heartbeat`` seconds. Each write has a
timeout: a client that does not read is dropped. A client disconnect or a drop cancels the
producer, which cancels its AI calls. ``on_close`` always runs once (slots, settlement). The
producer is the only writer; this module never logs.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, Final

from starlette.responses import Response
from starlette.types import Receive, Scope, Send

__all__ = ["MAX_EVENT_BYTES", "EventTooLargeError", "SseResponse", "sse_event"]

MAX_EVENT_BYTES: Final = 64 * 1024
HEARTBEAT: Final = b": keep-alive\n\n"
Produce = Callable[[Callable[[str, dict[str, Any]], None]], Awaitable[None]]


class EventTooLargeError(Exception):
    """An event is over the cap. Holds no data."""


def sse_event(name: str, data: dict[str, Any]) -> bytes:
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    block = f"event: {name}\ndata: {body}\n\n".encode()
    if len(block) > MAX_EVENT_BYTES:
        raise EventTooLargeError
    return block


class SseResponse(Response):
    def __init__(
        self,
        produce: Produce,
        *,
        heartbeat: float,
        send_timeout: float,
        on_close: Callable[[], None],
    ) -> None:
        super().__init__(
            content=None,
            status_code=200,
            headers={
                "Content-Type": "text/event-stream; charset=utf-8",
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            },
        )
        del self.headers["content-length"]
        self._produce = produce
        self._heartbeat = heartbeat
        self._send_timeout = send_timeout
        self._on_close = on_close

    async def _write(self, send: Send, message: dict[str, Any]) -> None:
        async with asyncio.timeout(self._send_timeout):
            await send(message)

    async def _pump(self, queue: asyncio.Queue[bytes | None], send: Send) -> None:
        while True:
            try:
                chunk = await asyncio.wait_for(queue.get(), self._heartbeat)
            except TimeoutError:
                chunk = HEARTBEAT
            if chunk is None:
                return
            await self._write(
                send, {"type": "http.response.body", "body": chunk, "more_body": True}
            )

    async def _produce_into(self, queue: asyncio.Queue[bytes | None]) -> None:
        def emit(name: str, data: dict[str, Any]) -> None:
            queue.put_nowait(sse_event(name, data))

        try:
            await self._produce(emit)
        except Exception:  # noqa: BLE001 - the stream ends with a code, never with the error text
            queue.put_nowait(sse_event("error", {"error": "internal_error"}))
        finally:
            queue.put_nowait(None)

    @staticmethod
    async def _disconnected(receive: Receive) -> None:
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        producer = asyncio.create_task(self._produce_into(queue))
        watcher = asyncio.create_task(self._disconnected(receive))
        pump: asyncio.Task[None] | None = None
        try:
            await self._write(
                send,
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": self.raw_headers,
                },
            )
            pump = asyncio.create_task(self._pump(queue, send))
            await asyncio.wait({pump, watcher}, return_when=asyncio.FIRST_COMPLETED)
            if pump.done() and pump.exception() is None:
                await self._write(send, {"type": "http.response.body", "body": b""})
        except TimeoutError:
            pass  # a client that does not read is dropped
        finally:
            tasks = [t for t in (pump, watcher, producer) if t is not None]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._on_close()
