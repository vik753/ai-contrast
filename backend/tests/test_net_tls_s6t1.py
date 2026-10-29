"""S6-T1 item 2: the outbound TLS context is a plain certifi SSLContext (ADR 0016 point 1)."""

from __future__ import annotations

import ssl
from pathlib import Path
from typing import Any
from unittest.mock import patch

import certifi
import httpcore2
import httpx2
import pytest

from app.net.client import outbound_client
from app.net.guard import GuardedNetworkBackend
from tests.netfakes import PUBLIC_V4, ResolverSpy, SpyInner

PROXY_VARS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy")


def _build_recording(
    backend: GuardedNetworkBackend | None,
) -> tuple[httpx2.AsyncClient, dict[str, Any]]:
    """Build a client and capture the keyword arguments that reach the connection pool."""
    seen: list[dict[str, Any]] = []
    original = httpcore2.AsyncConnectionPool

    class Recording(original):  # type: ignore[valid-type, misc]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            seen.append(kwargs)
            super().__init__(*args, **kwargs)

    # `patch.object` restores the attribute even when the build fails.
    with patch.object(httpcore2, "AsyncConnectionPool", Recording):
        client = outbound_client(connect_timeout=5, read_timeout=10, network_backend=backend)
    assert len(seen) == 1
    return client, seen[0]


def _build() -> tuple[httpx2.AsyncClient, ssl.SSLContext]:
    backend = GuardedNetworkBackend(resolver=ResolverSpy([PUBLIC_V4]), inner=SpyInner())
    client, kwargs = _build_recording(backend)
    return client, kwargs["ssl_context"]


def _reference_ca_count() -> int:
    return ssl.create_default_context(cafile=certifi.where()).cert_store_stats()["x509_ca"]


def test_ssl_context_is_plain_ssl_context_not_truststore() -> None:
    _, context = _build()

    assert type(context) is ssl.SSLContext
    assert "truststore" not in type(context).__module__


def test_ssl_context_verifies_certificates_and_hostnames() -> None:
    _, context = _build()

    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_ssl_context_has_no_keylog_file() -> None:
    _, context = _build()

    assert context.keylog_filename is None


def test_ssl_context_trust_store_is_the_certifi_bundle() -> None:
    _, context = _build()

    assert context.cert_store_stats()["x509_ca"] == _reference_ca_count() > 0


def test_ssl_context_ignores_ssl_cert_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    empty = tmp_path / "empty.pem"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("SSL_CERT_FILE", str(empty))

    _, context = _build()

    assert context.cert_store_stats()["x509_ca"] == _reference_ca_count()


def test_ssl_context_ignores_ssl_cert_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path))

    _, context = _build()

    assert context.cert_store_stats()["x509_ca"] == _reference_ca_count()


def test_ssl_context_ignores_sslkeylogfile(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("SSLKEYLOGFILE", str(tmp_path / "keys.log"))

    _, context = _build()

    assert context.keylog_filename is None


@pytest.mark.parametrize("name", PROXY_VARS)
def test_client_has_no_proxy_mounts_when_proxy_variable_is_set(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv(name, "http://proxy.invalid:3128")

    client, _ = _build()

    assert client.trust_env is False
    # No public accessor for mounts exists in httpx2; this private check is deliberate.
    assert client._mounts == {}


def test_ssl_context_is_unchanged_when_all_variables_are_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, before = _build()
    for name in PROXY_VARS:
        monkeypatch.setenv(name, "http://proxy.invalid:3128")
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "missing.pem"))
    monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path))
    monkeypatch.setenv("SSLKEYLOGFILE", str(tmp_path / "keys.log"))

    _, after = _build()

    assert type(after) is type(before)
    assert after.cert_store_stats() == before.cert_store_stats()
    assert after.verify_mode == before.verify_mode
    assert after.check_hostname == before.check_hostname
    assert after.keylog_filename is None


def test_production_factory_uses_guarded_backend_and_certifi_context() -> None:
    _, kwargs = _build_recording(None)

    assert type(kwargs["network_backend"]) is GuardedNetworkBackend
    context = kwargs["ssl_context"]
    assert type(context) is ssl.SSLContext
    assert context.cert_store_stats()["x509_ca"] == _reference_ca_count() > 0
    assert context.verify_mode == ssl.CERT_REQUIRED
