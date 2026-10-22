"""S3-T6a review findings (PR #35), MAJOR: slot first with a body deadline, and DNS failure mapping.

1. ``POST /api/extract/google-doc`` takes the extraction slot BEFORE it reads the body.
   Under the slot the body read has the deadline ``settings.google_body_timeout_seconds`` and
   fails with ``408 {"error": "upload_timeout"}``, as ``/api/extract`` does. A busy server
   answers ``503 busy`` + ``Retry-After`` before any body byte is read, whatever the body is.
   The ``415`` media-type check (header only) may stay before the slot.
2. A resolver that raises ``socket.gaierror`` / ``OSError`` makes the guard raise an
   ``httpcore.ConnectError`` with no host name and no address in its message; the fetcher maps
   it to ``GoogleDocError("google_doc_unavailable")``; the endpoint answers
   ``502 {"error": "google_doc_unavailable"}``; no log record has the host name.
Must fail before the fix.
"""

from __future__ import annotations

import asyncio
import json
import socket
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpcore
import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.net.client import outbound_client
from app.net.google_docs import GoogleDocError, fetch_google_doc
from app.net.guard import GuardedNetworkBackend
from tests.asgi_stream import AsgiRun, chunks, drive, drive_receive, post_scope
from tests.helpers import all_log_text, new_marker
from tests.netfakes import SpyInner

PATH = "/api/extract/google-doc"
DOC_ID = "a1B2c3D4e5F6g7H8i9J0k1L2m3"
JSON_HEADERS = {"Content-Type": "application/json"}
HOST = "docs.google.com"
Message = dict[str, Any]


# --- helpers ----------------------------------------------------------------------------


def _json_scope(content_length: int = 1000) -> dict[str, Any]:
    return post_scope(PATH, content_type="application/json", content_length=content_length)


def _stall_after(first: bytes) -> Callable[[], Awaitable[Message]]:
    """Send ``first`` (more to come), then never send anything again."""
    delivered = False

    async def receive() -> Message:
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": first, "more_body": True}
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    return receive


def _timed(app: FastAPI, scope: dict[str, Any], receive: Any) -> tuple[AsgiRun, float]:
    start = time.monotonic()
    run = asyncio.run(drive_receive(app, scope, receive))
    return run, time.monotonic() - start


def _slot_free(app: FastAPI) -> bool:
    limiter = app.state.extraction_limiter
    if limiter.try_acquire():
        limiter.release()
        return True
    return False


def _take_all_slots(app: FastAPI) -> int:
    limiter = app.state.extraction_limiter
    taken = 0
    while limiter.try_acquire():
        taken += 1
        assert taken <= 1000, "limiter never runs out of slots"
    return taken


def _no_network(app: FastAPI) -> list[int]:
    """Make any outbound client creation visible: the list gets one item per call."""
    calls: list[int] = []

    def factory() -> httpx.AsyncClient:
        calls.append(1)
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500)))

    app.state.google_client_factory = factory
    return calls


# --- 1a. body deadline ------------------------------------------------------------------


