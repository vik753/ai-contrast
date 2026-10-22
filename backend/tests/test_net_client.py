"""S3-T6a item 2: the outbound client factory (ADR 0012 point 4, threat model T2 control 2).

Public interface: ``outbound_client(*, connect_timeout, read_timeout, network_backend=None)``
in ``app/net/client.py``; ``None`` builds a default ``GuardedNetworkBackend()``.
Must fail before the implementation exists (module ``app.net.client`` is missing).

The "production factory uses the guard" test is implementation-agnostic: it replaces the
event loop DNS lookup and the real ``httpcore`` backends, so a default client resolves a
host to ``127.0.0.1`` and must fail with ``BlockedAddressError`` before any socket opens.
"""

from __future__ import annotations

import asyncio
import inspect
import socket
from typing import Any

import httpcore
import httpx
import pytest

from app.net.client import outbound_client
from app.net.guard import BlockedAddressError, GuardedNetworkBackend
from tests.netfakes import PUBLIC_V4, ResolverSpy, SpyInner


def _client(inner: SpyInner | None = None, **kwargs: Any) -> httpx.AsyncClient:
    backend = GuardedNetworkBackend(resolver=ResolverSpy([PUBLIC_V4]), inner=inner or SpyInner())
    return outbound_client(connect_timeout=5, read_timeout=10, network_backend=backend, **kwargs)


def test_outbound_client_signature_is_keyword_only_with_no_extra_parameters() -> None:
    params = inspect.signature(outbound_client).parameters

    assert set(params) == {"connect_timeout", "read_timeout", "network_backend"}
    assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in params.values())


@pytest.mark.parametrize("forbidden", ["proxy", "uds", "mounts", "local_address", "trust_env"])
def test_outbound_client_forbidden_parameter_rejected(forbidden: str) -> None:
    with pytest.raises(TypeError):
        outbound_client(connect_timeout=5, read_timeout=10, **{forbidden: None})  # type: ignore[arg-type]


def test_outbound_client_settings_are_locked_down() -> None:
    client = _client()

    assert isinstance(client, httpx.AsyncClient)
    assert client.trust_env is False
    assert client.follow_redirects is False
    assert client.timeout.connect == 5
    assert client.timeout.read == 10


def test_outbound_client_each_call_returns_a_new_client() -> None:
    assert _client() is not _client()


def test_outbound_client_ignores_proxy_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy", "HTTP_PROXY"):
        monkeypatch.setenv(name, "http://proxy.invalid:3128")
    inner = SpyInner()

    async def go() -> None:
        # The canned answer is a normal 404 response; what matters is where the
        # connection went.
        async with _client(inner) as client:
            await client.get("https://docs.google.com/x")

    asyncio.run(go())

    # The guard sees the target (as its checked IP), never the proxy.
    assert inner.connects
    assert all(connect == (PUBLIC_V4, 443) for connect in inner.connects)


def test_outbound_client_request_through_guard_reaches_inner_with_ip() -> None:
    inner = SpyInner()

    async def go() -> int:
        async with _client(inner) as client:
            return (await client.get("https://docs.google.com/x")).status_code

    assert asyncio.run(go()) == 404
    assert inner.connects == [(PUBLIC_V4, 443)]


def test_outbound_client_does_not_follow_redirects() -> None:
    inner = SpyInner(
        answer=b"HTTP/1.1 302 Found\r\nLocation: https://evil.example/\r\nContent-Length: 0\r\n\r\n"
    )

    async def go() -> int:
        async with _client(inner) as client:
            return (await client.get("https://docs.google.com/x")).status_code

    assert asyncio.run(go()) == 302
    assert len(inner.connects) == 1


def test_outbound_client_port_other_than_443_is_refused() -> None:
    inner = SpyInner()

    async def go() -> None:
        async with _client(inner) as client:
            await client.get("https://docs.google.com:8443/x")

    with pytest.raises(Exception) as info:  # noqa: PT011 - guard error type is ADR-open
        asyncio.run(go())

    assert inner.connects == []
    assert "8443" not in str(info.value)


def test_outbound_client_plain_http_is_refused_before_connecting() -> None:
    inner = SpyInner()

    async def go() -> None:
        async with _client(inner) as client:
            await client.get("http://docs.google.com/x")

    with pytest.raises(Exception):  # noqa: B017, PT011 - guard error type is ADR-open
        asyncio.run(go())

    assert inner.connects == []


def test_outbound_client_production_default_uses_the_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookups: list[str] = []
    real_connects: list[str] = []
    answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]

    async def fake_loop_getaddrinfo(self: object, host: str, port: object, **kw: object) -> Any:
        lookups.append(str(host))
        return answer

    def fake_getaddrinfo(host: str, port: object, *args: object, **kw: object) -> Any:
        lookups.append(str(host))
        return answer

    async def refuse_connect(self: object, *args: object, **kw: object) -> Any:
        real_connects.append("connect")
        msg = "the inner backend must not be asked to connect"
        raise AssertionError(msg)

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake_loop_getaddrinfo)
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", refuse_connect)
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_unix_socket", refuse_connect)
    from httpcore._backends.auto import AutoBackend  # noqa: PLC0415 - private, patched on purpose

    monkeypatch.setattr(AutoBackend, "connect_tcp", refuse_connect)

    async def go() -> None:
        async with outbound_client(connect_timeout=5, read_timeout=10) as client:
            await client.get("https://example.com/")

    with pytest.raises(BlockedAddressError):
        asyncio.run(go())

    assert real_connects == []
    assert lookups  # the lookup happened through the patched resolver
