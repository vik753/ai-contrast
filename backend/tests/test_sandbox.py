"""S3-T1 AC1, AC2, AC3, AC8, AC10: the parsing sandbox (ADR 0011; T4, T6).

``run_extraction`` starts one child process per file, the child limits itself
before it reads input, and the parent enforces the wall deadline and the
result cap. Every failure is an ``ExtractionError`` with a code; no child and
no zombie is left behind; child stderr never reaches a log.

Test-only hook (assumed contract, see the test report):

- ``run_extraction(data, kind, *, limits, test_hook: str | None = None)``.
  When ``test_hook`` is given, the parent adds
  ``AI_CONTRAST_WORKER_TEST_HOOK=<name>`` to the child's minimal environment.
  Nothing else sets it: the parent never copies its own environment, and the
  HTTP handler never passes ``test_hook``.
- The worker runs the hook **after** it has set its limits and read its input.
  Hooks: ``sleep`` (sleeps for an hour), ``burn_cpu`` (busy loop without end),
  ``allocate_memory`` (allocates and touches 1 GiB), ``huge_output`` (writes to
  stdout without end), ``exit_nonzero`` (exit status 3), ``kill_self``
  (SIGKILL to itself), ``write_file`` (writes the input bytes to
  ``ai-contrast-write-probe`` in its working directory, errors not caught),
  ``stderr_echo`` (writes the input bytes to stderr, then exits 1),
  ``stderr_flood`` (writes the input bytes to stderr until at least 4 MiB were
  written, then extracts normally), ``invalid_json`` (prints ``not json``,
  exits 0), ``invalid_schema`` (prints a JSON object with an unknown key,
  exits 0). An unknown hook name makes the worker exit non-zero.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest

from app.extraction.detect import FileKind
from app.extraction.model import ExtractionError, ExtractionResult
from app.extraction.sandbox import SandboxLimits, run_extraction
from app.extraction.text import extract_text_file
from tests import proc_probe
from tests.helpers import all_log_text, new_canary

MIB = 1024 * 1024
HOOK_ENV = "AI_CONTRAST_WORKER_TEST_HOOK"
WRITE_PROBE = Path("/tmp/ai-contrast-write-probe")  # noqa: S108 - the child's working directory (ADR 0011)
APP_DIR = Path(__file__).resolve().parents[1] / "app"

SAMPLE = (
    b"SERVICE AGREEMENT (synthetic test data)\n\n"
    b"1. The Provider delivers the services described in Annex 1.\n"
    b"2. The Client pays every invoice within 30 days.\n\n"
    b"Signed by Party A and Party B.\n"
)

# Generous margins: the suite may run on a loaded CI machine.
SLACK_SECONDS = 15.0

DEFAULT_LIMITS: dict[str, int] = {
    "memory_bytes": 192 * MIB,
    "cpu_seconds": 20,
    "wall_seconds": 30,
    "max_result_bytes": 4 * MIB,
}


def _limits(**overrides: int) -> SandboxLimits:
    return SandboxLimits(**{**DEFAULT_LIMITS, **overrides})


def _run(data: bytes, *, hook: str | None = None, **overrides: int) -> ExtractionResult:
    kwargs: dict[str, Any] = {"limits": _limits(**overrides)}
    if hook is not None:
        kwargs["test_hook"] = hook
    return asyncio.run(run_extraction(data, FileKind.TEXT, **kwargs))


def _fail(
    data: bytes, *, hook: str | None = None, **overrides: int
) -> tuple[ExtractionError, float]:
    start = time.monotonic()
    with pytest.raises(ExtractionError) as info:
        _run(data, hook=hook, **overrides)
    return info.value, time.monotonic() - start


@pytest.fixture
def no_leftovers() -> Any:
    """Fail the test if a child process or zombie outlives the call."""
    before = set(proc_probe.descendants())
    yield
    left = proc_probe.wait_until_no_leftovers(before)
    assert left == {}, f"child processes left behind (pid -> state): {left}"


# --- Normal extraction through the child ---------------------------------------------------


def test_run_extraction_text_returns_extraction_result() -> None:
    result = _run(SAMPLE)

    assert isinstance(result, ExtractionResult)
    assert result.kind == "text"
    assert result.bytes == len(SAMPLE)


def test_run_extraction_text_equals_pure_extraction() -> None:
    assert _run(SAMPLE) == extract_text_file(SAMPLE)


def test_run_extraction_success_leaves_no_child(no_leftovers: None) -> None:
    _run(SAMPLE)


def test_run_extraction_result_above_cap_fails() -> None:
    data = ("synthetic clause text " * 500).encode()  # result JSON well above 1,000 bytes

    error, _ = _fail(data, max_result_bytes=1000)

    assert error.code == "extraction_failed"


# --- Hostile children (AC2, AC8) --------------------------------------------------------------


def test_run_extraction_sleeping_child_times_out() -> None:
    error, elapsed = _fail(SAMPLE, hook="sleep", wall_seconds=2)

    assert error.code == "extraction_timeout"
    assert elapsed < 2 + SLACK_SECONDS, f"took {elapsed:.1f} s"


def test_run_extraction_cpu_burning_child_fails_on_cpu_limit() -> None:
    # The wall deadline (30 s) is far away: only the CPU limit (1 s) can stop it in time.
    error, elapsed = _fail(SAMPLE, hook="burn_cpu", cpu_seconds=1, wall_seconds=30)

    assert error.code == "extraction_failed"
    assert elapsed < 25, f"took {elapsed:.1f} s"


def test_run_extraction_memory_hungry_child_fails_on_memory_limit() -> None:
    error, _ = _fail(SAMPLE, hook="allocate_memory")

    assert error.code == "extraction_failed"


def test_run_extraction_endless_output_fails_at_result_cap() -> None:
    error, elapsed = _fail(SAMPLE, hook="huge_output", max_result_bytes=64 * 1024, wall_seconds=30)

    assert error.code == "extraction_failed"
    assert elapsed < 20, f"took {elapsed:.1f} s: the cap must stop it, not the deadline"


def test_run_extraction_non_zero_exit_fails() -> None:
    error, _ = _fail(SAMPLE, hook="exit_nonzero")

    assert error.code == "extraction_failed"


def test_run_extraction_child_killed_by_signal_fails() -> None:
    error, _ = _fail(SAMPLE, hook="kill_self")

    assert error.code == "extraction_failed"


def test_run_extraction_invalid_json_fails() -> None:
    error, _ = _fail(SAMPLE, hook="invalid_json")

    assert error.code == "extraction_failed"


def test_run_extraction_invalid_schema_fails() -> None:
    error, _ = _fail(SAMPLE, hook="invalid_schema")

    assert error.code == "extraction_failed"


def test_run_extraction_unknown_hook_fails() -> None:
    error, _ = _fail(SAMPLE, hook="no_such_hook")

    assert error.code == "extraction_failed"


@pytest.fixture
def clean_write_probe() -> Any:
    """Remove the ``write_file`` hook's probe file before and after the test."""
    WRITE_PROBE.unlink(missing_ok=True)
    yield
    WRITE_PROBE.unlink(missing_ok=True)


