"""The outbound client for AI provider calls (ADR 0016 point 3).

It wraps the guarded transport of ``client.py`` (or a test transport) and adds three rules
that hold on every path, so the production path and the test path share one wrapper:

- every 3xx response is refused (a redirect would carry the provider key to another host);
- the response body is capped (streamed, fails closed);
- only an allowlist of request headers leaves the process, so an SDK default or an SDK
  environment variable (custom headers, organization, trace context) has no effect.

Only this package imports ``httpx2``; ``app/ai/`` gets the types it needs from here.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import TracebackType
from typing import Final

import httpx2

from app.net.client import _GuardedTransport
from app.net.guard import GuardedNetworkBackend

AITransport = httpx2.AsyncBaseTransport
AIHttpClient = httpx2.AsyncClient

MAX_RESPONSE_BYTES: Final = 2 * 1024 * 1024
_WRITE_TIMEOUT_SECONDS: Final = 10.0
_POOL_TIMEOUT_SECONDS: Final = 5.0
_ALLOWED_HEADERS: Final = frozenset(
    {
        "accept",
        "accept-encoding",
        "authorization",
        "anthropic-version",
        "connection",
        "content-length",
        "content-type",
        "host",
        "transfer-encoding",
        "user-agent",
        "x-api-key",
    }
)


class RedirectRefusedError(Exception):
    """The provider answered with a 3xx status."""


class ResponseTooLargeError(Exception):
    """The response body is larger than the cap."""


class _CappedStream(httpx2.AsyncByteStream):
    def __init__(self, stream: httpx2.AsyncByteStream, limit: int) -> None:
        self._stream = stream
        self._limit = limit

    async def __aiter__(self) -> AsyncIterator[bytes]:
        total = 0
        async for part in self._stream:
            total += len(part)
            if total > self._limit:
                raise ResponseTooLargeError("response is too large")  # noqa: TRY003
            yield part

    async def aclose(self) -> None:
        await self._stream.aclose()


class _AITransport(httpx2.AsyncBaseTransport):
    def __init__(
        self, inner: httpx2.AsyncBaseTransport, *, owns_inner: bool, max_bytes: int
    ) -> None:
        self._inner = inner
        self._owns_inner = owns_inner
        self._max_bytes = max_bytes

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        # A filtered copy: the SDK reads its own marker headers from the original request.
        outgoing = httpx2.Request(
            method=request.method,
            url=request.url,
            headers=[
                (k, v) for k, v in request.headers.raw if k.decode().lower() in _ALLOWED_HEADERS
            ],
            stream=request.stream,
            extensions=request.extensions,
        )
        response = await self._inner.handle_async_request(outgoing)
        try:
            self._check(response)
        except Exception:
            await response.aclose()
            raise
        stream = response.stream
        assert isinstance(stream, httpx2.AsyncByteStream)  # noqa: S101 - async transport
        return httpx2.Response(
            status_code=response.status_code,
            headers=response.headers,
            stream=_CappedStream(stream, self._max_bytes),
            extensions=response.extensions,
        )

    def _check(self, response: httpx2.Response) -> None:
        if 300 <= response.status_code < 400:  # noqa: PLR2004 - the 3xx class
            raise RedirectRefusedError("redirect is refused")  # noqa: TRY003
        length = response.headers.get("content-length", "")
        if length.isascii() and length.isdigit() and int(length) > self._max_bytes:
            raise ResponseTooLargeError("response is too large")  # noqa: TRY003

    async def aclose(self) -> None:
        if self._owns_inner:
            await self._inner.aclose()

    async def __aenter__(self) -> _AITransport:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        await self.aclose()


def ai_client(
    *,
    connect_timeout: float,
    read_timeout: float,
    transport: AITransport | None = None,
    max_response_bytes: int = MAX_RESPONSE_BYTES,
) -> httpx2.AsyncClient:
    """Return a new client for one AI call. The caller closes it.

    Without ``transport`` the connection goes through the SSRF guard. ``transport`` is a
    test hook; the redirect refusal, the size cap and the header allowlist apply to it too.
    """
    inner = transport if transport is not None else _GuardedTransport(GuardedNetworkBackend())
    return httpx2.AsyncClient(
        transport=_AITransport(inner, owns_inner=transport is None, max_bytes=max_response_bytes),
        timeout=httpx2.Timeout(
            read_timeout,
            connect=connect_timeout,
            write=_WRITE_TIMEOUT_SECONDS,
            pool=_POOL_TIMEOUT_SECONDS,
        ),
        follow_redirects=False,
        trust_env=False,
    )
