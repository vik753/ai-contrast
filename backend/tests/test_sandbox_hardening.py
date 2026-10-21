"""S3-T1 review round 1 (PR #20): sandbox hardening (developer tests).

``RLIMIT_NPROC`` = 0 in the child, a failed child start, the bootstrap path.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest

from app.extraction import sandbox
from app.extraction.detect import FileKind
from app.extraction.model import ExtractionError
from app.extraction.sandbox import SandboxLimits, run_extraction
from app.extraction.text import extract_text_file
from tests import proc_probe
from tests.helpers import all_log_text, new_canary

MIB = 1024 * 1024
SAMPLE = b"SERVICE AGREEMENT (synthetic test data)\n\nThe Client pays within 30 days.\n"
LIMITS = SandboxLimits(
    memory_bytes=192 * MIB, cpu_seconds=20, wall_seconds=30, max_result_bytes=4 * MIB
)


def test_worker_child_sets_nproc_to_zero() -> None:
    async def scenario() -> dict[str, str]:
        before = set(proc_probe.descendants())
        task = asyncio.create_task(
            run_extraction(SAMPLE, FileKind.TEXT, limits=LIMITS, test_hook="sleep")
        )
        try:
            child = await proc_probe.wait_for_new_live_child(before)
            assert child is not None
            return proc_probe.soft_limits(child)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    assert asyncio.run(scenario())["Max processes"] == "0"


@pytest.mark.skipif(os.geteuid() == 0, reason="root is not bound by RLIMIT_NPROC")
def test_worker_child_cannot_fork() -> None:
    # The `fork` hook exits non-zero if fork works, else extracts normally.
    result = asyncio.run(run_extraction(SAMPLE, FileKind.TEXT, limits=LIMITS, test_hook="fork"))

    assert result == extract_text_file(SAMPLE)


def test_child_start_failure_is_extraction_failed(
    monkeypatch: pytest.MonkeyPatch, log_capture: pytest.LogCaptureFixture
) -> None:
    canary = new_canary()

    async def fail(*args: Any, **kwargs: Any) -> Any:
        raise OSError(canary)

    monkeypatch.setattr(sandbox.asyncio, "create_subprocess_exec", fail)

    with pytest.raises(ExtractionError) as info:
        asyncio.run(run_extraction(SAMPLE, FileKind.TEXT, limits=LIMITS))

    assert info.value.code == "extraction_failed"
    assert info.value.__cause__ is None
    assert canary not in all_log_text(log_capture)
    assert all(record.exc_info is None for record in log_capture.records)
    assert any("outcome=extraction_failed" in r.getMessage() for r in log_capture.records)


def test_bootstrap_appends_app_root_to_sys_path() -> None:
    assert "sys.path.append(sys.argv.pop(1))" in sandbox._BOOTSTRAP
    assert "insert" not in sandbox._BOOTSTRAP
