"""S3-T6a items 6 and 2, logging part (threat model T1, T2 control 5, T7 control 6).

The ID is a password for the document. It must not appear in any log, response or error.
``httpx`` logs every request URL at INFO, so the canary goes through a REAL
``httpx.AsyncClient`` built by ``outbound_client`` with a guarded backend, a fake resolver
and a fake inner backend (the canned answer is HTTP 404). A control test proves that the
same stack does log the URL when the ``httpx`` logger is at INFO.

Uses plain ``caplog`` (not ``log_capture``): that fixture forces the ``httpx`` loggers to
WARNING, which would hide the very defect these tests look for.
Must fail before the implementation exists.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.net.client import outbound_client
from app.net.google_docs import GoogleDocError, fetch_google_doc
from app.net.guard import GuardedNetworkBackend
from tests.helpers import access_lines, all_log_text, new_canary
from tests.netfakes import PUBLIC_V4, ResolverSpy, SpyInner

PATH = "/api/extract/google-doc"
NET_LOGGERS = ("httpx", "httpcore")
LOG_CONFIG = Path(__file__).resolve().parent.parent / "log_config.json"


@pytest.fixture
def open_net_loggers() -> Iterator[None]:
    """Reset ``httpx``/``httpcore`` to NOTSET (inherit root) and restore afterwards."""
    saved = {name: logging.getLogger(name).level for name in NET_LOGGERS}
    for name in NET_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET)
    yield
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)


def guarded_client(inner: SpyInner | None = None) -> httpx.AsyncClient:
    backend = GuardedNetworkBackend(resolver=ResolverSpy([PUBLIC_V4]), inner=inner or SpyInner())
    return outbound_client(connect_timeout=5, read_timeout=10, network_backend=backend)


def fetch_with_real_client(document_id: str) -> GoogleDocError:
    async def go() -> GoogleDocError:
        try:
            await fetch_google_doc(
                document_id,
                max_bytes=1000,
                timeout_seconds=5,
                client_factory=guarded_client,
            )
        except GoogleDocError as error:
            return error
        msg = "the canned answer is 404, a result is not expected"
        raise AssertionError(msg)

    return asyncio.run(go())


def test_log_config_sets_httpx_and_httpcore_to_warning() -> None:
    loggers = json.loads(LOG_CONFIG.read_text(encoding="utf-8"))["loggers"]

    assert loggers["httpx"]["level"] == "WARNING"
    assert loggers["httpcore"]["level"] == "WARNING"


@pytest.mark.parametrize("name", NET_LOGGERS)
def test_app_start_sets_httpx_and_httpcore_loggers_to_warning(
    open_net_loggers: None, make_app: Callable[..., FastAPI], name: str
) -> None:
    assert logging.getLogger(name).level == logging.NOTSET

    make_app()

    assert logging.getLogger(name).level == logging.WARNING


def test_control_httpx_at_info_does_log_the_request_url(
    open_net_loggers: None, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    logging.getLogger("httpx").setLevel(logging.INFO)
    canary = new_canary()

    error = fetch_with_real_client(canary)

    assert error.code == "google_doc_not_found"
    assert canary in all_log_text(caplog), "the test setup must be able to see the httpx log"


def test_fetch_with_real_client_id_canary_absent_from_logs_after_app_start(
    open_net_loggers: None,
    make_app: Callable[..., FastAPI],
    caplog: pytest.LogCaptureFixture,
) -> None:
    make_app()  # application start sets the httpx and httpcore loggers
    caplog.set_level(logging.DEBUG)
    canary = new_canary()

    error = fetch_with_real_client(canary)

    assert error.code == "google_doc_not_found"
    assert canary not in all_log_text(caplog)
    assert canary not in str(error) + repr(error)


def test_endpoint_with_real_client_id_canary_absent_from_logs_and_response(
    open_net_loggers: None,
    make_app: Callable[..., FastAPI],
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = make_app()
    app.state.google_client_factory = guarded_client
    caplog.set_level(logging.DEBUG)
    canary = new_canary()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        PATH,
        json={"document_id": canary},
        headers={"X-Provider-Key": canary},
    )

    assert response.status_code == 422
    assert response.json() == {"error": "google_doc_not_found"}
    assert canary not in response.text
    assert canary not in str(dict(response.headers))
    assert canary not in all_log_text(caplog)
    assert "docs.google.com" not in all_log_text(caplog)
    assert PUBLIC_V4 not in all_log_text(caplog)


@pytest.mark.parametrize(
    "document_id", ["short", "{canary}/../x", "{canary}\n"], ids=["short", "path", "newline"]
)
def test_endpoint_invalid_id_canary_absent_from_logs_and_response(
    make_app: Callable[..., FastAPI],
    caplog: pytest.LogCaptureFixture,
    document_id: str,
) -> None:
    caplog.set_level(logging.DEBUG)
    canary = new_canary()
    client = TestClient(make_app(), raise_server_exceptions=False)

    response = client.post(PATH, json={"document_id": document_id.format(canary=canary)})

    assert response.status_code == 422
    assert canary not in response.text
    assert canary not in all_log_text(caplog)


def test_endpoint_access_log_has_method_path_status_only(
    open_net_loggers: None,
    make_app: Callable[..., FastAPI],
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = make_app()
    app.state.google_client_factory = guarded_client
    caplog.set_level(logging.DEBUG)
    canary = new_canary()

    TestClient(app, raise_server_exceptions=False).post(PATH, json={"document_id": canary})

    lines = access_lines(caplog, "POST", PATH)
    assert len(lines) == 1
    assert " 422 " in lines[0]
    assert canary not in lines[0]
