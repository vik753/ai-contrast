"""S5-T1 AC4: the segmentation sandbox (worker kind ``segment``, test hooks, 504)."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.extraction.sandbox import APP_ROOT, SandboxLimits
from app.segment.runner import run_segmentation
from app.segment.segmenter import SegmentError, SegmentLimits
from tests.segment_helpers import block, body_bytes, post_blocks

MIB = 1024 * 1024
BODY = body_bytes([block("1. Payment is due."), block("2. Either party may end it.")])
LIMITS = SandboxLimits(
    memory_bytes=192 * MIB, cpu_seconds=20, wall_seconds=30, max_result_bytes=4 * MIB
)
SEGMENT_LIMITS = SegmentLimits(max_clauses=2000, max_clause_chars=20_000)


def _run(body: bytes = BODY, *, hook: str | None = None, **changes: int) -> Any:
    limits = SandboxLimits(**{**LIMITS.__dict__, **changes})
    return asyncio.run(
        run_segmentation(body, limits=limits, segment_limits=SEGMENT_LIMITS, hook=hook)
    )


def _code(hook: str, **changes: int) -> str:
    with pytest.raises(SegmentError) as info:
        _run(hook=hook, **changes)
    return info.value.code


def test_run_segmentation_returns_the_clauses() -> None:
    result = _run()

    assert [c.number for c in result.clauses] == ["1", "2"]


def test_run_segmentation_sleeping_child_times_out() -> None:
    start = time.monotonic()

    assert _code("sleep", wall_seconds=2) == "segment_timeout"
    assert time.monotonic() - start < 15


@pytest.mark.parametrize("hook", ["exit_nonzero", "kill_self", "invalid_json", "invalid_schema"])
def test_run_segmentation_broken_child_is_segment_failed(hook: str) -> None:
    assert _code(hook) == "segment_failed"


def test_run_segmentation_cpu_burning_child_is_segment_failed() -> None:
    assert _code("burn_cpu", cpu_seconds=1) == "segment_failed"


def test_segment_timeout_returns_504(
    make_client: Callable[..., TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def timing_out(*args: Any, **kwargs: Any) -> Any:
        raise SegmentError("segment_timeout")

    monkeypatch.setattr("app.api.segment.run_segmentation", timing_out)

    response = post_blocks(make_client(), [block("1. A.")])

    assert (response.status_code, response.json()) == (504, {"error": "segment_timeout"})


def _worker(header: dict[str, object], data: bytes) -> tuple[int, bytes]:
    code = (
        "import sys\nsys.path.append(sys.argv.pop(1))\n"
        "from app.extraction.worker import main\nmain()\n"
    )
    process = subprocess.run(  # noqa: S603 - fixed argv, test input only
        [sys.executable, "-I", "-B", "-c", code, APP_ROOT, str(192 * MIB), "20"],
        input=json.dumps(header).encode() + b"\n" + data,
        capture_output=True,
        check=False,
        timeout=60,
    )
    return process.returncode, process.stdout


def _header(data: bytes) -> dict[str, object]:
    return {
        "kind": "segment",
        "size": len(data),
        "max_text_chars": 1_000_000,
        "max_blocks": 20_000,
        "pdf_max_pages": 100,
        "segment_max_clauses": 2000,
        "segment_max_clause_chars": 20_000,
    }


def test_worker_segment_kind_replies_with_a_result() -> None:
    status, out = _worker(_header(BODY), BODY)

    assert status == 0
    assert [c["number"] for c in json.loads(out)["result"]["clauses"]] == ["1", "2"]


def test_worker_segment_kind_replies_with_an_error_code() -> None:
    data = b'{"blocks": 1}'

    status, out = _worker(_header(data), data)

    assert (status, json.loads(out)) == (0, {"error": "invalid_request"})


def test_worker_segment_kind_missing_cap_exits_non_zero() -> None:
    header = _header(BODY)
    del header["segment_max_clauses"]

    status, out = _worker(header, BODY)

    assert (status, out) == (1, b"")
