"""The outbound HTTP client factory (ADR 0012 point 4).

A new client per call. ``trust_env=False``, no redirects, HTTP/1.1 only, no retries,
certificate verification with the ``certifi`` bundle, and the SSRF guard below the
transport. The factory takes no proxy, Unix socket, mounts or local address.

``_GuardedTransport`` is our own ``httpx`` transport on top of an ``httpcore`` connection
pool with the guarded network backend. It uses public APIs only. Errors are mapped to
``httpx`` errors with fixed texts (the text of a ``httpcore`` error can hold the URL);
guard errors pass through unchanged.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator, Callable
from types import TracebackType
from typing import Final, cast

import httpcore
import httpx

from app.net.guard import HTTPS_PORT, BlockedHostError, GuardedNetworkBackend

# Builds one new guarded client per fetch (``outbound_client`` with the settings applied).
ClientFactory = Callable[[], httpx.AsyncClient]

MAX_CONNECTIONS: Final = 4
_WRITE_TIMEOUT_SECONDS: Final = 10.0
_POOL_TIMEOUT_SECONDS: Final = 5.0

# More specific classes first.
_ERROR_MAP: Final[tuple[tuple[type[Exception], type[httpx.TransportError]], ...]] = (
    (httpcore.ConnectTimeout, httpx.ConnectTimeout),
    (httpcore.ReadTimeout, httpx.ReadTimeout),
    (httpcore.WriteTimeout, httpx.WriteTimeout),
    (httpcore.PoolTimeout, httpx.PoolTimeout),
    (httpcore.TimeoutException, httpx.TimeoutException),
    (httpcore.ConnectError, httpx.ConnectError),
    (httpcore.ReadError, httpx.ReadError),
    (httpcore.WriteError, httpx.WriteError),
    (httpcore.NetworkError, httpx.NetworkError),
    (httpcore.UnsupportedProtocol, httpx.UnsupportedProtocol),
    (httpcore.LocalProtocolError, httpx.LocalProtocolError),
    (httpcore.RemoteProtocolError, httpx.RemoteProtocolError),
    (httpcore.ProtocolError, httpx.ProtocolError),
    (httpcore.ProxyError, httpx.ProxyError),
)


def _mapped(error: Exception) -> Exception | None:
    for source, target in _ERROR_MAP:
        if isinstance(error, source):
            return target("transport error")
    return None


class _ResponseStream(httpx.AsyncByteStream):
    def __init__(self, stream: AsyncIterable[bytes]) -> None:
        self._stream = stream

    async def __aiter__(self) -> AsyncIterator[bytes]:
        try:
            async for part in self._stream:
                yield part
        except Exception as error:
            mapped = _mapped(error)
            if mapped is None:
                raise
            raise mapped from None

    async def aclose(self) -> None:
        close = getattr(self._stream, "aclose", None)
        if close is not None:
            await close()


class _GuardedTransport(httpx.AsyncBaseTransport):
    def __init__(self, network_backend: httpcore.AsyncNetworkBackend) -> None:
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(verify=True, trust_env=False),
            max_connections=MAX_CONNECTIONS,
            http1=True,
            http2=False,
            retries=0,
            network_backend=network_backend,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.scheme != "https":
            raise BlockedHostError("scheme is not allowed")  # noqa: TRY003
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=url.raw_scheme,
                host=url.raw_host,
                port=url.port or HTTPS_PORT,
                target=url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        try:
            core_response = await self._pool.handle_async_request(core_request)
        except Exception as error:
            mapped = _mapped(error)
            if mapped is None:
                raise
            raise mapped from None
        return httpx.Response(
            status_code=core_response.status,
            headers=core_response.headers,
            stream=_ResponseStream(cast(AsyncIterable[bytes], core_response.stream)),
            extensions=core_response.extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()

    async def __aenter__(self) -> _GuardedTransport:
        await self._pool.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        await self._pool.__aexit__(exc_type, exc_value, traceback)


def outbound_client(
    *,
    connect_timeout: float,
    read_timeout: float,
    network_backend: httpcore.AsyncNetworkBackend | None = None,
) -> httpx.AsyncClient:
    """Return a new guarded client. The caller closes it (``async with``)."""
    backend = network_backend if network_backend is not None else GuardedNetworkBackend()
    return httpx.AsyncClient(
        transport=_GuardedTransport(backend),
        timeout=httpx.Timeout(
            read_timeout,
            connect=connect_timeout,
            write=_WRITE_TIMEOUT_SECONDS,
            pool=_POOL_TIMEOUT_SECONDS,
        ),
        follow_redirects=False,
        trust_env=False,
    )
