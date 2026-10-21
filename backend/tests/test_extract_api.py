"""S2-T1 AC1 and AC4: ``POST /api/extract`` follows the API contract table.

Request: raw bytes of one file, ``Content-Type: application/octet-stream`` and
``Content-Length``. Responses: 200, 411, 413, 415, 422, 503 with exact JSON
bodies (docs/agent/TASKS.md, Stage 2). Threats: T3, T4, T6.

Hostile body streams (a body longer than its ``Content-Length``, a client that
disconnects) are sent at the ASGI level with ``tests/asgi_stream.py``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.asgi_stream import (
    chunks,
    drive,
    endless,
    post_scope,
    run_driven,
    then_disconnect,
)
from tests.zipbuild import (
    ENGLISH_TEXT,
    OLE2_SAMPLE,
    PDF_SAMPLE,
    PNG_SAMPLE,
    RTF_SAMPLE,
    UKRAINIAN_TEXT,
    build_zip,
    docx_entries,
    minimal_docx,
    stored,
    zipfile_archive,
)

EXTRACT = "/api/extract"
OCTET = {"Content-Type": "application/octet-stream"}
MIB = 1024 * 1024
DEFAULT_MAX_FILE_BYTES = 10 * MIB

TEXT_BODY = ENGLISH_TEXT.encode("utf-8")


def _post(client: TestClient, body: Any, headers: dict[str, str] | None = None) -> Any:
    return client.post(EXTRACT, content=body, headers=OCTET if headers is None else headers)


# --- 200 ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "expected_kind"),
    [
        pytest.param(PDF_SAMPLE, "pdf", id="pdf"),
        pytest.param(minimal_docx(), "docx", id="docx"),
        pytest.param(TEXT_BODY, "text", id="text-english"),
        pytest.param(UKRAINIAN_TEXT.encode("cp1251"), "text", id="text-cp1251"),
        pytest.param(b"\xff\xfe" + UKRAINIAN_TEXT.encode("utf-16-le"), "text", id="utf16"),
    ],
)
def test_extract_accepted_file_returns_200_with_kind_and_bytes(
    make_client: Callable[..., TestClient], body: bytes, expected_kind: str
) -> None:
    response = _post(make_client(), body)

    assert response.status_code == 200
    assert response.json() == {"kind": expected_kind, "bytes": len(body)}


def test_extract_content_type_with_parameters_accepted(
    make_client: Callable[..., TestClient],
) -> None:
    response = _post(
        make_client(), TEXT_BODY, {"Content-Type": "application/octet-stream; charset=binary"}
    )

    assert response.status_code == 200


def test_extract_content_type_case_insensitive_accepted(
    make_client: Callable[..., TestClient],
) -> None:
    response = _post(make_client(), TEXT_BODY, {"Content-Type": "Application/Octet-Stream"})

    assert response.status_code == 200


def test_extract_body_exactly_at_default_limit_returns_200(
    make_client: Callable[..., TestClient],
) -> None:
    body = b"a" * DEFAULT_MAX_FILE_BYTES

    response = _post(make_client(), body)

    assert response.status_code == 200
    assert response.json() == {"kind": "text", "bytes": DEFAULT_MAX_FILE_BYTES}


def test_extract_body_at_configured_limit_returns_200(
    make_client: Callable[..., TestClient],
) -> None:
    response = _post(make_client(max_file_bytes=100), b"a" * 100)

    assert response.status_code == 200
    assert response.json() == {"kind": "text", "bytes": 100}


def test_extract_body_in_many_chunks_counts_all_bytes(make_app: Callable[..., FastAPI]) -> None:
    parts = [b"synthetic line\n"] * 50
    total = sum(len(p) for p in parts)

    run = run_driven(make_app(), post_scope(EXTRACT, content_length=total), chunks(*parts))

    assert run.status == 200
    assert json.loads(run.body) == {"kind": "text", "bytes": total}


# --- 411 ---------------------------------------------------------------------------


def test_extract_chunked_body_without_content_length_returns_411(
    make_client: Callable[..., TestClient],
) -> None:
    response = _post(make_client(), iter([b"synthetic ", b"text"]))

    assert response.status_code == 411
    assert response.json() == {"error": "length_required"}


def test_extract_without_content_length_returns_411_before_reading_body(
    make_app: Callable[..., FastAPI],
) -> None:
    scope = post_scope(EXTRACT, extra_headers=[("transfer-encoding", "chunked")])

    run = run_driven(make_app(), scope, chunks(b"synthetic text"))

    assert run.status == 411
    assert run.body_read_before_response() is False


# --- 413 ---------------------------------------------------------------------------


def test_extract_body_above_default_limit_returns_413(
    make_client: Callable[..., TestClient],
) -> None:
    response = _post(make_client(), b"a" * (DEFAULT_MAX_FILE_BYTES + 1))

    assert response.status_code == 413
    assert response.json() == {"error": "file_too_large"}


def test_extract_body_above_configured_limit_returns_413(
    make_client: Callable[..., TestClient],
) -> None:
    response = _post(make_client(max_file_bytes=100), b"a" * 101)

    assert response.status_code == 413
    assert response.json() == {"error": "file_too_large"}


def test_extract_content_length_above_limit_rejected_before_reading_body(
    make_app: Callable[..., FastAPI],
) -> None:
    scope = post_scope(EXTRACT, content_length=DEFAULT_MAX_FILE_BYTES + 1)

    run = run_driven(make_app(), scope, chunks(b"a" * 1024))

    assert run.status == 413
    assert json.loads(run.body) == {"error": "file_too_large"}
    assert run.body_read_before_response() is False


def test_extract_huge_content_length_returns_413(make_app: Callable[..., FastAPI]) -> None:
    scope = post_scope(EXTRACT, content_length=10**18)

    run = run_driven(make_app(), scope, chunks(b"a"))

    assert run.status == 413
    assert json.loads(run.body) == {"error": "file_too_large"}


def test_extract_body_longer_than_content_length_and_limit_returns_413(
    make_app: Callable[..., FastAPI],
) -> None:
    # Content-Length is exactly at the limit; the stream keeps coming. The body
    # grows above the limit, so 413 (not 400 length_mismatch, which is for a
    # wrong length under the cap).
    app = make_app(max_file_bytes=4096)
    scope = post_scope(EXTRACT, content_length=4096)

    run = run_driven(app, scope, endless(b"a" * 1024, max_total=10 * MIB))

    assert run.status == 413
    assert json.loads(run.body) == {"error": "file_too_large"}


def test_extract_body_above_limit_stops_reading(make_app: Callable[..., FastAPI]) -> None:
    app = make_app(max_file_bytes=4096)
    scope = post_scope(EXTRACT, content_length=4096)

    run = run_driven(app, scope, endless(b"a" * 1024, max_total=10 * MIB))

    # The limit plus at most one more chunk, never the whole stream.
    assert run.body_bytes_delivered <= 4096 + 1024


# --- 415 ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content_type",
    [
        "text/plain",
        "application/json",
        "application/pdf",
        "application/x-www-form-urlencoded",
        "multipart/form-data; boundary=synthetic",
        "application/octet-streamx",
        "application/octet",
        "",
    ],
)
def test_extract_other_content_type_returns_415(
    make_client: Callable[..., TestClient], content_type: str
) -> None:
    response = _post(make_client(), TEXT_BODY, {"Content-Type": content_type})

    assert response.status_code == 415
    assert response.json() == {"error": "unsupported_media_type"}


def test_extract_without_content_type_returns_415(
    make_client: Callable[..., TestClient],
) -> None:
    response = make_client().post(EXTRACT, content=TEXT_BODY)
    assert "content-type" not in {k.lower() for k in response.request.headers}

    assert response.status_code == 415
    assert response.json() == {"error": "unsupported_media_type"}


def test_extract_multipart_upload_returns_415(make_client: Callable[..., TestClient]) -> None:
    response = make_client().post(
        EXTRACT, files={"file": ("synthetic.txt", TEXT_BODY, "text/plain")}
    )

    assert response.status_code == 415
    assert response.json() == {"error": "unsupported_media_type"}


# --- 422 ---------------------------------------------------------------------------


def test_extract_empty_body_returns_422_empty_file(make_client: Callable[..., TestClient]) -> None:
    response = _post(make_client(), b"")

    assert response.status_code == 422
    assert response.json() == {"error": "empty_file"}


@pytest.mark.parametrize(
    ("body", "code"),
    [
        pytest.param(PNG_SAMPLE, "unsupported_type", id="png"),
        pytest.param(RTF_SAMPLE, "unsupported_type", id="rtf"),
        pytest.param(b"synthetic\x00binary", "unsupported_type", id="binary"),
        pytest.param(zipfile_archive([("readme.txt", b"synthetic")]), "unsupported_type", id="zip"),
        pytest.param(OLE2_SAMPLE, "legacy_office_unsupported", id="ole2"),
        pytest.param(
            build_zip([stored("Index/Document.iwa", b"synthetic")]),
            "pages_unsupported",
            id="pages",
        ),
        pytest.param(
            build_zip(docx_entries(), trailing=b"trailing"), "archive_rejected", id="archive"
        ),
    ],
)
def test_extract_rejected_file_returns_422_with_code(
    make_client: Callable[..., TestClient], body: bytes, code: str
) -> None:
    response = _post(make_client(), body)

    assert response.status_code == 422
    assert response.json() == {"error": code}


def test_extract_zip_limits_come_from_settings(make_client: Callable[..., TestClient]) -> None:
    body = build_zip(docx_entries(stored("word/a.xml"), stored("word/b.xml")))  # 5 entries

    response = _post(make_client(max_zip_entries=4), body)

    assert response.status_code == 422
    assert response.json() == {"error": "archive_rejected"}


def test_extract_zip_ratio_limit_comes_from_settings(
    make_client: Callable[..., TestClient],
) -> None:
    body = zipfile_archive([("[Content_Types].xml", b"a" * 5000), ("_rels/.rels", b"<r/>")])

    response = _post(make_client(max_zip_ratio=2), body)

    assert response.status_code == 422
    assert response.json() == {"error": "archive_rejected"}


def test_extract_zip_uncompressed_limit_comes_from_settings(
    make_client: Callable[..., TestClient],
) -> None:
    body = build_zip(docx_entries(stored("word/media/a.bin", b"a" * 2000)))

    response = _post(make_client(max_zip_uncompressed_bytes=1000), body)

    assert response.status_code == 422
    assert response.json() == {"error": "archive_rejected"}


# --- 503 and the limiter -------------------------------------------------------------


def _take_all_slots(app: FastAPI) -> int:
    limiter = app.state.extraction_limiter
    taken = 0
    while limiter.try_acquire():
        taken += 1
        assert taken <= 1000, "limiter never runs out of slots"
    return taken


def _release(app: FastAPI, count: int) -> None:
    for _ in range(count):
        app.state.extraction_limiter.release()


def test_extract_all_slots_taken_returns_503_busy(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    app = make_app()
    client = make_client(app)
    _take_all_slots(app)

    response = _post(client, TEXT_BODY)

    assert response.status_code == 503
    assert response.json() == {"error": "busy"}
    assert response.headers.get("retry-after") == "5"


def test_extract_busy_answered_before_reading_body(make_app: Callable[..., FastAPI]) -> None:
    app = make_app()
    _take_all_slots(app)

    run = run_driven(app, post_scope(EXTRACT, content_length=len(TEXT_BODY)), chunks(TEXT_BODY))

    assert run.status == 503
    assert run.body_read_before_response() is False


def test_extract_after_slots_released_returns_200(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    app = make_app()
    client = make_client(app)
    taken = _take_all_slots(app)
    assert _post(client, TEXT_BODY).status_code == 503

    _release(app, taken)

    assert _post(client, TEXT_BODY).status_code == 200


def test_extraction_limiter_default_has_two_slots(make_app: Callable[..., FastAPI]) -> None:
    assert _take_all_slots(make_app()) == 2


def test_extraction_limiter_slots_follow_settings(make_app: Callable[..., FastAPI]) -> None:
    assert _take_all_slots(make_app(max_concurrent_extractions=3)) == 3


def test_extraction_limiter_release_frees_one_slot(make_app: Callable[..., FastAPI]) -> None:
    app = make_app()
    limiter = app.state.extraction_limiter
    _take_all_slots(app)

    limiter.release()

    assert limiter.try_acquire() is True
    assert limiter.try_acquire() is False


def _slot_free(app: FastAPI) -> bool:
    """With one slot configured: True if it is free. Gives it back."""
    limiter = app.state.extraction_limiter
    if limiter.try_acquire():
        limiter.release()
        return True
    return False


def test_extract_slot_released_after_success(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    app = make_app(max_concurrent_extractions=1)
    client = make_client(app)

    first = _post(client, TEXT_BODY)
    second = _post(client, TEXT_BODY)

    assert (first.status_code, second.status_code) == (200, 200)
    assert _slot_free(app)


@pytest.mark.parametrize(
    ("body", "status"),
    [
        pytest.param(b"", 422, id="empty"),
        pytest.param(b"synthetic\x00binary", 422, id="unsupported"),
        # Under the 100-byte limit: a local header signature and no EOCD.
        pytest.param(b"PK\x03\x04" + b"x" * 20, 422, id="archive"),
        pytest.param(b"a" * 101, 413, id="too-large"),
    ],
)
def test_extract_slot_released_after_error(
    make_app: Callable[..., FastAPI],
    make_client: Callable[..., TestClient],
    body: bytes,
    status: int,
) -> None:
    app = make_app(max_concurrent_extractions=1, max_file_bytes=100)
    client = make_client(app)

    assert _post(client, body).status_code == status

    assert _slot_free(app)
    assert _post(client, b"synthetic").status_code == 200


def test_extract_slot_released_after_streamed_body_above_limit(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app(max_concurrent_extractions=1, max_file_bytes=4096)

    run = run_driven(
        app, post_scope(EXTRACT, content_length=4096), endless(b"a" * 1024, max_total=MIB)
    )

    assert run.status == 413
    assert _slot_free(app)


def test_extract_slot_released_after_client_disconnect(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app(max_concurrent_extractions=1)
    scope = post_scope(EXTRACT, content_length=1000)

    run = run_driven(app, scope, then_disconnect(b"a" * 100))

    assert run.status is None  # nobody to answer
    assert _slot_free(app)


def test_extract_slot_released_after_request_cancelled(
    make_app: Callable[..., FastAPI],
) -> None:
    """The server cancels the request task while the handler waits for body
    bytes (for example on shutdown or a timeout)."""
    app = make_app(max_concurrent_extractions=1)
    scope = post_scope(EXTRACT, content_length=1000)

    async def scenario() -> None:
        first_chunk_taken = asyncio.Event()
        stalled = asyncio.Event()
        delivered = False

        async def receive() -> dict[str, Any]:
            nonlocal delivered
            if not delivered:
                delivered = True
                first_chunk_taken.set()
                return {"type": "http.request", "body": b"a" * 100, "more_body": True}
            await stalled.wait()  # the rest of the body never arrives
            raise AssertionError("unreachable")

        async def send(message: dict[str, Any]) -> None:
            return None

        task = asyncio.create_task(app(scope, receive, send))
        await asyncio.wait_for(first_chunk_taken.wait(), 10)
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert _slot_free(app)


def test_extract_two_concurrent_requests_hold_both_slots(
    make_app: Callable[..., FastAPI],
) -> None:
    """Two uploads that wait for body bytes hold both slots; a third gets 503."""
    app = make_app()
    scope = post_scope(EXTRACT, content_length=1000)

    async def scenario() -> tuple[int | None, bool]:
        stalled = asyncio.Event()
        started = asyncio.Semaphore(0)

        def stalled_receive() -> Any:
            delivered = False

            async def receive() -> dict[str, Any]:
                nonlocal delivered
                if not delivered:
                    delivered = True
                    started.release()
                    return {"type": "http.request", "body": b"a" * 10, "more_body": True}
                await stalled.wait()
                return {"type": "http.disconnect"}

            return receive

        async def send(message: dict[str, Any]) -> None:
            return None

        tasks = [asyncio.create_task(app(scope, stalled_receive(), send)) for _ in range(2)]
        for _ in range(2):
            await asyncio.wait_for(started.acquire(), 10)
        third = await drive(app, scope, chunks(TEXT_BODY))
        stalled.set()
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 10)
        return third.status, _slot_free(app)

    third_status, free_after = asyncio.run(scenario())

    assert third_status == 503
    assert free_after is True


# --- Shape of every error response -----------------------------------------------------


def test_extract_error_responses_are_json(make_client: Callable[..., TestClient]) -> None:
    client = make_client(max_file_bytes=100)
    responses = [
        _post(client, b"a" * 101),
        _post(client, TEXT_BODY, {"Content-Type": "text/plain"}),
        _post(client, b""),
        _post(client, iter([b"a"])),
    ]

    for response in responses:
        assert response.headers["content-type"].startswith("application/json")
        assert set(response.json()) == {"error"}
