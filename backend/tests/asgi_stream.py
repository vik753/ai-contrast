"""Drive an ASGI app with a scripted request body (stage 2 upload tests).

The test client always sends an honest ``Content-Length``. These helpers send
what a hostile or broken client could send at the ASGI level: a body larger
than its ``Content-Length``, an endless stream, or a disconnect mid-body.
They also record the order of events, so a test can check that the app
answered *before* it read any part of the body.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

Message = dict[str, Any]

RUN_TIMEOUT_SECONDS = 20.0


@dataclass
class AsgiRun:
    sent: list[Message] = field(default_factory=list)
    # "receive:<type>" and "send:<type>" in the order they happened.
    events: list[str] = field(default_factory=list)
    body_bytes_delivered: int = 0
    body_messages_delivered: int = 0

    @property
    def status(self) -> int | None:
        for message in self.sent:
            if message["type"] == "http.response.start":
                return int(message["status"])
        return None

    @property
    def headers(self) -> dict[str, str]:
        for message in self.sent:
            if message["type"] == "http.response.start":
                return {
                    k.decode("latin-1").lower(): v.decode("latin-1")
                    for k, v in message.get("headers", [])
                }
        return {}

    @property
    def body(self) -> bytes:
        return b"".join(m.get("body", b"") for m in self.sent if m["type"] == "http.response.body")

    def body_read_before_response(self) -> bool:
        """True if any ``http.request`` message was taken before the response started."""
        for event in self.events:
            if event == "send:http.response.start":
                return False
            if event == "receive:http.request":
                return True
        return False


def chunks(*parts: bytes) -> Iterator[Message]:
    """A finite body: every part as one ``http.request`` message."""
    for index, part in enumerate(parts):
        yield {"type": "http.request", "body": part, "more_body": index < len(parts) - 1}


def endless(chunk: bytes, *, max_total: int) -> Iterator[Message]:
    """A body that keeps coming (``more_body`` always true) until ``max_total``
    bytes were delivered; then the client disconnects."""
    delivered = 0
    while delivered < max_total:
        delivered += len(chunk)
        yield {"type": "http.request", "body": chunk, "more_body": True}
    yield {"type": "http.disconnect"}


def then_disconnect(*parts: bytes) -> Iterator[Message]:
    """Some body parts (more to come), then a client disconnect."""
    for part in parts:
        yield {"type": "http.request", "body": part, "more_body": True}
    yield {"type": "http.disconnect"}


async def drive(app: Any, scope: dict[str, Any], messages: Iterator[Message]) -> AsgiRun:
    run = AsgiRun()

    async def receive() -> Message:
        message = next(messages, None)
        if message is None:
            # The script is over: from now on the client is gone.
            message = {"type": "http.disconnect"}
        run.events.append(f"receive:{message['type']}")
        if message["type"] == "http.request":
            run.body_messages_delivered += 1
            run.body_bytes_delivered += len(message.get("body", b""))
        return message

    async def send(message: Message) -> None:
        run.events.append(f"send:{message['type']}")
        run.sent.append(message)

    await asyncio.wait_for(app(scope, receive, send), RUN_TIMEOUT_SECONDS)
    return run


async def drive_receive(
    app: Any, scope: dict[str, Any], receive: Callable[[], Awaitable[Message]]
) -> AsgiRun:
    """Like ``drive`` but with a custom async ``receive`` (for stalls and
    slow trickles). The custom receive is responsible for its own timing."""
    run = AsgiRun()

    async def tracked_receive() -> Message:
        message = await receive()
        run.events.append(f"receive:{message['type']}")
        if message["type"] == "http.request":
            run.body_messages_delivered += 1
            run.body_bytes_delivered += len(message.get("body", b""))
        return message

    async def send(message: Message) -> None:
        run.events.append(f"send:{message['type']}")
        run.sent.append(message)

    await asyncio.wait_for(app(scope, tracked_receive, send), RUN_TIMEOUT_SECONDS)
    return run


def response_starts(run: AsgiRun) -> int:
    return sum(1 for m in run.sent if m["type"] == "http.response.start")


def run_driven(app: Any, scope: dict[str, Any], messages: Iterator[Message]) -> AsgiRun:
    return asyncio.run(drive(app, scope, messages))


def post_scope(
    path: str,
    *,
    content_type: str | None = "application/octet-stream",
    content_length: int | str | None = None,
    extra_headers: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """An ASGI scope for ``POST path`` with the given headers."""
    headers: list[tuple[bytes, bytes]] = [(b"host", b"testserver")]
    if content_type is not None:
        headers.append((b"content-type", content_type.encode("latin-1")))
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode("latin-1")))
    for name, value in extra_headers or []:
        headers.append((name.lower().encode("latin-1"), value.encode("latin-1")))
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
