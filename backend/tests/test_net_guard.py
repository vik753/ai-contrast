"""S3-T6a items 1 and 4: the SSRF guard (ADR 0012 point 3, threat model T2 controls 2 and 4).

Public interface (app/net/guard.py): ``check_hostname``, ``check_addresses``,
``BlockedHostError``, ``BlockedAddressError``, ``GuardedNetworkBackend(resolver=, inner=)``.
Assumptions: a refused port raises ``BlockedHostError`` or ``BlockedAddressError``; a
resolver slower than the connect timeout raises ``httpcore2.ConnectTimeout``; an empty or
unparsable address list is refused (fail closed).
Must fail before the implementation exists (module ``app.net.guard`` is missing).
"""

from __future__ import annotations

import asyncio

import httpcore2
import pytest

from app.net.guard import (
    BlockedAddressError,
    BlockedHostError,
    GuardedNetworkBackend,
    check_addresses,
    check_hostname,
)
from tests.netfakes import PUBLIC_V4, PUBLIC_V4_2, PUBLIC_V6, ResolverSpy, SpyInner

REFUSED_HOSTS = [
    "127.0.0.1",
    "127.1",
    "0.0.0.0",  # noqa: S104 - a refused literal, not a bind address
    "[::1]",
    "::1",
    "2130706433",
    "0x7f000001",
    "0177.0.0.1",
    "8.8.8.8",
    "localhost",
    "intranet",
    "-bad-.com",
    "bad-.com",
    "-bad.com",
    "",
    ".",
    "a..com",
    "example.com..",
    "example",
    "example.c",
    "example.123",
    "example.c0m",
    "exa_mple.com",
    "exa mple.com",
    "example.com:443",
    "example.com/path",
    "user@example.com",
    "пример.рф",
    ("a" * 64) + ".com",
    "example." + ("a" * 64),
]
PRIVATE_ADDRESSES = [
    "127.0.0.1",
    "10.0.0.1",
    "172.16.0.1",
    "192.168.0.1",
    "169.254.169.254",
    "100.64.0.1",
    "0.0.0.0",  # noqa: S104 - a refused address, not a bind address
    "224.0.0.1",
    "255.255.255.255",
    "::1",
    "::",
    "fd00::1",
    "fe80::1",
    "fec0::1",
    "ff02::1",
    "::7f00:1",
    "::ffff:127.0.0.1",
    "::ffff:224.0.0.1",
    "64:ff9b::7f00:1",
    "64:ff9b::a00:1",
]


def _run(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


# --- check_hostname ---------------------------------------------------------------------


@pytest.mark.parametrize("host", REFUSED_HOSTS)
def test_check_hostname_refused_host_raises_blocked_host(host: str) -> None:
    with pytest.raises(BlockedHostError) as info:
        check_hostname(host)

    if host:
        assert host not in str(info.value)


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("Example.COM.", "example.com"),
        ("example.com", "example.com"),
        ("docs.google.com", "docs.google.com"),
        ("a.b-c.example.org", "a.b-c.example.org"),
        ("xn--e1afmkfd.xn--p1ai", "xn--e1afmkfd.xn--p1ai"),
        ("doc-0k-0s-docs.googleusercontent.com", "doc-0k-0s-docs.googleusercontent.com"),
        (("a" * 63) + ".com", ("a" * 63) + ".com"),
    ],
)
def test_check_hostname_valid_host_returns_normalized(host: str, expected: str) -> None:
    assert check_hostname(host) == expected


def test_check_hostname_error_is_not_an_address_error() -> None:
    assert not issubclass(BlockedHostError, BlockedAddressError)
    assert not issubclass(BlockedAddressError, BlockedHostError)


# --- check_addresses --------------------------------------------------------------------


@pytest.mark.parametrize("address", PRIVATE_ADDRESSES)
def test_check_addresses_non_public_address_raises_blocked_address(address: str) -> None:
    with pytest.raises(BlockedAddressError) as info:
        check_addresses([address])

    assert address not in str(info.value)


@pytest.mark.parametrize("address", PRIVATE_ADDRESSES)
def test_check_addresses_mixed_with_public_refuses_whole_result(address: str) -> None:
    with pytest.raises(BlockedAddressError):
        check_addresses([PUBLIC_V4, address, PUBLIC_V6])


def test_check_addresses_public_addresses_returned_in_order() -> None:
    assert check_addresses([PUBLIC_V6, PUBLIC_V4, PUBLIC_V4_2]) == [
        PUBLIC_V6,
        PUBLIC_V4,
        PUBLIC_V4_2,
    ]


