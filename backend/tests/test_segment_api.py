# ruff: noqa: PLC0415, TRY003
"""S5-T1 AC5, AC4: ``POST /api/segment`` request handling (T3, T5, T6).

Content type, body limit, slot, body deadline, request validation, strict JSON
parsing in the child, ``Cache-Control: no-store``, and "never echo input".
Hostile bodies are sent at ASGI level with ``tests/asgi_stream.py``.
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

from tests.asgi_stream import (
    AsgiRun,
    chunks,
    drive_receive,
    endless,
    post_scope,
    run_driven,
)
from tests.helpers import new_marker
from tests.segment_helpers import (
    JSON_HEADERS,
    SEGMENT,
    block,
    body_bytes,
    contract_problems,
    cover_problems,
    post_blocks,
    post_raw,
)

JSON_TYPE = "application/json"
OK_BLOCKS = [block("1. Payment is due within 30 days."), block("2. Either party may terminate.")]
OK_BODY = body_bytes(OK_BLOCKS)
Message = dict[str, Any]


def _close(run: AsgiRun) -> bool:
    return run.headers.get("connection", "").strip().lower() == "close"


def _take_all_slots(app: FastAPI) -> int:
    taken = 0
    while app.state.extraction_limiter.try_acquire():
        taken += 1
        assert taken < 1000
    return taken


def _slot_free(app: FastAPI) -> bool:
    limiter = app.state.extraction_limiter
    if limiter.try_acquire():
        limiter.release()
        return True
    return False


def _json_run(app: FastAPI, body: bytes, **scope: Any) -> AsgiRun:
    return run_driven(
        app,
        post_scope(SEGMENT, content_type=JSON_TYPE, content_length=len(body), **scope),
        chunks(body),
    )


# --- 200 -----------------------------------------------------------------------------


def test_segment_valid_request_returns_200_with_contract(
    make_client: Callable[..., TestClient],
) -> None:
    response = post_blocks(make_client(), OK_BLOCKS)

    assert response.status_code == 200
    assert contract_problems(response.json()) == []
    assert cover_problems(response.json()) == []
    assert [c["number"] for c in response.json()["clauses"]] == ["1", "2"]


def test_segment_content_type_with_charset_is_accepted(
    make_client: Callable[..., TestClient],
) -> None:
    response = make_client().post(
        SEGMENT, content=OK_BODY, headers={"Content-Type": "application/json; charset=utf-8"}
    )

    assert response.status_code == 200


def test_segment_content_type_is_case_insensitive(
    make_client: Callable[..., TestClient],
) -> None:
    response = make_client().post(
        SEGMENT, content=OK_BODY, headers={"Content-Type": "Application/JSON"}
    )

    assert response.status_code == 200


def test_segment_200_carries_cache_control_no_store(
    make_client: Callable[..., TestClient],
) -> None:
    response = post_blocks(make_client(), OK_BLOCKS)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


def test_segment_slot_free_after_success(make_app: Callable[..., FastAPI]) -> None:
    app = make_app(max_concurrent_extractions=1)

    run = _json_run(app, OK_BODY)

    assert run.status == 200
    assert _slot_free(app)


def test_segment_slot_free_after_422(make_app: Callable[..., FastAPI]) -> None:
    app = make_app(max_concurrent_extractions=1)

    run = _json_run(app, b'{"blocks": 5}')

    assert run.status == 422
    assert _slot_free(app)


# --- 415 / 413 / 411 / 503 -------------------------------------------------------------


@pytest.mark.parametrize(
    "content_type",
    ["text/plain", "application/octet-stream", "application/jsonx", "multipart/form-data", ""],
)
def test_segment_other_content_type_returns_415(
    make_client: Callable[..., TestClient], content_type: str
) -> None:
    response = make_client().post(SEGMENT, content=OK_BODY, headers={"Content-Type": content_type})

    assert response.status_code == 415
    assert response.json() == {"error": "unsupported_media_type"}


def test_segment_415_is_answered_before_taking_the_slot(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app()
    _take_all_slots(app)

    run = run_driven(
        app,
        post_scope(SEGMENT, content_type="text/plain", content_length=len(OK_BODY)),
        chunks(OK_BODY),
    )

    assert run.status == 415
    assert run.body_read_before_response() is False


def test_segment_body_above_segment_limit_returns_413(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app(segment_max_body_bytes=1000)

    run = _json_run(app, b" " * 1001)

    assert run.status == 413
    assert json.loads(run.body) == {"error": "request_too_large"}


def test_segment_huge_content_length_returns_413_without_reading(
    make_app: Callable[..., FastAPI],
) -> None:
    run = run_driven(
        make_app(),
        post_scope(SEGMENT, content_type=JSON_TYPE, content_length=10**18),
        chunks(b"{"),
    )

    assert run.status == 413
    assert json.loads(run.body) == {"error": "request_too_large"}


def test_segment_streamed_body_above_limit_returns_413_and_stops_reading(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app(segment_max_body_bytes=4096)
    scope = post_scope(SEGMENT, content_type=JSON_TYPE, content_length=4096)

    run = run_driven(app, scope, endless(b"a" * 1024, max_total=10 * 1024 * 1024))

    assert run.status == 413
    assert run.body_bytes_delivered <= 4096 + 1024


def test_segment_default_limit_is_4_mib(make_app: Callable[..., FastAPI]) -> None:
    mib4 = 4 * 1024 * 1024
    app = make_app()
    base = body_bytes([block("1. Synthetic clause.")])
    at_limit = base[:-1] + b" " * (mib4 - len(base)) + base[-1:]
    over = at_limit + b" "

    ok = _json_run(app, at_limit)
    too_big = _json_run(app, over)

    assert len(at_limit) == mib4
    assert ok.status == 200
    assert too_big.status == 413
    assert json.loads(too_big.body) == {"error": "request_too_large"}


def test_segment_body_exactly_at_limit_is_not_413(make_app: Callable[..., FastAPI]) -> None:
    pad = 100
    base = body_bytes([block("1. Synthetic clause.")])
    body = base[:-1] + b" " * pad + base[-1:]  # JSON white space before the final brace
    app = make_app(segment_max_body_bytes=len(body))

    run = _json_run(app, body)

    assert run.status == 200


def test_segment_limit_does_not_apply_to_extract(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client(segment_max_body_bytes=100)

    response = client.post(
        "/api/extract",
        content=b"Synthetic contract text. " * 20,
        headers={"Content-Type": "application/octet-stream"},
    )

    assert response.status_code == 200


def test_segment_ignores_the_small_json_body_limit_of_other_routes(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client(max_json_body_bytes=100)

    response = post_blocks(client, [block("1. " + "Synthetic clause text. " * 20)])

    assert response.status_code == 200


def test_segment_chunked_body_returns_411(make_client: Callable[..., TestClient]) -> None:
    response = make_client().post(
        SEGMENT, content=iter([b'{"blocks":', b"[]}"]), headers=JSON_HEADERS
    )

    assert response.status_code == 411
    assert response.json() == {"error": "length_required"}


def test_segment_transfer_encoding_header_returns_411(
    make_app: Callable[..., FastAPI],
) -> None:
    run = run_driven(
        make_app(),
        post_scope(
            SEGMENT,
            content_type=JSON_TYPE,
            content_length=len(OK_BODY),
            extra_headers=[("transfer-encoding", "chunked")],
        ),
        chunks(OK_BODY),
    )

    assert run.status == 411
    assert run.body_read_before_response() is False


def test_segment_all_slots_taken_returns_503_busy_with_retry_after(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    app = make_app()
    client = make_client(app)
    _take_all_slots(app)

    response = client.post(SEGMENT, content=OK_BODY, headers=JSON_HEADERS)

    assert response.status_code == 503
    assert response.json() == {"error": "busy"}
    assert response.headers.get("retry-after") == "5"


def test_segment_busy_is_answered_before_reading_the_body(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app()
    _take_all_slots(app)

    run = _json_run(app, OK_BODY)

    assert run.status == 503
    assert run.body_read_before_response() is False


def test_segment_and_extract_share_the_same_slots(make_app: Callable[..., FastAPI]) -> None:
    app = make_app(max_concurrent_extractions=1)
    assert app.state.extraction_limiter.try_acquire()

    run = _json_run(app, OK_BODY)

    assert run.status == 503


def _early_runs(make_app: Callable[..., FastAPI]) -> dict[str, tuple[AsgiRun, int]]:
    busy = make_app()
    _take_all_slots(busy)
    return {
        "411": (
            run_driven(
                make_app(),
                post_scope(
                    SEGMENT,
                    content_type=JSON_TYPE,
                    extra_headers=[("transfer-encoding", "chunked")],
                ),
                chunks(OK_BODY),
            ),
            411,
        ),
        "413-header": (
            _json_run(make_app(segment_max_body_bytes=100), b" " * 101),
            413,
        ),
        "413-stream": (
            run_driven(
                make_app(segment_max_body_bytes=4096),
                post_scope(SEGMENT, content_type=JSON_TYPE, content_length=4096),
                endless(b"a" * 1024, max_total=1024 * 1024),
            ),
            413,
        ),
        "415": (
            run_driven(
                make_app(),
                post_scope(SEGMENT, content_type="text/plain", content_length=len(OK_BODY)),
                chunks(OK_BODY),
            ),
            415,
        ),
        "503": (_json_run(busy, OK_BODY), 503),
    }


@pytest.mark.parametrize("case", ["411", "413-header", "413-stream", "415", "503"])
def test_segment_early_error_carries_connection_close(
    make_app: Callable[..., FastAPI], case: str
) -> None:
    run, status = _early_runs(make_app)[case]

    assert run.status == status
    assert _close(run), run.headers


@pytest.mark.parametrize("case", ["411", "413-header", "413-stream", "415", "503"])
def test_segment_early_error_carries_cache_control_no_store(
    make_app: Callable[..., FastAPI], case: str
) -> None:
    run, status = _early_runs(make_app)[case]

    assert run.status == status
    assert run.headers.get("cache-control") == "no-store", run.headers


def test_segment_200_is_not_an_early_response(make_app: Callable[..., FastAPI]) -> None:
    run = _json_run(make_app(), OK_BODY)

    assert run.status == 200
    assert not _close(run)


# --- 408 stalled body ------------------------------------------------------------------


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


def test_segment_stalled_body_returns_408_with_connection_close(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app(extract_body_timeout_seconds=1, max_concurrent_extractions=1)
    start = time.monotonic()

    run = asyncio.run(
        drive_receive(
            app,
            post_scope(SEGMENT, content_type=JSON_TYPE, content_length=1000),
            _stall_after(b'{"blocks":'),
        )
    )

    assert run.status == 408
    assert json.loads(run.body) == {"error": "upload_timeout"}
    assert _close(run)
    assert time.monotonic() - start < 4.0
    assert _slot_free(app)


def test_segment_slow_body_below_minimum_rate_returns_408(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app(extract_min_rate_bytes_per_second=1_000_000, extract_rate_grace_seconds=0.5)
    receive = _trickle(b" " * 100, interval=0.1, total=1_000_000)

    run = asyncio.run(
        drive_receive(
            app, post_scope(SEGMENT, content_type=JSON_TYPE, content_length=1_000_000), receive
        )
    )

    assert run.status == 408
    assert json.loads(run.body) == {"error": "upload_timeout"}
    assert _close(run)


def test_segment_body_split_in_many_chunks_is_read_completely(
    make_app: Callable[..., FastAPI],
) -> None:
    parts = [OK_BODY[i : i + 7] for i in range(0, len(OK_BODY), 7)]

    run = run_driven(
        make_app(),
        post_scope(SEGMENT, content_type=JSON_TYPE, content_length=len(OK_BODY)),
        chunks(*parts),
    )

    assert run.status == 200


# --- 422 request validation ---------------------------------------------------------------


def _blk(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"text": "1. Synthetic clause.", "part": "body", "page": None}
    base.update(changes)
    return base


def _invalid(*raw: Any) -> list[Any]:
    return [pytest.param(r, id=str(i)) for i, r in enumerate(raw)]


INVALID_REQUESTS = _invalid(
    b"",
    b"not json",
    b"[]",
    b"null",
    b'"blocks"',
    b"{}",
    b'{"blocks": null}',
    b'{"blocks": {}}',
    b'{"blocks": "text"}',
    b'{"blocks": [1]}',
    b'{"blocks": ["text"]}',
    b'{"blocks": [{"part": "body", "page": null}]}',
    b'{"blocks": [{"text": 5, "part": "body", "page": null}]}',
    b'{"blocks": [{"text": null, "part": "body", "page": null}]}',
    b'{"blocks": [{"text": "a", "part": "bogus", "page": null}]}',
    b'{"blocks": [{"text": "a", "part": "BODY", "page": null}]}',
    b'{"blocks": [{"text": "a", "part": 1, "page": null}]}',
    b'{"blocks": [{"text": "a", "part": "body", "page": "1"}]}',
    b'{"blocks": [{"text": "a", "part": "body", "page": 1.5}]}',
    b'{"blocks": [{"text": "a", "part": "body", "page": 0}]}',
    b'{"blocks": [{"text": "a", "part": "body", "page": -1}]}',
    b'{"blocks": [{"text": "a", "part": "body", "page": 99999999}]}',
    b'{"blocks": [{"text": "a", "part": "body", "page": null, "extra": 1}]}',
    b'{"blocks": [{"text": "a", "part": "body", "page": null}], "extra": 1}',
    b'{"blocks": [{"text": "a", "part": "body", "page": null}]} trailing',
    b'{"blocks": [{"text": "a", "part": "body", "page": null}]',
    b"\xff\xfe\x00",
    b'{"blocks": [{"text": "\xc3\x28", "part": "body", "page": null}]}',
)


@pytest.mark.parametrize("raw", INVALID_REQUESTS)
def test_segment_malformed_request_returns_422_invalid_request(
    make_client: Callable[..., TestClient], raw: bytes
) -> None:
    response = post_raw(make_client(), raw)

    assert response.status_code == 422
    assert response.json() == {"error": "invalid_request"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("page", [5])
def test_segment_page_at_max_pdf_pages_is_accepted(
    make_client: Callable[..., TestClient], page: int
) -> None:
    response = post_blocks(make_client(max_pdf_pages=5), [_blk(page=page)])

    assert response.status_code == 200


@pytest.mark.parametrize("page", [6, 0, -1])
def test_segment_page_outside_1_to_max_pdf_pages_returns_422(
    make_client: Callable[..., TestClient], page: int
) -> None:
    response = post_blocks(make_client(max_pdf_pages=5), [_blk(page=page)])

    assert response.status_code == 422
    assert response.json() == {"error": "invalid_request"}


@pytest.mark.parametrize("part", ["body", "footnote", "endnote", "header", "footer", "textbox"])
def test_segment_every_extract_part_is_accepted(
    make_client: Callable[..., TestClient], part: str
) -> None:
    response = post_blocks(make_client(), [_blk(part=part)])

    assert response.status_code == 200


def test_segment_empty_blocks_list_returns_422_no_text_extracted(
    make_client: Callable[..., TestClient],
) -> None:
    response = post_blocks(make_client(), [])

    assert response.status_code == 422
    assert response.json() == {"error": "no_text_extracted"}


@pytest.mark.parametrize("text", ["", "   ", "\n\t \n", "\u200b\u200b", "\x01\x02"])
def test_segment_text_without_visible_characters_returns_422_no_text_extracted(
    make_client: Callable[..., TestClient], text: str
) -> None:
    response = post_blocks(make_client(), [_blk(text=text), _blk(text=text)])

    assert response.status_code == 422
    assert response.json() == {"error": "no_text_extracted"}


def test_segment_blocks_above_max_blocks_return_422_too_much_text(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client(extract_max_blocks=3)

    over = post_blocks(client, [_blk(text=f"{n}. Clause.") for n in range(1, 5)])
    at_cap = post_blocks(client, [_blk(text=f"{n}. Clause.") for n in range(1, 4)])

    assert (over.status_code, over.json()) == (422, {"error": "too_much_text"})
    assert at_cap.status_code == 200


def test_segment_characters_above_max_text_chars_return_422_too_much_text(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client(extract_max_text_chars=20)

    over = post_blocks(client, [_blk(text="1. " + "a" * 9), _blk(text="b" * 9)])
    at_cap = post_blocks(client, [_blk(text="1. " + "a" * 9), _blk(text="b" * 8)])

    assert (over.status_code, over.json()) == (422, {"error": "too_much_text"})
    assert at_cap.status_code == 200


def test_segment_422_errors_never_echo_input(make_client: Callable[..., TestClient]) -> None:
    marker = new_marker("echo")
    client = make_client(max_pdf_pages=5, extract_max_blocks=2)
    bodies = [
        json.dumps({"blocks": [_blk(part=marker)]}).encode(),
        json.dumps({"blocks": [_blk(page=marker)]}).encode(),
        json.dumps({"blocks": [_blk(text=5, part=marker)]}).encode(),
        json.dumps({"blocks": [_blk()], marker: 1}).encode(),
        json.dumps({"blocks": [_blk(**{marker: 1})]}).encode(),
        json.dumps({"blocks": [_blk(text=marker)] * 3}).encode(),
        json.dumps({"blocks": [_blk(text=" ", part="body"), _blk(text=marker[:0])]}).encode(),
        b'{"blocks": [{"text": "' + marker.encode() + b'", "text": "x"}]}',
        b"not json " + marker.encode(),
        b'{"blocks": [' + marker.encode() + b"]}",
    ]
    for raw in bodies:
        response = post_raw(client, raw)
        assert response.status_code in (413, 422), response.status_code
        assert set(response.json()) == {"error"}
        assert marker not in response.text
        assert all(marker not in v for v in response.headers.values())


def test_segment_error_reply_is_exactly_the_error_object(
    make_client: Callable[..., TestClient],
) -> None:
    response = post_raw(make_client(), b'{"blocks": 1}')

    assert response.json() == {"error": "invalid_request"}
    assert response.headers["content-type"].startswith("application/json")


# --- AC4 strict parsing in the child --------------------------------------------------------


def test_segment_deeply_nested_json_returns_422_without_crash(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client()
    depth = 10_000
    nested_arrays = b"[" * depth + b"]" * depth
    nested_objects = b'{"a":' * depth + b"1" + b"}" * depth
    bodies = [
        nested_arrays,
        b'{"blocks":' + nested_arrays + b"}",
        b'{"blocks":[],"x":' + nested_arrays + b"}",
        b'{"blocks":[{"text":"a","part":"body","page":null,"x":' + nested_objects + b"}]}",
        b'{"blocks":[' * depth,
    ]

    for raw in bodies:
        response = post_raw(client, raw)
        assert response.status_code == 422, raw[:30]
        assert response.json() == {"error": "invalid_request"}
    assert post_blocks(client, OK_BLOCKS).status_code == 200  # server still healthy


@pytest.mark.parametrize(
    "raw",
    [
        b'{"blocks":[{"text":"a","text":"b","part":"body","page":null}]}',
        b'{"blocks":[{"text":"1. a","part":"body","part":"footer","page":null}]}',
        b'{"blocks":[{"text":"1. a","part":"body","page":null,"page":2}]}',
        b'{"blocks":[{"text":"1. a","part":"body","page":null}],"blocks":[]}',
        b'{"blocks":[],"blocks":[{"text":"1. a","part":"body","page":null}]}',
        b'{"\\u0062locks":[{"text":"1. a","part":"body","page":null}],"blocks":[]}',
    ],
)
def test_segment_duplicate_keys_return_422_invalid_request(
    make_client: Callable[..., TestClient], raw: bytes
) -> None:
    response = post_raw(make_client(), raw)

    assert response.status_code == 422
    assert response.json() == {"error": "invalid_request"}


def test_segment_lone_surrogate_is_rejected_or_removed_and_reported(
    make_client: Callable[..., TestClient],
) -> None:
    raw = b'{"blocks":[{"text":"1. Pay\\ud800ment is due.","part":"body","page":null}]}'

    response = post_raw(make_client(), raw)

    if response.status_code == 422:
        assert response.json() == {"error": "invalid_request"}
        return
    data = response.json()
    assert response.status_code == 200
    text = data["blocks"][0]["text"]
    assert "\ud800" not in text
    assert "Payment is due." in text.replace("\ud800", "")
    assert sum(r["count"] for r in data["removed"]) >= 1
    assert cover_problems(data) == []


@pytest.mark.parametrize("escaped", ["\\udc00", "\\ud83d", "\\ude00\\ud83d"])
def test_segment_other_lone_surrogates_never_reach_the_reply(
    make_client: Callable[..., TestClient], escaped: str
) -> None:
    raw = ('{"blocks":[{"text":"1. Pay' + escaped + 'ment.","part":"body","page":null}]}').encode()

    response = post_raw(make_client(), raw)

    assert response.status_code in (200, 422)
    reply_text = json.dumps(json.loads(response.content), ensure_ascii=False)
    assert all(not 0xD800 <= ord(ch) <= 0xDFFF for ch in reply_text)
    if response.status_code == 200:
        assert sum(r["count"] for r in response.json()["removed"]) >= 1


def test_segment_valid_surrogate_pair_escape_is_kept(
    make_client: Callable[..., TestClient],
) -> None:
    raw = b'{"blocks":[{"text":"1. Smile \\ud83d\\ude00 here.","part":"body","page":null}]}'

    response = post_raw(make_client(), raw)

    assert response.status_code == 200
    assert "\U0001f600" in response.json()["blocks"][0]["text"]


def test_segment_parent_does_not_parse_the_request_body(
    make_client: Callable[..., TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    import starlette.requests

    real_loads = json.loads

    def guarded_loads(s: Any, *args: Any, **kwargs: Any) -> Any:
        head = bytes(s[:12]) if isinstance(s, (bytes, bytearray)) else str(s[:12]).encode()
        if head.lstrip().startswith(b'{"blocks"'):
            raise AssertionError("request body parsed with json.loads in the parent")
        return real_loads(s, *args, **kwargs)

    async def no_json(self: Any) -> Any:
        raise AssertionError("Request.json() called")

    monkeypatch.setattr(json, "loads", guarded_loads)
    monkeypatch.setattr(starlette.requests.Request, "json", no_json)

    response = post_blocks(make_client(), OK_BLOCKS)

    assert response.status_code == 200


def test_segment_result_above_result_cap_returns_segment_failed(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client(extract_max_result_bytes=300)

    response = post_blocks(client, [block(f"{n}. Synthetic clause text.") for n in range(1, 40)])

    assert response.status_code in (422, 500)
    assert response.json() == {"error": "segment_failed"}


def test_segment_child_that_cannot_start_returns_segment_failed_and_frees_slot(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app(extract_worker_memory_mb=1, max_concurrent_extractions=1)

    run = _json_run(app, OK_BODY)

    assert run.status in (422, 500)
    assert json.loads(run.body) == {"error": "segment_failed"}
    assert _slot_free(app)
