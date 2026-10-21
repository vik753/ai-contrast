"""S2-T1 review round 1 (PR #15): hardening of ``POST /api/extract`` (T4, T6).

- Body deadline and minimum average rate → ``408 upload_timeout``.
- ``Connection: close`` on every response sent before the whole body is read.
- Any ``Transfer-Encoding`` → ``411``; a body length different from
  ``Content-Length`` → ``400 length_mismatch``.
- A ``Content-Length`` with more than 18 digits → ``413``, never ``500``.
- CORS exposes ``Retry-After``.
- The handler's own 413 paths work without ``BodySizeLimitMiddleware``.
- One ``http.response.start`` per response; clean access log line.
- Peak memory for a body in 1-byte chunks stays below 2.5x the body.
- ``ExtractionLimiter.slot()`` releases exactly once; ``release()`` without a
  held slot raises.
- ``app/http_limits.py`` exports ``EXTRACT_PATH`` and ``declared_length``.

Timing approach for the 408 tests: the grace period (5 s) is not a setting,
so the minimum-rate tests run in real time with a slow trickle (about 5-6 s
each). The deadline test uses ``EXTRACT_BODY_TIMEOUT_SECONDS=1`` and a body
that stalls after one byte. No clock is patched, so the tests do not depend
on which clock the implementation reads.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import re
import time
import tracemalloc
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.settings import Settings
from tests.asgi_stream import (
    AsgiRun,
    chunks,
    drive_receive,
    endless,
    post_scope,
    response_starts,
    run_driven,
)
from tests.helpers import ALLOWED_ORIGIN, access_lines

EXTRACT = "/api/extract"
ECHO = "/api/test/echo-size"
MIB = 1024 * 1024
TEXT = b"Synthetic contract text. Clause 1. Payment within 30 days.\n"
GRACE_SECONDS = 5.0

Message = dict[str, Any]


def _limiter_module() -> Any:
    return importlib.import_module("app.extraction.limiter")


def _slot_free(app: FastAPI) -> bool:
    limiter = app.state.extraction_limiter
    if limiter.try_acquire():
        limiter.release()
        return True
    return False


def _connection_close(run: AsgiRun) -> bool:
    return run.headers.get("connection", "").strip().lower() == "close"


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


def _trickle(chunk: bytes, *, interval: float, total: int) -> Callable[[], Awaitable[Message]]:
    """Send ``chunk`` every ``interval`` seconds until ``total`` bytes are sent."""
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


def _timed(app: FastAPI, scope: dict[str, Any], receive: Any) -> tuple[AsgiRun, float]:
    start = time.monotonic()
    run = asyncio.run(drive_receive(app, scope, receive))
    return run, time.monotonic() - start


# --- 1. Body deadline and minimum rate -------------------------------------------------


def test_extract_stalled_body_returns_408_within_deadline(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app(extract_body_timeout_seconds=1)

    run, elapsed = _timed(app, post_scope(EXTRACT, content_length=1000), _stall_after(b"a"))

    assert run.status == 408
    assert json.loads(run.body) == {"error": "upload_timeout"}
    assert 0.8 <= elapsed < 3.0, f"answered after {elapsed:.2f} s"


def test_extract_stalled_body_408_carries_connection_close(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app(extract_body_timeout_seconds=1)

    run, _ = _timed(app, post_scope(EXTRACT, content_length=1000), _stall_after(b"a"))

    assert run.status == 408
    assert _connection_close(run)


def test_extract_stalled_body_slot_free_after_408(make_app: Callable[..., FastAPI]) -> None:
    app = make_app(extract_body_timeout_seconds=1, max_concurrent_extractions=1)

    run, _ = _timed(app, post_scope(EXTRACT, content_length=1000), _stall_after(b"a"))

    assert run.status == 408
    assert _slot_free(app)


def test_extract_slow_body_below_min_rate_after_grace_returns_408(
    make_app: Callable[..., FastAPI],
) -> None:
    # About 400 B/s against a minimum of 1 MB/s: rejected once the grace ends.
    app = make_app(extract_min_rate_bytes_per_second=1_000_000)
    receive = _trickle(b"a" * 100, interval=0.25, total=1_000_000)

    run, elapsed = _timed(app, post_scope(EXTRACT, content_length=1_000_000), receive)

    assert run.status == 408
    assert json.loads(run.body) == {"error": "upload_timeout"}
    assert _connection_close(run)
    assert GRACE_SECONDS - 0.5 <= elapsed < GRACE_SECONDS + 3.0, f"after {elapsed:.2f} s"
    assert _slot_free(app)


def test_extract_slow_body_within_grace_period_accepted(
    make_app: Callable[..., FastAPI],
) -> None:
    # Far below the minimum rate, but complete before the grace period ends.
    app = make_app(extract_min_rate_bytes_per_second=1_000_000)
    receive = _trickle(b"a" * 100, interval=0.1, total=1000)

    run, _ = _timed(app, post_scope(EXTRACT, content_length=1000), receive)

    assert run.status == 200
    assert json.loads(run.body) == {"kind": "text", "bytes": 1000}


def test_extract_body_above_min_rate_after_grace_period_accepted(
    make_app: Callable[..., FastAPI],
) -> None:
    # About 4,000 B/s for about 6 s against a minimum of 1,000 B/s.
    app = make_app(extract_min_rate_bytes_per_second=1000)
    total = 24 * 1000
    receive = _trickle(b"a" * 1000, interval=0.25, total=total)

    run, elapsed = _timed(app, post_scope(EXTRACT, content_length=total), receive)

    assert elapsed > GRACE_SECONDS
    assert run.status == 200
    assert json.loads(run.body) == {"kind": "text", "bytes": total}


# --- 2. Connection: close on early responses --------------------------------------------


def _early_runs(make_app: Callable[..., FastAPI]) -> dict[str, AsgiRun]:
    def fresh(**settings: Any) -> FastAPI:
        return make_app(**settings)

    busy_app = fresh()
    while busy_app.state.extraction_limiter.try_acquire():
        pass
    return {
        "400-short": run_driven(
            fresh(), post_scope(EXTRACT, content_length=100), chunks(b"a" * 50)
        ),
        "400-long": run_driven(fresh(), post_scope(EXTRACT, content_length=10), chunks(b"a" * 50)),
        "411": run_driven(
            fresh(),
            post_scope(EXTRACT, extra_headers=[("transfer-encoding", "chunked")]),
            chunks(TEXT),
        ),
        "413-header": run_driven(
            fresh(max_file_bytes=100), post_scope(EXTRACT, content_length=101), chunks(b"a" * 101)
        ),
        "413-stream": run_driven(
            fresh(max_file_bytes=4096),
            post_scope(EXTRACT, content_length=4096),
            endless(b"a" * 1024, max_total=MIB),
        ),
        "415": run_driven(
            fresh(),
            post_scope(EXTRACT, content_type="text/plain", content_length=len(TEXT)),
            chunks(TEXT),
        ),
        "503": run_driven(busy_app, post_scope(EXTRACT, content_length=len(TEXT)), chunks(TEXT)),
    }


EARLY_STATUS = {
    "400-short": 400,
    "400-long": 400,
    "411": 411,
    "413-header": 413,
    "413-stream": 413,
    "415": 415,
    "503": 503,
}


@pytest.mark.parametrize("case", sorted(EARLY_STATUS))
def test_extract_early_response_carries_connection_close(
    make_app: Callable[..., FastAPI], case: str
) -> None:
    run = _early_runs(make_app)[case]

    assert run.status == EARLY_STATUS[case]
    assert _connection_close(run), run.headers


def test_extract_200_response_is_not_an_early_response(
    make_app: Callable[..., FastAPI],
) -> None:
    run = run_driven(make_app(), post_scope(EXTRACT, content_length=len(TEXT)), chunks(TEXT))

    assert run.status == 200


# --- 3. Transfer-Encoding ----------------------------------------------------------------


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param([("transfer-encoding", "chunked")], id="chunked-alone"),
        pytest.param([("transfer-encoding", "identity")], id="identity-alone"),
    ],
)
def test_extract_transfer_encoding_without_length_returns_411(
    make_app: Callable[..., FastAPI], headers: list[tuple[str, str]]
) -> None:
    run = run_driven(make_app(), post_scope(EXTRACT, extra_headers=headers), chunks(TEXT))

    assert run.status == 411
    assert json.loads(run.body) == {"error": "length_required"}
    assert run.body_read_before_response() is False


@pytest.mark.parametrize("encoding", ["chunked", "identity", "gzip, chunked"])
def test_extract_transfer_encoding_with_content_length_returns_411(
    make_app: Callable[..., FastAPI], encoding: str
) -> None:
    scope = post_scope(
        EXTRACT, content_length=len(TEXT), extra_headers=[("transfer-encoding", encoding)]
    )

    run = run_driven(make_app(), scope, chunks(TEXT))

    assert run.status == 411
    assert json.loads(run.body) == {"error": "length_required"}
    assert run.body_read_before_response() is False


@pytest.mark.parametrize("value", ["abc", "-5", "1.5", "0x10", "5 5", ""])
def test_extract_non_numeric_content_length_returns_411(
    make_app: Callable[..., FastAPI], value: str
) -> None:
    run = run_driven(make_app(), post_scope(EXTRACT, content_length=value), chunks(TEXT))

    assert run.status == 411
    assert json.loads(run.body) == {"error": "length_required"}


# --- 4. Length mismatch ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("declared", "parts"),
    [
        pytest.param(100, (b"a" * 50,), id="shorter"),
        pytest.param(100, (b"a" * 40, b"a" * 40), id="shorter-two-chunks"),
        pytest.param(5, (b"",), id="declared-but-empty"),
        pytest.param(10, (b"a" * 50,), id="longer"),
        pytest.param(10, (b"a" * 8, b"a" * 8), id="longer-two-chunks"),
    ],
)
def test_extract_body_length_differs_from_content_length_returns_400(
    make_app: Callable[..., FastAPI], declared: int, parts: tuple[bytes, ...]
) -> None:
    run = run_driven(make_app(), post_scope(EXTRACT, content_length=declared), chunks(*parts))

    assert run.status == 400
    assert json.loads(run.body) == {"error": "length_mismatch"}


def test_extract_length_mismatch_slot_free(make_app: Callable[..., FastAPI]) -> None:
    app = make_app(max_concurrent_extractions=1)

    run = run_driven(app, post_scope(EXTRACT, content_length=100), chunks(b"a" * 50))

    assert run.status == 400
    assert _slot_free(app)


# --- 5. Huge Content-Length -----------------------------------------------------------------


HUGE_LENGTHS = ["9" * 5000, "9" * 19, "1" + "0" * 18]


def _app_with_echo(make_app: Callable[..., FastAPI]) -> FastAPI:
    app = make_app()

    async def echo(request: Request) -> dict[str, int]:
        return {"size": len(await request.body())}

    app.add_api_route(ECHO, echo, methods=["POST"])
    return app


@pytest.mark.parametrize("value", HUGE_LENGTHS)
def test_extract_huge_content_length_digits_returns_413(
    make_app: Callable[..., FastAPI], value: str
) -> None:
    run = run_driven(make_app(), post_scope(EXTRACT, content_length=value), chunks(b"a"))

    assert run.status == 413
    assert json.loads(run.body) == {"error": "file_too_large"}


@pytest.mark.parametrize("value", HUGE_LENGTHS)
def test_json_route_huge_content_length_digits_returns_413(
    make_app: Callable[..., FastAPI], value: str
) -> None:
    scope = post_scope(ECHO, content_type="application/json", content_length=value)

    run = run_driven(_app_with_echo(make_app), scope, chunks(b"{}"))

    assert run.status == 413
    assert json.loads(run.body) == {"error": "request_too_large"}


@pytest.mark.parametrize("path", [EXTRACT, ECHO])
def test_huge_content_length_access_log_shows_413(
    make_app: Callable[..., FastAPI], log_capture: pytest.LogCaptureFixture, path: str
) -> None:
    app = _app_with_echo(make_app)
    log_capture.clear()

    run_driven(app, post_scope(path, content_length="9" * 5000), chunks(b"a"))

    lines = access_lines(log_capture, "POST", path)
    assert len(lines) == 1
    assert re.fullmatch(rf"POST {re.escape(path)} 413 duration_ms=\d+", lines[0]), lines[0]
    assert not any(r.name == "ai_contrast.errors" for r in log_capture.records)


# --- 6. CORS exposes Retry-After ------------------------------------------------------------


def test_extract_busy_to_allowed_origin_exposes_retry_after(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    app = make_app(allowed_origins=[ALLOWED_ORIGIN])
    while app.state.extraction_limiter.try_acquire():
        pass

    response = make_client(app).post(
        EXTRACT,
        content=TEXT,
        headers={"Content-Type": "application/octet-stream", "Origin": ALLOWED_ORIGIN},
    )

    assert response.status_code == 503
    assert response.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
    exposed = {
        part.strip().lower()
        for part in response.headers.get("access-control-expose-headers", "").split(",")
    }
    assert "retry-after" in exposed


# --- 7. The handler's own 413 paths, without BodySizeLimitMiddleware ----------------------


def _bare_app(**settings: Any) -> FastAPI:
    """Only the extract router: no middleware at all."""
    extract = importlib.import_module("app.api.extract")
    app = FastAPI()
    app.include_router(extract.router)
    resolved = Settings(**settings)
    app.state.settings = resolved
    app.state.extraction_limiter = _limiter_module().ExtractionLimiter(
        resolved.max_concurrent_extractions
    )
    return app


def test_handler_without_middleware_content_length_above_limit_returns_413() -> None:
    app = _bare_app(max_file_bytes=100, max_concurrent_extractions=1)

    run = run_driven(app, post_scope(EXTRACT, content_length=101), chunks(b"a" * 101))

    assert run.status == 413
    assert json.loads(run.body) == {"error": "file_too_large"}
    assert run.body_read_before_response() is False
    assert _slot_free(app)


def test_handler_without_middleware_streamed_body_above_limit_returns_413() -> None:
    app = _bare_app(max_file_bytes=4096, max_concurrent_extractions=1)

    run = run_driven(
        app, post_scope(EXTRACT, content_length=4096), endless(b"a" * 1024, max_total=10 * MIB)
    )

    assert run.status == 413
    assert json.loads(run.body) == {"error": "file_too_large"}
    assert run.body_bytes_delivered <= 4096 + 1024
    assert _slot_free(app)


def test_handler_without_middleware_accepts_body_at_limit() -> None:
    app = _bare_app(max_file_bytes=100)

    run = run_driven(app, post_scope(EXTRACT, content_length=100), chunks(b"a" * 100))

    assert run.status == 200


# --- 8. ASGI flow -----------------------------------------------------------------------


def test_extract_streamed_overflow_sends_one_response_start(
    make_app: Callable[..., FastAPI],
) -> None:
    run = run_driven(
        make_app(max_file_bytes=4096),
        post_scope(EXTRACT, content_length=4096),
        endless(b"a" * 1024, max_total=10 * MIB),
    )

    assert run.status == 413
    assert response_starts(run) == 1


@pytest.mark.parametrize(
    ("declared", "parts"),
    [
        pytest.param(101, (b"a" * 101,), id="by-header"),
        pytest.param(100, (b"a" * 60, b"a" * 60), id="by-stream"),
    ],
)
def test_extract_413_sends_one_response_start(
    make_app: Callable[..., FastAPI], declared: int, parts: tuple[bytes, ...]
) -> None:
    run = run_driven(
        make_app(max_file_bytes=100), post_scope(EXTRACT, content_length=declared), chunks(*parts)
    )

    assert run.status == 413
    assert response_starts(run) == 1


def test_extract_streamed_overflow_access_log_line_has_no_flags(
    make_app: Callable[..., FastAPI], log_capture: pytest.LogCaptureFixture
) -> None:
    app = make_app(max_file_bytes=4096)
    log_capture.clear()

    run_driven(app, post_scope(EXTRACT, content_length=4096), endless(b"a" * 1024, max_total=MIB))

    lines = access_lines(log_capture, "POST", EXTRACT)
    assert len(lines) == 1
    assert re.fullmatch(r"POST /api/extract 413 duration_ms=\d+", lines[0]), lines[0]


@pytest.mark.parametrize(
    ("declared", "parts"),
    [
        pytest.param(101, (b"a" * 101,), id="by-header"),
        pytest.param(100, (b"a" * 60, b"a" * 60), id="by-stream"),
    ],
)
def test_extract_413_with_origin_frees_slot(
    make_app: Callable[..., FastAPI], declared: int, parts: tuple[bytes, ...]
) -> None:
    app = make_app(
        allowed_origins=[ALLOWED_ORIGIN], max_file_bytes=100, max_concurrent_extractions=1
    )
    scope = post_scope(EXTRACT, content_length=declared, extra_headers=[("origin", ALLOWED_ORIGIN)])

    run = run_driven(app, scope, chunks(*parts))

    assert run.status == 413
    assert run.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
    assert _slot_free(app)


# --- 12. Memory ------------------------------------------------------------------------

MEMORY_BODY_BYTES = 512 * 1024
MEMORY_FACTOR = 2.5


def test_extract_one_byte_chunks_peak_memory_below_two_and_a_half_times_body(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app()
    scope = post_scope(EXTRACT, content_length=MEMORY_BODY_BYTES)
    # Warm up: build the middleware stack and import everything first.
    run_driven(app, post_scope(EXTRACT, content_length=len(TEXT)), chunks(TEXT))

    remaining = MEMORY_BODY_BYTES
    status: list[int] = []

    async def receive() -> Message:
        nonlocal remaining
        if remaining == 0:
            await asyncio.Event().wait()
        remaining -= 1
        return {"type": "http.request", "body": b"a", "more_body": remaining > 0}

    async def send(message: Message) -> None:
        if message["type"] == "http.response.start":
            status.append(int(message["status"]))

    tracemalloc.start()
    try:
        baseline, _ = tracemalloc.get_traced_memory()
        tracemalloc.reset_peak()
        asyncio.run(asyncio.wait_for(app(scope, receive, send), 120))
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert status == [200]
    growth = peak - baseline
    assert growth < MEMORY_FACTOR * MEMORY_BODY_BYTES, (
        f"peak grew by {growth / MEMORY_BODY_BYTES:.2f}x the body"
    )


# --- 13. Limiter slot() --------------------------------------------------------------------
# Assumption: ``slot()`` takes a slot without waiting when it is entered and
# gives it back when it is left (the handler uses it instead of a bare
# ``try_acquire()`` / ``release()`` pair).


def _free_slots(limiter: Any) -> int:
    taken = 0
    while limiter.try_acquire():
        taken += 1
    for _ in range(taken):
        limiter.release()
    return taken


def test_limiter_slot_holds_one_slot_inside() -> None:
    limiter = _limiter_module().ExtractionLimiter(2)

    with limiter.slot():
        assert _free_slots(limiter) == 1

    assert _free_slots(limiter) == 2


def test_limiter_slot_releases_exactly_once() -> None:
    limiter = _limiter_module().ExtractionLimiter(2)
    assert limiter.try_acquire() is True  # someone else holds one slot

    with limiter.slot():
        pass

    assert _free_slots(limiter) == 1


def test_limiter_slot_released_on_exception() -> None:
    limiter = _limiter_module().ExtractionLimiter(1)

    with pytest.raises(LookupError), limiter.slot():
        raise LookupError

    assert _free_slots(limiter) == 1


def test_limiter_release_without_held_slot_raises() -> None:
    limiter = _limiter_module().ExtractionLimiter(2)

    with pytest.raises((RuntimeError, ValueError)):
        limiter.release()


def test_limiter_release_more_than_acquired_raises() -> None:
    limiter = _limiter_module().ExtractionLimiter(2)
    assert limiter.try_acquire() is True
    limiter.release()

    with pytest.raises((RuntimeError, ValueError)):
        limiter.release()
    assert _free_slots(limiter) == 2


# --- 15. Shared module ---------------------------------------------------------------------


def test_http_limits_exports_extract_path() -> None:
    module = importlib.import_module("app.http_limits")

    assert module.EXTRACT_PATH == "/api/extract"


def test_http_limits_exports_declared_length() -> None:
    module = importlib.import_module("app.http_limits")

    assert callable(module.declared_length)