@pytest.mark.usefixtures("clean_write_probe")
def test_run_extraction_file_write_attempt_fails() -> None:
    marker = new_canary().encode()

    error, _ = _fail(SAMPLE + marker, hook="write_file")

    assert error.code == "extraction_failed"


@pytest.mark.usefixtures("clean_write_probe")
def test_run_extraction_file_write_attempt_writes_no_bytes() -> None:
    with pytest.raises(ExtractionError):
        _run(SAMPLE, hook="write_file")

    assert not WRITE_PROBE.exists() or WRITE_PROBE.stat().st_size == 0


def test_run_extraction_stderr_flood_is_drained_and_extraction_succeeds() -> None:
    start = time.monotonic()

    result = _run(SAMPLE, hook="stderr_flood")

    assert result == extract_text_file(SAMPLE)
    assert time.monotonic() - start < 20


HOSTILE: list[tuple[str, dict[str, int]]] = [
    ("sleep", {"wall_seconds": 2}),
    ("burn_cpu", {"cpu_seconds": 1}),
    ("allocate_memory", {}),
    ("huge_output", {"max_result_bytes": 64 * 1024}),
    ("exit_nonzero", {}),
    ("kill_self", {}),
    ("write_file", {}),
    ("stderr_echo", {}),
    ("invalid_json", {}),
    ("invalid_schema", {}),
]
HOSTILE_IDS = [name for name, _ in HOSTILE]


@pytest.mark.parametrize(("hook", "overrides"), HOSTILE, ids=HOSTILE_IDS)
def test_run_extraction_hostile_child_leaves_no_child_or_zombie(
    no_leftovers: None, hook: str, overrides: dict[str, int]
) -> None:
    with pytest.raises(ExtractionError):
        _run(SAMPLE, hook=hook, **overrides)


@pytest.mark.parametrize(("hook", "overrides"), HOSTILE, ids=HOSTILE_IDS)
def test_run_extraction_after_hostile_child_next_extraction_succeeds(
    hook: str, overrides: dict[str, int]
) -> None:
    with pytest.raises(ExtractionError):
        _run(SAMPLE, hook=hook, **overrides)

    assert _run(SAMPLE) == extract_text_file(SAMPLE)


@pytest.mark.parametrize(("hook", "overrides"), HOSTILE, ids=HOSTILE_IDS)
def test_run_extraction_error_never_contains_input(hook: str, overrides: dict[str, int]) -> None:
    canary = new_canary()

    error, _ = _fail(SAMPLE + canary.encode(), hook=hook, **overrides)

    for text in (str(error), repr(error), repr(error.args), repr(vars(error))):
        assert canary not in text


