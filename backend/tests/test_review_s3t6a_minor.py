"""S3-T6a review findings (PR #35), MINOR and NIT: shared helpers, typed client factory,
``sni_hostname`` extension, ``SSLKEYLOGFILE`` and the timeout mapping."""

from __future__ import annotations

import ast
import asyncio
import pathlib
import ssl
import time
import typing
from collections.abc import Callable
from typing import Any

import httpcore2
import httpx2
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import common, extract, google_doc
from app.net.client import ClientFactory, outbound_client
from app.net.google_docs import GoogleDocError, fetch_google_doc
from app.net.guard import BlockedHostError, GuardedNetworkBackend
from app.settings import Settings
from tests.asgi_stream import post_scope
from tests.netfakes import PUBLIC_V4, ResolverSpy, SpyInner, StreamingTransport

DOC_ID = "a1B2c3D4e5F6g7H8i9J0k1L2m3"
APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"


def _request(app: FastAPI) -> Request:
    return Request({"type": "http", "app": app, "headers": []})


def _client(inner: SpyInner) -> httpx2.AsyncClient:
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


def test_fetch_google_doc_client_factory_is_annotated_with_the_alias() -> None:
    hints = typing.get_type_hints(fetch_google_doc)

    assert hints["client_factory"] == ClientFactory
    assert typing.get_args(ClientFactory) == ([], httpx2.AsyncClient)


def test_the_alias_matches_what_outbound_client_returns() -> None:
    def factory() -> httpx2.AsyncClient:
        return _client(SpyInner())

    typed: ClientFactory = factory

    async def go() -> None:
        async with typed() as client:
            assert isinstance(client, httpx2.AsyncClient)

    asyncio.run(go())


def test_google_client_factory_returns_the_factory_of_the_app(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app()

    def factory() -> httpx2.AsyncClient:
        return httpx2.AsyncClient()

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
            assert isinstance(client, httpx2.AsyncClient)

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

    class Recording(httpcore2.AsyncConnectionPool):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            contexts.append(kwargs["ssl_context"])
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpcore2, "AsyncConnectionPool", Recording)

    _client(SpyInner())

    assert len(contexts) == 1
    assert contexts[0].keylog_filename is None


# --- 8. every httpx2 timeout is google_doc_timeout -------------------------------------------


def _fetch_raising(error: Exception) -> str:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise error

    async def go() -> str:
        try:
            await fetch_google_doc(
                DOC_ID,
                max_bytes=1000,
                timeout_seconds=5,
                client_factory=lambda: httpx2.AsyncClient(transport=StreamingTransport(handler)),
            )
        except GoogleDocError as exc:
            return exc.code
        return "result"

    return asyncio.run(go())


@pytest.mark.parametrize(
    "error",
    [httpx2.ConnectTimeout, httpx2.ReadTimeout, httpx2.WriteTimeout, httpx2.PoolTimeout],
)
def test_every_httpx_timeout_is_google_doc_timeout(error: type[httpx2.TimeoutException]) -> None:
    assert _fetch_raising(error("t")) == "google_doc_timeout"


@pytest.mark.parametrize("error", [httpx2.ConnectError, httpx2.ReadError, httpx2.WriteError])
def test_other_network_errors_are_google_doc_unavailable(
    error: type[httpx2.TransportError],
) -> None:
    assert _fetch_raising(error("t")) == "google_doc_unavailable"


def test_settings_type_is_used_by_the_app_state(make_app: Callable[..., FastAPI]) -> None:
    app = make_app()
    settings, _ = common.app_state(_request(app))

    assert isinstance(settings, Settings)


# --- GOOGLE_BODY_TIMEOUT_SECONDS and the 415 header -------------------------------------------


def test_google_body_timeout_default_is_5_seconds() -> None:
    assert Settings().google_body_timeout_seconds == 5


def test_google_body_timeout_is_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOOGLE_BODY_TIMEOUT_SECONDS", "2.5")

    assert Settings().google_body_timeout_seconds == 2.5


@pytest.mark.parametrize("value", ["0", "-1", "abc", "", "nan", "inf"])
def test_google_body_timeout_invalid_value_is_refused_without_echo(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("GOOGLE_BODY_TIMEOUT_SECONDS", value)

    with pytest.raises(ValidationError) as info:
        Settings()

    if value:
        assert f"'{value}'" not in str(info.value)


def test_google_body_deadline_is_not_the_extract_body_deadline(
    make_app: Callable[..., FastAPI],
) -> None:
    """The deadline is ``google_body_timeout_seconds``; the 60 s upload deadline is not used."""
    app = make_app(google_body_timeout_seconds=1, extract_body_timeout_seconds=60)
    stalled = asyncio.Event()

    async def receive() -> dict[str, Any]:
        await stalled.wait()
        return {"type": "http.disconnect"}

    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = post_scope(
        "/api/extract/google-doc", content_type="application/json", content_length=100
    )
    start = time.monotonic()
    asyncio.run(asyncio.wait_for(app(scope, receive, send), 10))

    assert time.monotonic() - start < 4
    assert sent[0]["status"] == 408


def test_google_doc_415_closes_the_connection(make_app: Callable[..., FastAPI]) -> None:
    client = TestClient(make_app(), raise_server_exceptions=False)

    response = client.post(
        "/api/extract/google-doc", content=b"{}", headers={"Content-Type": "text/plain"}
    )

    assert response.status_code == 415
    assert response.json() == {"error": "unsupported_media_type"}
    assert response.headers.get("connection") == "close"
