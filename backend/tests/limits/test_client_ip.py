"""S6-T3 AC2: client key (ADR 0016 point 8, T6 control 6)."""

from __future__ import annotations

from typing import Any

import pytest
from app.limits.client_ip import client_key

from app.settings import Settings
from tests.helpers import ALLOWED_ORIGIN


def prod(hops: int = 1) -> Settings:
    return Settings(
        environment="production", allowed_origins=[ALLOWED_ORIGIN], trusted_proxy_hops=hops
    )


def dev() -> Settings:
    return Settings(environment="development")


def scope(peer: str | None = "10.0.0.1", xff: list[str] | None = None) -> dict[str, Any]:
    headers = [(b"x-forwarded-for", value.encode("latin-1")) for value in xff or []]
    return {
        "type": "http",
        "headers": headers,
        "client": (peer, 50000) if peer is not None else None,
    }


def test_settings_defaults_one_hop_one_slot_per_client() -> None:
    settings = Settings(environment="development")

    assert settings.trusted_proxy_hops == 1
    assert settings.max_extractions_per_client == 1


def test_settings_read_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "2")
    monkeypatch.setenv("MAX_EXTRACTIONS_PER_CLIENT", "2")

    settings = Settings(environment="development")

    assert settings.trusted_proxy_hops == 2
    assert settings.max_extractions_per_client == 2


def test_production_uses_rightmost_entry() -> None:
    assert client_key(scope(xff=["198.51.100.9"]), prod()) == "198.51.100.9"


def test_production_ignores_spoofed_leftmost_entries() -> None:
    spoofed = scope(xff=["1.1.1.1, 2.2.2.2, 198.51.100.9"])
    honest = scope(xff=["198.51.100.9"])

    assert client_key(spoofed, prod()) == client_key(honest, prod())


def test_production_ignores_the_peer() -> None:
    a = scope(peer="10.0.0.1", xff=["198.51.100.9"])
    b = scope(peer="10.9.9.9", xff=["198.51.100.9"])

    assert client_key(a, prod()) == client_key(b, prod())


def test_production_strips_spaces_around_entries() -> None:
    assert client_key(scope(xff=["1.1.1.1 ,   198.51.100.9  "]), prod()) == "198.51.100.9"


def test_production_joins_repeated_headers_and_takes_the_last_entry() -> None:
    s = scope(xff=["198.51.100.1", "6.6.6.6, 198.51.100.9"])

    assert client_key(s, prod()) == "198.51.100.9"


def test_production_two_hops_takes_second_from_right() -> None:
    s = scope(xff=["1.1.1.1, 198.51.100.5, 10.1.1.1"])

    assert client_key(s, prod(hops=2)) == "198.51.100.5"


def test_production_fewer_entries_than_hops_is_unknown() -> None:
    assert client_key(scope(xff=["198.51.100.5"]), prod(hops=2)) == "unknown"


def test_production_missing_header_is_unknown_not_the_peer() -> None:
    assert client_key(scope(peer="198.51.100.5"), prod()) == "unknown"


@pytest.mark.parametrize(
    "value",
    ["", "   ", "not-an-ip", "999.1.1.1", "1.2.3", "1.2.3.4:8080", "1.1.1.1,", "unknown", "::g"],
)
def test_production_invalid_rightmost_entry_is_unknown(value: str) -> None:
    assert client_key(scope(xff=[value]), prod()) == "unknown"


def test_development_uses_the_peer() -> None:
    assert client_key(scope(peer="198.51.100.7"), dev()) == "198.51.100.7"


def test_development_ignores_forwarded_for() -> None:
    s = scope(peer="198.51.100.7", xff=["203.0.113.1"])

    assert client_key(s, dev()) == "198.51.100.7"


@pytest.mark.parametrize("peer", [None, "testclient", "", "300.1.1.1"])
def test_development_missing_or_invalid_peer_is_unknown(peer: str | None) -> None:
    assert client_key(scope(peer=peer), dev()) == "unknown"


def test_different_ipv4_addresses_have_different_keys() -> None:
    a = client_key(scope(xff=["198.51.100.1"]), prod())
    b = client_key(scope(xff=["198.51.100.2"]), prod())

    assert a != b


def test_two_ipv6_addresses_in_one_slash_64_share_a_key() -> None:
    a = client_key(scope(xff=["2001:db8:1:2::1"]), prod())
    b = client_key(scope(xff=["2001:db8:1:2:ffff:ffff:ffff:ffff"]), prod())

    assert a == b != "unknown"


def test_ipv6_in_different_slash_64_have_different_keys() -> None:
    a = client_key(scope(xff=["2001:db8:1:2::1"]), prod())
    b = client_key(scope(xff=["2001:db8:1:3::1"]), prod())

    assert a != b


def test_ipv6_spelling_does_not_change_the_key() -> None:
    a = client_key(scope(xff=["2001:DB8:1:2:0:0:0:1"]), prod())
    b = client_key(scope(xff=["2001:db8:1:2::1"]), prod())

    assert a == b


def test_ipv6_development_peer_is_keyed_by_slash_64() -> None:
    a = client_key(scope(peer="2001:db8:1:2::1"), dev())
    b = client_key(scope(peer="2001:db8:1:2::2"), dev())

    assert a == b != "unknown"


def test_ipv4_mapped_ipv6_has_the_ipv4_key() -> None:
    mapped = client_key(scope(xff=["::ffff:198.51.100.7"]), prod())
    plain = client_key(scope(xff=["198.51.100.7"]), prod())

    assert mapped == plain == "198.51.100.7"


def test_ipv4_mapped_hex_form_has_the_ipv4_key() -> None:
    mapped = client_key(scope(xff=["::ffff:c633:6407"]), prod())

    assert mapped == "198.51.100.7"


def test_different_ipv4_mapped_addresses_do_not_share_a_key() -> None:
    a = client_key(scope(xff=["::ffff:198.51.100.7"]), prod())
    b = client_key(scope(xff=["::ffff:198.51.100.8"]), prod())

    assert a != b
