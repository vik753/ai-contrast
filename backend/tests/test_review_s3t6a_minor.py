"""S3-T6a review findings (PR #35), MINOR and NIT: shared helpers, typed client factory,
``sni_hostname`` extension, ``SSLKEYLOGFILE`` and the timeout mapping."""

from __future__ import annotations

import ast
import asyncio
import pathlib
import ssl
from collections.abc import Callable
from typing import Any

import httpcore
import httpx
import pytest
from fastapi import FastAPI, Request

from app.api import common, extract, google_doc
from app.net.client import ClientFactory, outbound_client
from app.net.google_docs import GoogleDocError, fetch_google_doc
from app.net.guard import BlockedHostError, GuardedNetworkBackend
from app.settings import Settings
from tests.netfakes import PUBLIC_V4, ResolverSpy, SpyInner, StreamingTransport

DOC_ID = "a1B2c3D4e5F6g7H8i9J0k1L2m3"
APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"


def _request(app: FastAPI) -> Request:
    return Request({"type": "http", "app": app, "headers": []})


def _client(inner: SpyInner) -> httpx.AsyncClient:
    backend = GuardedNetworkBackend(resolver=ResolverSpy([PUBLIC_V4]), inner=inner)
    return outbound_client(connect_timeout=5, read_timeout=10, network_backend=backend)


# --- 3. shared helpers in a public module --------------------------------------------------


def test_google_doc_endpoint_imports_nothing_private_from_the_extract_endpoint() -> None:
    tree = ast.parse((APP_DIR / "api" / "google_doc.py").read_text())

    imported = [
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    ]

    assert "app.api.extract" not in imported
    assert "app.api.common" in imported


@pytest.mark.parametrize(
    "name", ["_app_state", "_media_type", "_sandbox_limits", "_send_in_chunks", "_SlotResponse"]
)
def test_endpoint_modules_do_not_define_the_shared_helpers_again(name: str) -> None:
    assert not hasattr(extract, name)
    assert not hasattr(google_doc, name)


def test_common_helpers_follow_the_settings(make_app: Callable[..., FastAPI]) -> None:
    app = make_app(max_zip_entries=7, extract_worker_memory_mb=300)
    settings, limiter = common.app_state(_request(app))

    assert limiter is app.state.extraction_limiter
    assert common.zip_limits(settings).max_entries == 7
    assert common.sandbox_limits(settings).memory_bytes == 300 * 1024 * 1024


def test_common_app_state_rejects_an_app_that_is_not_configured() -> None:
    with pytest.raises(TypeError):
        common.app_state(_request(FastAPI()))


def test_common_media_type_ignores_parameters_and_case() -> None:
    assert common.media_type("Application/JSON; charset=utf-8") == "application/json"
    assert common.media_type(None) == ""


# --- 4. typed client factory ---------------------------------------------------------------


def test_client_factory_alias_is_a_callable_returning_an_async_client() -> None:
    assert ClientFactory == Callable[[], httpx.AsyncClient]


def test_google_client_factory_returns_the_factory_of_the_app(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app()

    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient()

    app.state.google_client_factory = factory

    assert common.google_client_factory(_request(app)) is factory


@pytest.mark.parametrize("value", [None, "factory", 5])
def test_google_client_factory_rejects_a_value_that_is_not_callable(
    make_app: Callable[..., FastAPI], value: Any
) -> None:
    app = make_app()
    app.state.google_client_factory = value

    with pytest.raises(TypeError):
        common.google_client_factory(_request(app))


def test_google_client_factory_rejects_an_app_without_one() -> None:
    with pytest.raises(TypeError):
        common.google_client_factory(_request(FastAPI()))


def test_the_default_factory_of_the_app_is_valid(make_app: Callable[..., FastAPI]) -> None:
    app = make_app(google_connect_timeout_seconds=3)

    factory = common.google_client_factory(_request(app))

    async def go() -> None:
        async with factory() as client:
            assert isinstance(client, httpx.AsyncClient)

    asyncio.run(go())


# --- 5. the sni_hostname extension ---------------------------------------------------------


def test_transport_refuses_the_sni_hostname_extension() -> None:
    inner = SpyInner()

    async def go() -> None:
        async with _client(inner) as client:
            await client.get(
                "https://docs.google.com/x", extensions={"sni_hostname": "evil.example"}
            )

    with pytest.raises(BlockedHostError) as info:
        asyncio.run(go())

    assert inner.connects == []
    assert "evil.example" not in str(info.value)


def test_transport_passes_the_other_extensions_on() -> None:
    inner = SpyInner()
    events: list[str] = []

    async def trace(name: str, info: dict[str, Any]) -> None:
        events.append(name)

    async def go() -> None:
        async with _client(inner) as client:
            await client.get("https://docs.google.com/x", extensions={"trace": trace})

    asyncio.run(go())

    assert inner.connects
    assert any(name.startswith("connection.") for name in events)


# --- 6. SSLKEYLOGFILE ----------------------------------------------------------------------


def test_ssl_context_ignores_sslkeylogfile(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    keylog = tmp_path / "keys.log"
    monkeypatch.setenv("SSLKEYLOGFILE", str(keylog))
    # The control: Python itself would take the file from the environment.
    assert ssl.create_default_context().keylog_filename == str(keylog)
    contexts: list[ssl.SSLContext] = []

    class Recording(httpcore.AsyncConnectionPool):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            contexts.append(kwargs["ssl_context"])
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpcore, "AsyncConnectionPool", Recording)

    _client(SpyInner())

    assert len(contexts) == 1
    assert contexts[0].keylog_filename is None


# --- 8. every httpx timeout is google_doc_timeout -------------------------------------------


def _fetch_raising(error: Exception) -> str:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    async def go() -> str:
        try:
            await fetch_google_doc(
                DOC_ID,
                max_bytes=1000,
                timeout_seconds=5,
                client_factory=lambda: httpx.AsyncClient(transport=StreamingTransport(handler)),
            )
        except GoogleDocError as exc:
            return exc.code
        return "result"

    return asyncio.run(go())


@pytest.mark.parametrize(
    "error",
    [httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout],
)
def test_every_httpx_timeout_is_google_doc_timeout(error: type[httpx.TimeoutException]) -> None:
    assert _fetch_raising(error("t")) == "google_doc_timeout"


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ReadError, httpx.WriteError])
def test_other_network_errors_are_google_doc_unavailable(error: type[httpx.TransportError]) -> None:
    assert _fetch_raising(error("t")) == "google_doc_unavailable"


def test_settings_type_is_used_by_the_app_state(make_app: Callable[..., FastAPI]) -> None:
    app = make_app()
    settings, _ = common.app_state(_request(app))

    assert isinstance(settings, Settings)
