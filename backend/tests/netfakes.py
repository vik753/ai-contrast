"""Fakes for the outbound HTTP tests (S3-T6a, ADR 0012 point 6). No network.

``SpyInner`` is an ``httpcore2`` network backend that records every connect and returns
a fake stream with a canned HTTP/1.1 answer. ``fixed_resolver`` makes a resolver that
returns a fixed address list for any host.
"""

from __future__ import annotations

import asyncio
import inspect
import ssl
from collections.abc import Callable, Iterable, Sequence
from typing import Any

import httpcore2
import httpx2

PUBLIC_V4 = "93.184.216.34"
PUBLIC_V4_2 = "151.101.1.69"
PUBLIC_V6 = "2606:2800:220:1:248:1893:25c8:1946"


class ResolverSpy:
    """A resolver that returns ``addresses`` and records its calls."""

    def __init__(self, addresses: Sequence[str]) -> None:
        self.addresses = list(addresses)
        self.calls: list[tuple[str, int]] = []

    async def __call__(self, host: str, port: int) -> list[str]:
        self.calls.append((host, port))
        return list(self.addresses)


class FakeStream(httpcore2.AsyncNetworkStream):
    def __init__(self, answer: bytes) -> None:
        self._answer = answer

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        data, self._answer = self._answer[:max_bytes], self._answer[max_bytes:]
        return data

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        return None

    async def aclose(self) -> None:
        return None

    async def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> httpcore2.AsyncNetworkStream:
        return self

    def get_extra_info(self, info: str) -> object:
        return None


def http_answer(status_line: str = "404 Not Found") -> bytes:
    return f"HTTP/1.1 {status_line}\r\nContent-Length: 0\r\n\r\n".encode()


class SpyInner(httpcore2.AsyncNetworkBackend):
    """Records ``(host, port)`` of every connect. Hosts in ``failing`` raise ``ConnectError``."""

    def __init__(self, *, failing: Iterable[str] = (), answer: bytes | None = None) -> None:
        self.failing = set(failing)
        self.answer = answer if answer is not None else http_answer()
        self.connects: list[tuple[str, int]] = []
        self.unix: list[str] = []

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[tuple[int, int, int] | tuple[int, int, int, bytes]] | None = None,
    ) -> httpcore2.AsyncNetworkStream:
        self.connects.append((host, port))
        if host in self.failing:
            msg = "fake connect failure"
            raise httpcore2.ConnectError(msg)
        return FakeStream(self.answer)

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[tuple[int, int, int] | tuple[int, int, int, bytes]] | None = None,
    ) -> httpcore2.AsyncNetworkStream:
        self.unix.append(path)
        return FakeStream(self.answer)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class StreamingTransport(httpx2.AsyncBaseTransport):
    """Like ``httpx2.MockTransport``, but every answer is a stream that is not read yet.

    ``httpx2.Response(content=<bytes>)`` is read and consumed when it is built. A real
    transport never returns such a response, and the fetcher reads the raw stream.
    """

    def __init__(self, handler: Callable[[httpx2.Request], Any]) -> None:
        self._handler = handler

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        await request.aread()
        answer = self._handler(request)
        if inspect.isawaitable(answer):
            answer = await answer
        assert isinstance(answer, httpx2.Response)
        if not answer.is_stream_consumed:
            return answer
        return httpx2.Response(
            answer.status_code,
            headers=answer.headers,
            stream=httpx2.ByteStream(answer.content),
        )