def test_google_doc_stalled_body_returns_408_within_deadline(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app(google_body_timeout_seconds=1)
    calls = _no_network(app)

    run, elapsed = _timed(app, _json_scope(), _stall_after(b'{"document_id": "'))

    assert run.status == 408
    assert json.loads(run.body) == {"error": "upload_timeout"}
    assert 0.8 <= elapsed < 3.0, f"answered after {elapsed:.2f} s"
    assert calls == []


def test_google_doc_stalled_body_slot_free_after_408(make_app: Callable[..., FastAPI]) -> None:
    app = make_app(google_body_timeout_seconds=1, max_concurrent_extractions=1)
    _no_network(app)

    run, _ = _timed(app, _json_scope(), _stall_after(b'{"document_id": "'))

    assert run.status == 408
    assert _slot_free(app)


def test_google_doc_stalled_body_408_never_echoes_the_partial_input(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app(google_body_timeout_seconds=1)
    marker = new_marker("partial")

    run, _ = _timed(app, _json_scope(), _stall_after(f'{{"{marker}": "'.encode()))

    assert run.status == 408
    assert marker not in run.body.decode()
    assert marker not in str(run.headers)


def test_google_doc_stalled_body_holds_the_slot_while_it_is_read(
    make_app: Callable[..., FastAPI],
) -> None:
    """A stalled upload occupies the only slot; a second request gets 503, not a wait."""
    app = make_app(max_concurrent_extractions=1)
    _no_network(app)
    body = json.dumps({"document_id": DOC_ID}).encode()

    async def scenario() -> int | None:
        stalled = asyncio.Event()
        started = asyncio.Event()

        async def receive() -> Message:
            if not started.is_set():
                started.set()
                return {"type": "http.request", "body": b'{"document_id": "', "more_body": True}
            await stalled.wait()
            return {"type": "http.disconnect"}

        async def send(message: Message) -> None:
            return None

        first = asyncio.create_task(app(_json_scope(), receive, send))
        await asyncio.wait_for(started.wait(), 10)
        await asyncio.sleep(0.2)
        second = await drive(app, _json_scope(len(body)), chunks(body))
        stalled.set()
        await asyncio.wait_for(asyncio.gather(first, return_exceptions=True), 10)
        return second.status

    assert asyncio.run(scenario()) == 503


# --- 1b. busy slot wins over body validation ---------------------------------------------

INVALID_BODIES = [
    pytest.param(b"{", id="bad-json"),
    pytest.param(b"not json", id="not-json"),
    pytest.param(b"", id="empty"),
    pytest.param(b"[]", id="not-an-object"),
    pytest.param(b'{"document_id": "a1B2c3D4e5F6g7H8i9J0k1L2m3", "extra": 1}', id="extra-field"),
    pytest.param(b'{"document_id": "short"}', id="bad-id"),
    pytest.param(b'{"document_id": 5}', id="id-not-a-string"),
]


@pytest.mark.parametrize("body", INVALID_BODIES)
def test_google_doc_busy_with_invalid_body_returns_503_not_422(
    make_app: Callable[..., FastAPI], body: bytes
) -> None:
    app = make_app()
    calls = _no_network(app)
    client = TestClient(app, raise_server_exceptions=False)
    _take_all_slots(app)

    response = client.post(PATH, content=body, headers=JSON_HEADERS)

    assert response.status_code == 503
    assert response.json() == {"error": "busy"}
    assert response.headers.get("retry-after") == "5"
    assert calls == []


def test_google_doc_busy_is_answered_before_reading_the_body(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app(google_body_timeout_seconds=1)
    _take_all_slots(app)

    run, elapsed = _timed(app, _json_scope(), _stall_after(b'{"document_id": "'))

    assert run.status == 503
    assert json.loads(run.body) == {"error": "busy"}
    assert elapsed < 0.5, f"waited {elapsed:.2f} s for the body of a rejected request"


def test_google_doc_busy_with_body_in_flight_reads_no_body_before_the_response(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app()
    _take_all_slots(app)
    body = b'{"document_id": "short"}'

    from tests.asgi_stream import run_driven  # noqa: PLC0415 - used by one test only

    run = run_driven(app, _json_scope(len(body)), chunks(body))

    assert run.status == 503
    assert run.body_read_before_response() is False


@pytest.mark.parametrize("body", INVALID_BODIES)
def test_google_doc_busy_error_body_never_echoes_the_input(
    make_app: Callable[..., FastAPI], body: bytes
) -> None:
    app = make_app()
    marker = new_marker("echo")
    client = TestClient(app, raise_server_exceptions=False)
    _take_all_slots(app)

    response = client.post(PATH, content=body + marker.encode(), headers=JSON_HEADERS)

    assert response.status_code == 503
    assert marker not in response.text
    assert marker not in str(dict(response.headers))


def test_google_doc_invalid_body_with_free_slot_still_422_and_frees_the_slot(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app(max_concurrent_extractions=1)
    calls = _no_network(app)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(PATH, content=b"{", headers=JSON_HEADERS)

    assert response.status_code == 422
    assert response.json() == {"error": "invalid_request"}
    assert calls == []
    assert _slot_free(app)


# --- 2. DNS failure mapping --------------------------------------------------------------


def _failing_resolver(error: OSError) -> Callable[[str, int], Awaitable[list[str]]]:
    async def resolver(host: str, port: int) -> list[str]:
        raise error

    return resolver


def _dns_errors() -> list[OSError]:
    return [
        socket.gaierror(socket.EAI_NONAME, f"Name or service not known: {HOST} 203.0.113.7"),
        socket.gaierror(socket.EAI_AGAIN, f"Temporary failure resolving {HOST}"),
        OSError(f"resolver exploded for {HOST} 203.0.113.7"),
    ]


def _connect(error: OSError) -> tuple[SpyInner, BaseException | None]:
    inner = SpyInner()
    backend = GuardedNetworkBackend(resolver=_failing_resolver(error), inner=inner)
    caught: BaseException | None = None
    try:
        asyncio.run(backend.connect_tcp(HOST, 443, timeout=5))
    except BaseException as exc:  # noqa: BLE001 - the test inspects the type itself
        caught = exc
    return inner, caught


@pytest.mark.parametrize(
    "error", _dns_errors(), ids=["gaierror-noname", "gaierror-again", "oserror"]
)
def test_guard_resolver_oserror_raises_httpcore_connect_error(error: OSError) -> None:
    inner, caught = _connect(error)

    assert isinstance(caught, httpcore.ConnectError), repr(caught)
    assert not isinstance(caught, socket.gaierror)
    assert inner.connects == []


@pytest.mark.parametrize(
    "error", _dns_errors(), ids=["gaierror-noname", "gaierror-again", "oserror"]
)
def test_guard_resolver_oserror_message_has_no_host_and_no_address(error: OSError) -> None:
    _, caught = _connect(error)

    assert isinstance(caught, httpcore.ConnectError), repr(caught)
    text = f"{caught!s} {caught!r}"
    assert HOST not in text
    assert "google" not in text
    assert "203.0.113.7" not in text


@pytest.mark.parametrize(
    "error", _dns_errors(), ids=["gaierror-noname", "gaierror-again", "oserror"]
)
def test_fetch_google_doc_dns_failure_is_google_doc_unavailable(error: OSError) -> None:
    def factory() -> httpx.AsyncClient:
        backend = GuardedNetworkBackend(resolver=_failing_resolver(error), inner=SpyInner())
        return outbound_client(connect_timeout=5, read_timeout=10, network_backend=backend)

    async def go() -> GoogleDocError:
        try:
            await fetch_google_doc(
                DOC_ID, max_bytes=1000, timeout_seconds=5, client_factory=factory
            )
        except GoogleDocError as exc:
            return exc
        msg = "a result is not expected"
        raise AssertionError(msg)

    result = asyncio.run(go())

    assert result.code == "google_doc_unavailable"
    assert HOST not in str(result)
    assert DOC_ID not in str(result)


@pytest.mark.parametrize(
    "error", _dns_errors(), ids=["gaierror-noname", "gaierror-again", "oserror"]
)
def test_google_doc_endpoint_dns_failure_502_unavailable_and_no_host_in_logs(
    make_app: Callable[..., FastAPI], caplog: pytest.LogCaptureFixture, error: OSError
) -> None:
    import logging  # noqa: PLC0415 - used by one test only

    app = make_app(max_concurrent_extractions=1)

    def factory() -> httpx.AsyncClient:
        backend = GuardedNetworkBackend(resolver=_failing_resolver(error), inner=SpyInner())
        return outbound_client(connect_timeout=5, read_timeout=10, network_backend=backend)

    app.state.google_client_factory = factory
    client = TestClient(app, raise_server_exceptions=False)
    caplog.set_level(logging.DEBUG)

    response = client.post(PATH, json={"document_id": DOC_ID})

    assert response.status_code == 502
    assert response.json() == {"error": "google_doc_unavailable"}
    assert HOST not in response.text
    assert DOC_ID not in response.text
    logs = all_log_text(caplog)
    assert HOST not in logs
    assert "203.0.113.7" not in logs
    assert DOC_ID not in logs
    assert _slot_free(app)
