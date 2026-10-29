"""Client key from the ASGI scope (ADR 0016 point 8, threat model T6).

Production: the Nth entry from the right of ``X-Forwarded-For`` (N = ``TRUSTED_PROXY_HOPS``);
entries to its left can be forged by the client and are ignored; the socket peer is the
proxy and is never used. Development: the socket peer; the header is ignored.
Anything missing or invalid gives ``unknown``. IPv6 is keyed by its /64 prefix, an
IPv4-mapped IPv6 address by its IPv4 address. The key is never logged.
"""

from __future__ import annotations

import ipaddress
from typing import Final

from starlette.types import Scope

from app.settings import Settings

UNKNOWN: Final = "unknown"
_IPV6_PREFIX: Final = 64


def _key_of(text: str) -> str:
    if not text.isascii() or "%" in text or any(char.isspace() for char in text):
        return UNKNOWN
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return UNKNOWN
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            return str(address.ipv4_mapped)
        return str(ipaddress.IPv6Network((address, _IPV6_PREFIX), strict=False))
    return str(address)


def _forwarded_entries(scope: Scope) -> list[str]:
    values = [
        value.decode("latin-1")
        for name, value in scope.get("headers", [])
        if name.lower() == b"x-forwarded-for"
    ]
    return [entry.strip(" \t") for entry in ",".join(values).split(",")] if values else []


def client_key(scope: Scope, settings: Settings) -> str:
    """The rate-limit key of the client of this request."""
    if settings.environment != "production":
        client = scope.get("client")
        if not client or not isinstance(client[0], str):
            return UNKNOWN
        return _key_of(client[0])
    entries = _forwarded_entries(scope)
    if len(entries) < settings.trusted_proxy_hops:
        return UNKNOWN
    return _key_of(entries[-settings.trusted_proxy_hops])
