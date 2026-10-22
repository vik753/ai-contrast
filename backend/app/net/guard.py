"""SSRF guard as an ``httpcore`` network backend (ADR 0012 point 3, threat model T2).

Rules for ``GuardedNetworkBackend.connect_tcp``: port 443 only; a DNS hostname only (no
IP literal in any notation, no single-label name); the name is resolved once, inside the
connect timeout; the whole result is refused if any address is not public; the checked IP
is what is connected to (TLS and SNI use the original host, set by ``httpcore``).

Errors carry fixed texts. They never contain the host, the port or an address. A resolver
``OSError`` (``socket.gaierror`` included) becomes ``httpcore.ConnectError``.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections.abc import Awaitable, Callable, Iterable, Sequence
from typing import Final

import httpcore

HTTPS_PORT: Final = 443
_MAX_HOST_LENGTH: Final = 253
_LABEL_RE: Final = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", re.ASCII)
_TLD_RE: Final = re.compile(r"[a-z]{2,63}|xn--[a-z0-9-]{1,59}", re.ASCII)
_NAT64: Final = ipaddress.IPv6Network("64:ff9b::/96")
_GLOBAL_V6: Final = ipaddress.IPv6Network("2000::/3")
_SIX_TO_FOUR: Final = ipaddress.IPv6Network("2002::/16")
_V4_MASK: Final = 0xFFFFFFFF
_SIX_TO_FOUR_SHIFT: Final = 80

Resolver = Callable[[str, int], Awaitable[Sequence[str]]]


class BlockedHostError(Exception):
    """The host name or the port is not allowed."""


class BlockedAddressError(Exception):
    """A resolved address is not public, or the result is empty or unparsable."""


def check_hostname(host: str) -> str:
    """Return the normalized host name (lower case, one trailing dot stripped)."""
    if not host.isascii():
        raise BlockedHostError("host name is not allowed")  # noqa: TRY003
    name = host.lower()
    if name.endswith("."):
        name = name[:-1]
    labels = name.split(".")
    if (
        len(name) > _MAX_HOST_LENGTH
        or len(labels) < 2  # noqa: PLR2004 - at least two labels
        or not all(_LABEL_RE.fullmatch(label) for label in labels)
        or not _TLD_RE.fullmatch(labels[-1])
    ):
        raise BlockedHostError("host name is not allowed")  # noqa: TRY003
    return name


def _is_public_v4(ip: ipaddress.IPv4Address) -> bool:
    return ip.is_global and not ip.is_multicast


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv4Address):
        return _is_public_v4(ip)
    if ip.ipv4_mapped is not None:
        return _is_public_v4(ip.ipv4_mapped)
    if ip in _NAT64:
        return _is_public_v4(ipaddress.IPv4Address(int(ip) & _V4_MASK))
    if ip in _SIX_TO_FOUR:
        embedded = ipaddress.IPv4Address((int(ip) >> _SIX_TO_FOUR_SHIFT) & _V4_MASK)
        if not _is_public_v4(embedded):
            return False
    return ip in _GLOBAL_V6 and ip.is_global and not ip.is_multicast


def check_addresses(addresses: Sequence[str]) -> list[str]:
    """Return ``addresses`` if all are public; raise ``BlockedAddressError`` otherwise.

    An empty list and an unparsable entry are refused (fail closed).
    """
    if not addresses:
        raise BlockedAddressError("address is not allowed")  # noqa: TRY003
    for text in addresses:
        try:
            ip = ipaddress.ip_address(text)
        except ValueError:
            raise BlockedAddressError("address is not allowed") from None  # noqa: TRY003
        if getattr(ip, "scope_id", None) or not _is_public(ip):
            raise BlockedAddressError("address is not allowed")  # noqa: TRY003
    return list(addresses)


async def system_resolver(host: str, port: int) -> list[str]:
    """Resolve with the non-blocking resolver of the event loop. Order is kept."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    seen: dict[str, None] = {}
    for info in infos:
        seen.setdefault(str(info[4][0]), None)
    return list(seen)


class GuardedNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(
        self,
        *,
        resolver: Resolver | None = None,
        inner: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self._resolver: Resolver = resolver or system_resolver
        self._inner: httpcore.AsyncNetworkBackend = inner or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        if port != HTTPS_PORT:
            raise BlockedHostError("port is not allowed")  # noqa: TRY003
        name = check_hostname(host)
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout
        try:
            async with asyncio.timeout_at(deadline):
                resolved = await self._resolver(name, port)
        except TimeoutError:
            raise httpcore.ConnectTimeout("connect timeout") from None  # noqa: TRY003
        except OSError:
            # ``socket.gaierror`` is an ``OSError``; its text holds the host name.
            raise httpcore.ConnectError("name resolution failed") from None  # noqa: TRY003
        addresses = check_addresses(list(resolved))

        timed_out = False
        for address in addresses:
            remaining = None if deadline is None else deadline - loop.time()
            if remaining is not None and remaining <= 0:
                timed_out = True
                break
            try:
                return await self._inner.connect_tcp(
                    address,
                    port,
                    timeout=remaining,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except httpcore.ConnectTimeout:
                timed_out = True
            except httpcore.ConnectError:
                timed_out = False
        if timed_out:
            raise httpcore.ConnectTimeout("connect timeout")  # noqa: TRY003
        raise httpcore.ConnectError("connect failed")  # noqa: TRY003

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise BlockedHostError("unix sockets are not allowed")  # noqa: TRY003

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)
