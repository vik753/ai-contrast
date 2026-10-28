"""S5b-T2 AC2: ``POST /api/safety-check`` transport rules, the same as ``/api/segment``.

Content type, body limit (4 MiB per path), slot before read, body deadline and
minimum rate, strict parsing, ``Cache-Control: no-store``, ``Connection: close``
on early errors, never echo text. Hostile bodies go in at ASGI level.

Expected to fail until ``/api/safety-check`` exists (S5b-T2 not implemented).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.asgi_stream import AsgiRun, chunks, drive_receive, endless, post_scope, run_driven
from tests.helpers import new_marker
from tests.safety_helpers import JSON_HEADERS, SAFETY, detector_version, doc, post_doc

JSON_TYPE = "application/json"
MIB = 1024 * 1024
Message = dict[str, Any]
Make = Callable[..., TestClient]


def _ok_body(client: TestClient) -> bytes:
    payload = doc(detector_version(client), "1. Payment is due within 30 days.")
    return json.dumps(payload).encode()


def _close(run: AsgiRun) -> bool:
    return run.headers.get("connection", "").strip().lower() == "close"


def _take_all_slots(app: FastAPI) -> None:
    taken = 0
    while app.state.extraction_limiter.try_acquire():
        taken += 1
        assert taken < 1000


def _slot_free(app: FastAPI) -> bool:
    limiter = app.state.extraction_limiter
    if limiter.try_acquire():
        limiter.release()
        return True
    return False


def _json_run(app: FastAPI, body: bytes) -> AsgiRun:
    return run_driven(
        app, post_scope(SAFETY, content_type=JSON_TYPE, content_length=len(body)), chunks(body)
    )


# --- 200 and response headers ----------------------------------------------------------


def test_safety_valid_request_returns_200_ok_with_version_and_digest(make_client: Make) -> None:
    client = make_client()
    version = detector_version(client)

    response = post_doc(client, doc(version, "1. Payment is due within 30 days."))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"ok", "detector_version", "digest"}
    assert body["ok"] is True
    assert body["detector_version"] == version
    assert len(body["digest"]) == 64
    assert int(body["digest"], 16) >= 0


def test_safety_200_carries_cache_control_no_store(make_client: Make) -> None:
    client = make_client()
    response = post_doc(client, doc(detector_version(client), "1. Payment is due."))

    assert response.headers.get("cache-control") == "no-store"


def test_safety_content_type_with_charset_is_accepted(make_client: Make) -> None:
    client = make_client()
    headers = {"Content-Type": "application/json; charset=utf-8"}

    response = client.post(SAFETY, content=_ok_body(client), headers=headers)

    assert response.status_code == 200


def test_safety_200_is_not_an_early_response(make_app: Callable[..., FastAPI]) -> None:
    app = make_app()
    body = _ok_body(TestClient(app))

    run = _json_run(app, body)

    assert run.status == 200
    assert not _close(run)


def test_safety_slot_free_after_success_and_after_422(make_app: Callable[..., FastAPI]) -> None:
    app = make_app()
    client = TestClient(app)
    version = detector_version(client)

    assert post_doc(client, doc(version, "1. Payment is due.")).status_code == 200
    assert _slot_free(app)
    assert post_doc(client, doc(version, "Pay [A.FOO_1].")).status_code == 422
    assert _slot_free(app)


# --- early errors ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content_type",
    ["text/plain", "application/octet-stream", "application/jsonx", "multipart/form-data", ""],
)
def test_safety_other_content_type_returns_415(make_client: Make, content_type: str) -> None:
    client = make_client()

    response = client.post(SAFETY, content=_ok_body(client), headers={"Content-Type": content_type})

    assert response.status_code == 415
    assert response.json() == {"error": "unsupported_media_type"}


def test_safety_415_is_answered_before_taking_the_slot(make_app: Callable[..., FastAPI]) -> None:
    app = make_app()
    body = _ok_body(TestClient(app))
    _take_all_slots(app)

    run = run_driven(
        app, post_scope(SAFETY, content_type="text/plain", content_length=len(body)), chunks(body)
    )

    assert run.status == 415
    assert run.body_read_before_response() is False


def test_safety_huge_content_length_returns_413_without_reading(
    make_app: Callable[..., FastAPI],
) -> None:
    run = run_driven(
        make_app(),
        post_scope(SAFETY, content_type=JSON_TYPE, content_length=10**18),
        chunks(b"{"),
    )

    assert run.status == 413
    assert json.loads(run.body) == {"error": "request_too_large"}


def test_safety_content_length_just_above_4_mib_returns_413(
    make_app: Callable[..., FastAPI],
) -> None:
    run = run_driven(
        make_app(),
        post_scope(SAFETY, content_type=JSON_TYPE, content_length=4 * MIB + 1),
        chunks(b"{"),
    )

    assert run.status == 413
    assert run.body_read_before_response() is False


def test_safety_streamed_body_above_4_mib_returns_413_and_stops_reading(
    make_app: Callable[..., FastAPI],
) -> None:
    scope = post_scope(SAFETY, content_type=JSON_TYPE, content_length=4 * MIB)

    run = run_driven(make_app(), scope, endless(b"a" * 65536, max_total=12 * MIB))

    assert run.status == 413


def test_safety_chunked_body_returns_411(make_app: Callable[..., FastAPI]) -> None:
    run = run_driven(
        make_app(),
        post_scope(
            SAFETY, content_type=JSON_TYPE, extra_headers=[("transfer-encoding", "chunked")]
        ),
        chunks(b"{}"),
    )

    assert run.status == 411


def test_safety_all_slots_taken_returns_503_busy_with_retry_after(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app()
    client = TestClient(app)
    body = _ok_body(client)
    _take_all_slots(app)

    response = client.post(SAFETY, content=body, headers=JSON_HEADERS)

    assert response.status_code == 503
    assert response.json() == {"error": "busy"}
    assert response.headers.get("retry-after") == "5"


def test_safety_busy_is_answered_before_reading_the_body(make_app: Callable[..., FastAPI]) -> None:
    app = make_app()
    body = _ok_body(TestClient(app))
    _take_all_slots(app)

    run = _json_run(app, body)

    assert run.status == 503
    assert run.body_read_before_response() is False


def test_safety_and_extract_share_the_same_slots(make_app: Callable[..., FastAPI]) -> None:
    app = make_app(max_concurrent_extractions=1)
    body = _ok_body(TestClient(app))
    assert app.state.extraction_limiter.try_acquire()

    run = _json_run(app, body)

    assert run.status == 503


def _early_runs(make_app: Callable[..., FastAPI]) -> dict[str, tuple[AsgiRun, int]]:
    busy = make_app()
    body = _ok_body(TestClient(busy))
    _take_all_slots(busy)
    return {
        "411": (
            run_driven(
                make_app(),
                post_scope(
                    SAFETY,
                    content_type=JSON_TYPE,
                    extra_headers=[("transfer-encoding", "chunked")],
                ),
                chunks(body),
            ),
            411,
        ),
        "413-header": (
            run_driven(
                make_app(),
                post_scope(SAFETY, content_type=JSON_TYPE, content_length=5 * MIB),
                chunks(b"{"),
            ),
            413,
        ),
        "413-stream": (
            run_driven(
                make_app(),
                post_scope(SAFETY, content_type=JSON_TYPE, content_length=4 * MIB),
                endless(b"a" * 65536, max_total=12 * MIB),
            ),
            413,
        ),
        "415": (
            run_driven(
                make_app(),
                post_scope(SAFETY, content_type="text/plain", content_length=len(body)),
                chunks(body),
            ),
            415,
        ),
        "503": (_json_run(busy, body), 503),
    }


@pytest.mark.parametrize("case", ["411", "413-header", "413-stream", "415", "503"])
def test_safety_early_error_carries_connection_close(
    make_app: Callable[..., FastAPI], case: str
) -> None:
    run, status = _early_runs(make_app)[case]

    assert run.status == status
    assert _close(run), run.headers


@pytest.mark.parametrize("case", ["411", "413-header", "413-stream", "415", "503"])
def test_safety_early_error_carries_cache_control_no_store(
    make_app: Callable[..., FastAPI], case: str
) -> None:
    run, status = _early_runs(make_app)[case]

    assert run.status == status
    assert run.headers.get("cache-control") == "no-store", run.headers


# --- 408 ----------------------------------------------------------------------------------


def _stall_after(first: bytes) -> Callable[[], Awaitable[Message]]:
    delivered = False

    async def receive() -> Message:
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": first, "more_body": True}
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    return receive


def _trickle(chunk: bytes, *, interval: float, total: int) -> Callable[[], Awaitable[Message]]:
    sent = 0

    async def receive() -> Message:
        nonlocal sent
        if sent >= total:
            await asyncio.Event().wait()
        await asyncio.sleep(interval)
        part = chunk[: total - sent]
        sent += len(part)
        return {"type": "http.request", "body": part, "more_body": sent < total}

    return receive


def test_safety_stalled_body_returns_408_with_connection_close(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app(extract_body_timeout_seconds=1, max_concurrent_extractions=1)
    start = time.monotonic()

    run = asyncio.run(
        drive_receive(
            app,
            post_scope(SAFETY, content_type=JSON_TYPE, content_length=1000),
            _stall_after(b'{"label":'),
        )
    )

    assert run.status == 408
    assert json.loads(run.body) == {"error": "upload_timeout"}
    assert _close(run)
    assert time.monotonic() - start < 4.0
    assert _slot_free(app)


def test_safety_slow_body_below_minimum_rate_returns_408(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app(extract_min_rate_bytes_per_second=1_000_000, extract_rate_grace_seconds=0.5)
    receive = _trickle(b" " * 100, interval=0.1, total=1_000_000)

    run = asyncio.run(
        drive_receive(
            app, post_scope(SAFETY, content_type=JSON_TYPE, content_length=1_000_000), receive
        )
    )

    assert run.status == 408
    assert json.loads(run.body) == {"error": "upload_timeout"}
    assert _close(run)


def test_safety_body_split_in_many_chunks_is_read_completely(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app()
    body = _ok_body(TestClient(app))
    parts = [body[i : i + 7] for i in range(0, len(body), 7)]

    run = run_driven(
        app,
        post_scope(SAFETY, content_type=JSON_TYPE, content_length=len(body)),
        chunks(*parts),
    )

    assert run.status == 200


# --- strict parsing and no echo -------------------------------------------------------------

_GOOD = {
    "label": "A",
    "detector_version": "V",
    "clauses": [{"id": "c1", "text": "Pay."}],
    "acknowledged_unmasked": [],
}


def _with(**changes: Any) -> bytes:
    return json.dumps({**_GOOD, **changes}).encode()


INVALID_REQUESTS = [
    b"",
    b"not json",
    b"[]",
    b"null",
    b'{"label": "A"',
    b"\xff\xfe\x00",
    json.dumps({**_GOOD, "extra": 1}).encode(),
    json.dumps({k: v for k, v in _GOOD.items() if k != "label"}).encode(),
    json.dumps({k: v for k, v in _GOOD.items() if k != "clauses"}).encode(),
    json.dumps({k: v for k, v in _GOOD.items() if k != "detector_version"}).encode(),
    _with(label="a"),
    _with(label="AB"),
    _with(label=""),
    _with(label=1),
    _with(clauses=[{"id": "c0", "text": "x"}]),
    _with(clauses=[{"id": "c01", "text": "x"}]),
    _with(clauses=[{"id": "x1", "text": "x"}]),
    _with(clauses=[{"id": "c10000", "text": "x"}]),
    _with(clauses=[{"id": "c1", "text": 5}]),
    _with(clauses=[{"id": "c1", "text": "x", "extra": 1}]),
    _with(clauses=[{"id": "c1"}]),
    _with(clauses="x"),
    _with(acknowledged_unmasked="x"),
    _with(acknowledged_unmasked=[["c1", 0]]),
    _with(acknowledged_unmasked=[["c1", "0", 1]]),
    _with(acknowledged_unmasked=[["c1", -1, 1]]),
    b'{"label": "A", "label": "B", "detector_version": "V", "clauses": [], '
    b'"acknowledged_unmasked": []}',
    b'{"label":"A","detector_version":"V","clauses":[{"id":"c1","text":"x"}],'
    b'"acknowledged_unmasked":[]} trailing',
]


@pytest.mark.parametrize("raw", INVALID_REQUESTS)
def test_safety_malformed_request_returns_422_invalid_request(
    make_client: Make, raw: bytes
) -> None:
    client = make_client()

    response = client.post(SAFETY, content=raw, headers=JSON_HEADERS)

    assert response.status_code == 422
    assert response.json() == {"error": "invalid_request"}


@pytest.mark.parametrize(
    "ack", [[["c1", 2, 1]], [["c9", 0, 1]]], ids=["end-before-start", "unknown-clause"]
)
def test_safety_bad_acknowledged_list_with_real_version_returns_422_invalid_request(
    make_client: Make, ack: list[list[object]]
) -> None:
    client = make_client()
    payload = doc(detector_version(client), "Pay.", ack=ack)

    response = post_doc(client, payload)

    assert (response.status_code, response.json()) == (422, {"error": "invalid_request"})


def test_safety_deeply_nested_json_returns_422_without_crash(make_client: Make) -> None:
    raw = b'{"label":"A","x":' + b"[" * 100_000 + b"]" * 100_000 + b"}"

    response = make_client().post(SAFETY, content=raw, headers=JSON_HEADERS)

    assert response.status_code == 422


def test_safety_422_errors_never_echo_input(make_client: Make) -> None:
    marker = new_marker("echo")
    client = make_client()
    version = detector_version(client)
    bodies = [
        _with(label=marker),
        _with(**{marker: 1}),
        _with(clauses=[{"id": marker, "text": marker}]),
        _with(clauses=[{"id": "c1", "text": marker, marker: 1}]),
        _with(detector_version=marker),
        json.dumps(doc(version, f"Pay [A.{marker}_1].")).encode(),
        json.dumps(doc(version, f"Pay \u200b{marker}.")).encode(),
        json.dumps(doc(version, f"Mail {marker}@example.com now.")).encode(),
        json.dumps(doc(version, "x", ack=[["c1", 0, 1], [marker, 0, 1]])).encode(),
        b"not json " + marker.encode(),
        b'{"label": "' + marker.encode() + b'", "label": "x"}',
    ]
    for raw in bodies:
        response = client.post(SAFETY, content=raw, headers=JSON_HEADERS)
        assert response.status_code in (409, 413, 422), response.status_code
        assert marker not in response.text
        assert marker.split("echo")[1] not in response.text
        assert all(marker not in v for v in response.headers.values())


def test_safety_error_reply_has_error_object_with_json_media_type(make_client: Make) -> None:
    response = make_client().post(SAFETY, content=b'{"label": 1}', headers=JSON_HEADERS)

    assert response.json() == {"error": "invalid_request"}
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers.get("cache-control") == "no-store"
