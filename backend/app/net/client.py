"""The outbound HTTP client factory (ADR 0012 point 4).

A new client per call. ``trust_env=False``, no redirects, HTTP/1.1 only, no retries,
certificate verification with the ``certifi`` bundle, and the SSRF guard below the
transport. The factory takes no proxy, Unix socket, mounts or local address.

``_GuardedTransport`` is our own ``httpx2`` transport on top of an ``httpcore2`` connection
pool with the guarded network backend. It uses public APIs only. Errors are mapped to
``httpx2`` errors with fixed texts (the text of a ``httpcore2`` error can hold the URL);
guard errors pass through unchanged.
"""

from __future__ import annotations

import ssl
from collections.abc import AsyncIterable, AsyncIterator, Callable
from types import TracebackType
from typing import Final, cast

import certifi
import httpcore2
import httpx2

from app.net.guard import HTTPS_PORT, BlockedHostError, GuardedNetworkBackend

# Builds one new guarded client per fetch (``outbound_client`` with the settings applied).
ClientFactory = Callable[[], httpx2.AsyncClient]

MAX_CONNECTIONS: Final = 4
_WRITE_TIMEOUT_SECONDS: Final = 10.0
_POOL_TIMEOUT_SECONDS: Final = 5.0

# More specific classes first.
_ERROR_MAP: Final[tuple[tuple[type[Exception], type[httpx2.TransportError]], ...]] = (
    (httpcore2.ConnectTimeout, httpx2.ConnectTimeout),
    (httpcore2.ReadTimeout, httpx2.ReadTimeout),
    (httpcore2.WriteTimeout, httpx2.WriteTimeout),
    (httpcore2.PoolTimeout, httpx2.PoolTimeout),
    (httpcore2.TimeoutException, httpx2.TimeoutException),
    (httpcore2.ConnectError, httpx2.ConnectError),
    (httpcore2.ReadError, httpx2.ReadError),
    (httpcore2.WriteError, httpx2.WriteError),
    (httpcore2.NetworkError, httpx2.NetworkError),
    (httpcore2.UnsupportedProtocol, httpx2.UnsupportedProtocol),
    (httpcore2.LocalProtocolError, httpx2.LocalProtocolError),
    (httpcore2.RemoteProtocolError, httpx2.RemoteProtocolError),
    (httpcore2.ProtocolError, httpx2.ProtocolError),
    (httpcore2.ProxyError, httpx2.ProxyError),
)


def _mapped(error: Exception) -> Exception | None:
    for source, target in _ERROR_MAP:
        if isinstance(error, source):
            return target("transport error")
    return None


class _ResponseStream(httpx2.AsyncByteStream):
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


class _GuardedTransport(httpx2.AsyncBaseTransport):
    def __init__(self, network_backend: httpcore2.AsyncNetworkBackend) -> None:
        # Explicit certifi bundle: no env variable, no OS store, no truststore (ADR 0016).
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        # The TLS secrets of a fetch never go to a file, whatever ``SSLKEYLOGFILE`` says.
        ssl_context.keylog_filename = None  # type: ignore[assignment]  # typeshed: str
        self._pool = httpcore2.AsyncConnectionPool(
            ssl_context=ssl_context,
            max_connections=MAX_CONNECTIONS,
            http1=True,
            http2=False,
            retries=0,
            network_backend=network_backend,
        )

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        url = request.url
        if url.scheme != "https":
            raise BlockedHostError("scheme is not allowed")  # noqa: TRY003
        if "sni_hostname" in request.extensions:
            # It would send another TLS server name than the checked host (ADR 0012).
            raise BlockedHostError("extension is not allowed")  # noqa: TRY003
        core_request = httpcore2.Request(
            method=request.method,
            url=httpcore2.URL(
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
        return httpx2.Response(
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
    network_backend: httpcore2.AsyncNetworkBackend | None = None,
) -> httpx2.AsyncClient:
    """Return a new guarded client. The caller closes it (``async with``)."""
    backend = network_backend if network_backend is not None else GuardedNetworkBackend()
    return httpx2.AsyncClient(
        transport=_GuardedTransport(backend),
        timeout=httpx2.Timeout(
            read_timeout,
            connect=connect_timeout,
            write=_WRITE_TIMEOUT_SECONDS,
            pool=_POOL_TIMEOUT_SECONDS,
        ),
        follow_redirects=False,
        trust_env=False,
    )