@pytest.mark.parametrize("address", ["::ffff:8.8.8.8", "64:ff9b::808:808"])
def test_check_addresses_mapped_or_nat64_public_ipv4_accepted(address: str) -> None:
    assert len(check_addresses([address])) == 1


@pytest.mark.parametrize("addresses", [[], ["not-an-ip"], ["example.com"], [""], ["1.2.3"]])
def test_check_addresses_empty_or_unparsable_refused(addresses: list[str]) -> None:
    with pytest.raises(BlockedAddressError):
        check_addresses(addresses)


# --- GuardedNetworkBackend --------------------------------------------------------------


def _backend(
    addresses: list[str], *, failing: tuple[str, ...] = ()
) -> tuple[GuardedNetworkBackend, ResolverSpy, SpyInner]:
    resolver = ResolverSpy(addresses)
    inner = SpyInner(failing=failing)
    return GuardedNetworkBackend(resolver=resolver, inner=inner), resolver, inner


def test_connect_tcp_passes_ip_string_not_hostname_to_inner() -> None:
    backend, resolver, inner = _backend([PUBLIC_V4])

    _run(backend.connect_tcp("Example.COM.", 443, timeout=5))

    assert inner.connects == [(PUBLIC_V4, 443)]
    assert resolver.calls == [("example.com", 443)]


@pytest.mark.parametrize("host", REFUSED_HOSTS)
def test_connect_tcp_refused_host_never_resolves_or_connects(host: str) -> None:
    backend, resolver, inner = _backend([PUBLIC_V4])

    with pytest.raises(BlockedHostError):
        _run(backend.connect_tcp(host, 443, timeout=5))

    assert resolver.calls == []
    assert inner.connects == []


@pytest.mark.parametrize("port", [80, 8443, 0, 22, 444, 65535])
def test_connect_tcp_port_other_than_443_refused_before_resolving(port: int) -> None:
    backend, resolver, inner = _backend([PUBLIC_V4])

    with pytest.raises((BlockedHostError, BlockedAddressError)):
        _run(backend.connect_tcp("example.com", port, timeout=5))

    assert resolver.calls == []
    assert inner.connects == []


@pytest.mark.parametrize("address", PRIVATE_ADDRESSES)
def test_connect_tcp_resolver_returns_non_public_refused_inner_not_called(address: str) -> None:
    backend, resolver, inner = _backend([address])

    with pytest.raises(BlockedAddressError):
        _run(backend.connect_tcp("example.com", 443, timeout=5))

    assert len(resolver.calls) == 1
    assert inner.connects == []


def test_connect_tcp_mixed_public_and_private_result_refused_whole() -> None:
    backend, _, inner = _backend([PUBLIC_V4, "10.0.0.1"])

    with pytest.raises(BlockedAddressError):
        _run(backend.connect_tcp("example.com", 443, timeout=5))

    assert inner.connects == []


def test_connect_tcp_first_address_fails_second_is_tried_and_dns_resolved_once() -> None:
    backend, resolver, inner = _backend([PUBLIC_V4, PUBLIC_V4_2], failing=(PUBLIC_V4,))

    _run(backend.connect_tcp("example.com", 443, timeout=5))

    assert inner.connects == [(PUBLIC_V4, 443), (PUBLIC_V4_2, 443)]
    assert len(resolver.calls) == 1


def test_connect_tcp_all_addresses_fail_raises_connect_error_after_trying_each() -> None:
    backend, _, inner = _backend([PUBLIC_V4, PUBLIC_V4_2], failing=(PUBLIC_V4, PUBLIC_V4_2))

    with pytest.raises(httpcore2.ConnectError):
        _run(backend.connect_tcp("example.com", 443, timeout=5))

    assert inner.connects == [(PUBLIC_V4, 443), (PUBLIC_V4_2, 443)]


def test_connect_tcp_slow_resolver_hits_connect_timeout() -> None:
    inner = SpyInner()

    async def slow(host: str, port: int) -> list[str]:
        await asyncio.sleep(5)
        return [PUBLIC_V4]

    backend = GuardedNetworkBackend(resolver=slow, inner=inner)

    with pytest.raises(httpcore2.ConnectTimeout):
        _run(backend.connect_tcp("example.com", 443, timeout=0.1))

    assert inner.connects == []


def test_connect_unix_socket_always_refused() -> None:
    backend, resolver, inner = _backend([PUBLIC_V4])

    with pytest.raises(BlockedHostError):
        _run(backend.connect_unix_socket("/var/run/docker.sock"))

    assert inner.unix == []
    assert inner.connects == []
    assert resolver.calls == []