def test_run_extraction_cancelled_kills_child(no_leftovers: None) -> None:
    async def scenario() -> None:
        before = set(proc_probe.descendants())
        task = asyncio.create_task(
            run_extraction(SAMPLE, FileKind.TEXT, limits=_limits(), test_hook="sleep")
        )
        child = await proc_probe.wait_for_new_live_child(before)
        assert child is not None, "no child process was started"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())


# --- The child from the outside (AC1) ----------------------------------------------------


def _inspect_sleeping_child(
    data: bytes, limits: SandboxLimits
) -> tuple[dict[str, str], dict[str, str], list[str], str]:
    """Start a sleeping child, read its /proc entries, then kill it."""

    async def scenario() -> tuple[dict[str, str], dict[str, str], list[str], str]:
        before = set(proc_probe.descendants())
        task = asyncio.create_task(
            run_extraction(data, FileKind.TEXT, limits=limits, test_hook="sleep")
        )
        try:
            child = await proc_probe.wait_for_new_live_child(before)
            assert child is not None, "no child process was started"
            seen = (
                proc_probe.soft_limits(child),
                proc_probe.environ(child),
                proc_probe.cmdline(child),
                proc_probe.cwd(child),
            )
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return seen

    return asyncio.run(scenario())


def test_worker_child_sets_os_limits() -> None:
    limits = _limits(memory_bytes=200 * MIB, cpu_seconds=7)

    soft, _, _, _ = _inspect_sleeping_child(SAMPLE, limits)

    assert soft["Max address space"] == str(200 * MIB)
    assert soft["Max cpu time"] == "7"
    assert soft["Max file size"] == "0"
    assert soft["Max core file size"] == "0"
    assert soft["Max open files"] != "unlimited"
    assert int(soft["Max open files"]) <= 64


def test_worker_child_gets_minimal_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    marker = new_canary()
    monkeypatch.setenv("AI_CONTRAST_LEAK_PROBE", marker)

    _, env, _, _ = _inspect_sleeping_child(SAMPLE, _limits())

    assert "AI_CONTRAST_LEAK_PROBE" not in env
    assert all(marker not in value for value in env.values())


def test_worker_child_runs_python_isolated() -> None:
    _, _, args, _ = _inspect_sleeping_child(SAMPLE, _limits())

    assert "-I" in args


def test_worker_child_input_not_on_command_line() -> None:
    canary = new_canary()

    _, _, args, _ = _inspect_sleeping_child(SAMPLE + canary.encode(), _limits())

    assert all(canary not in arg for arg in args)


def test_worker_child_working_directory_is_tmp() -> None:
    _, _, _, directory = _inspect_sleeping_child(SAMPLE, _limits())

    assert directory == "/tmp"  # noqa: S108 - ADR 0011


# --- Logs (AC1, AC10) -------------------------------------------------------------------------


def test_run_extraction_child_stderr_not_logged(log_capture: pytest.LogCaptureFixture) -> None:
    canary = new_canary()

    with pytest.raises(ExtractionError):
        _run(SAMPLE + canary.encode(), hook="stderr_echo")

    assert canary not in all_log_text(log_capture)


def test_run_extraction_flooded_stderr_not_logged(log_capture: pytest.LogCaptureFixture) -> None:
    canary = new_canary()

    _run(SAMPLE + canary.encode(), hook="stderr_flood")

    assert canary not in all_log_text(log_capture)


@pytest.mark.parametrize(("hook", "overrides"), HOSTILE, ids=HOSTILE_IDS)
def test_run_extraction_hostile_child_input_not_logged(
    log_capture: pytest.LogCaptureFixture, hook: str, overrides: dict[str, int]
) -> None:
    canary = new_canary()

    with pytest.raises(ExtractionError):
        _run(SAMPLE + canary.encode(), hook=hook, **overrides)

    assert canary not in all_log_text(log_capture)


def test_run_extraction_success_text_not_logged(log_capture: pytest.LogCaptureFixture) -> None:
    canary = new_canary()

    _run(SAMPLE + canary.encode())

    assert canary not in all_log_text(log_capture)


# --- The test hook cannot be reached in production (AC8) ------------------------------------


def test_hook_variable_in_server_environment_is_not_inherited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(HOOK_ENV, "exit_nonzero")

    assert _run(SAMPLE) == extract_text_file(SAMPLE)


def test_hook_is_named_only_in_sandbox_and_worker() -> None:
    allowed = {APP_DIR / "extraction" / "sandbox.py", APP_DIR / "extraction" / "worker.py"}
    offenders = [
        str(path.relative_to(APP_DIR))
        for path in APP_DIR.rglob("*.py")
        if path not in allowed and ("test_hook" in path.read_text() or HOOK_ENV in path.read_text())
    ]

    assert offenders == []
