"""S1-T1c AC2: the log scrubber survives bad records and never mutates them.

Call-site tests run in a subprocess with ``log_config.json`` applied, exactly
like ``uvicorn --log-config log_config.json``. In-process, pytest's own
capture handler fails a test on any badly formatted record, which would hide
the behavior of our filter.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers import new_canary

BACKEND_DIR = Path(__file__).resolve().parent.parent

# argv: <mode> <canary> <force_raise_exceptions: 0|1>
_SCENARIO = r"""
import json, logging, logging.config, sys
mode, canary, force_raise = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
with open("log_config.json", encoding="utf-8") as fh:
    logging.config.dictConfig(json.load(fh))
if force_raise:
    # Test the filter on its own, without the raiseExceptions safety net.
    logging.raiseExceptions = True
log = logging.getLogger("s1t1c.test")
try:
    if mode == "bad_args":
        log.error("bad args %s %s", canary)
    elif mode == "bad_args_exc_info":
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            log.error("bad args %s %s", canary, exc_info=True)
    elif mode == "asgi_newline":
        try:
            raise RuntimeError(canary)
        except RuntimeError:
            logging.getLogger("uvicorn.error").error(
                "Exception in ASGI application\n", exc_info=True
            )
    elif mode == "raise_exceptions":
        import app.logging_filters  # noqa: F401
        print("RAISE_EXCEPTIONS=" + str(logging.raiseExceptions))
    else:
        raise SystemExit("unknown mode")
except Exception as exc:  # the call site must never raise
    print("CALL_RAISED " + type(exc).__name__)
    raise SystemExit(3)
print("CALL_OK")
"""


def _run(
    mode: str, canary: str, *, force_raise_exceptions: bool = True
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONPATH"] = str(BACKEND_DIR)
    return subprocess.run(  # noqa: S603 - fixed interpreter and script
        [sys.executable, "-c", _SCENARIO, mode, canary, "1" if force_raise_exceptions else "0"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


BAD_ARGS_MODES = ["bad_args", "bad_args_exc_info"]


@pytest.mark.parametrize("mode", BAD_ARGS_MODES)
def test_scrubber_bad_format_args_call_site_does_not_raise(mode: str) -> None:
    result = _run(mode, new_canary())

    assert result.returncode == 0, result.stdout + result.stderr
    assert "CALL_OK" in result.stdout


@pytest.mark.parametrize("mode", BAD_ARGS_MODES)
def test_scrubber_bad_format_args_canary_not_written_to_stderr(mode: str) -> None:
    canary = new_canary()

    result = _run(mode, canary)

    assert canary not in result.stderr
    assert canary not in result.stdout


@pytest.mark.parametrize("mode", BAD_ARGS_MODES)
def test_scrubber_bad_format_args_no_logging_error_traceback(mode: str) -> None:
    result = _run(mode, new_canary())

    assert "--- Logging error ---" not in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("mode", BAD_ARGS_MODES)
def test_scrubber_bad_format_args_record_flags_log_format_error(mode: str) -> None:
    result = _run(mode, new_canary())

    lines = [line for line in result.stderr.splitlines() if "bad args" in line]
    assert len(lines) == 1, result.stderr
    assert " log_format_error=1" in lines[0]


@pytest.mark.parametrize("mode", BAD_ARGS_MODES)
def test_scrubber_bad_format_args_default_raise_exceptions_canary_not_written(
    mode: str,
) -> None:
    canary = new_canary()

    result = _run(mode, canary, force_raise_exceptions=False)

    assert result.returncode == 0, result.stdout + result.stderr
    assert canary not in result.stderr


def test_logging_raise_exceptions_false_after_importing_logging_filters() -> None:
    result = _run("raise_exceptions", new_canary(), force_raise_exceptions=False)

    assert "RAISE_EXCEPTIONS=False" in result.stdout, result.stdout + result.stderr


def test_scrubber_asgi_message_with_trailing_newline_formats_on_one_line() -> None:
    canary = new_canary()

    result = _run("asgi_newline", canary)

    assert result.stderr.count("\n") == 1, result.stderr
    assert "Exception in ASGI application exc_type=" in result.stderr
    assert canary not in result.stderr


# --------------------------------------------------------------------------
# In-process: the filter works on a copy of the record.
# --------------------------------------------------------------------------


def _record(msg: str, args: tuple[object, ...] | None, *, with_exc: bool) -> logging.LogRecord:
    exc_info = None
    if with_exc:
        try:
            raise RuntimeError(new_canary())  # noqa: TRY301
        except RuntimeError:
            exc_info = sys.exc_info()
    return logging.LogRecord(
        name="s1t1c.test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=exc_info,
        sinfo="Stack (most recent call last):\n  fake frame",
    )


def _filtered(record: logging.LogRecord) -> logging.LogRecord:
    from app.logging_filters import ExcInfoScrubber  # noqa: PLC0415

    result = ExcInfoScrubber().filter(record)
    assert isinstance(result, logging.LogRecord), "filter must return the scrubbed copy"
    return result


def test_scrubber_filter_returns_new_record_object() -> None:
    record = _record("boom", None, with_exc=True)

    assert _filtered(record) is not record


def test_scrubber_filter_does_not_mutate_original_record() -> None:
    record = _record("boom %s", ("value",), with_exc=True)
    before = (record.msg, record.args, record.exc_info, record.exc_text, record.stack_info)

    _filtered(record)

    after = (record.msg, record.args, record.exc_info, record.exc_text, record.stack_info)
    assert after == before


def test_scrubber_filter_bad_args_copy_uses_msg_and_flag() -> None:
    canary = new_canary()
    record = _record("bad args %s %s", (canary,), with_exc=False)

    result = _filtered(record)

    assert result.args is None
    message = result.getMessage()
    assert canary not in message
    assert message.startswith("bad args")
    assert " log_format_error=1" in message


def test_scrubber_filter_bad_args_original_record_keeps_args() -> None:
    canary = new_canary()
    record = _record("bad args %s %s", (canary,), with_exc=False)

    _filtered(record)

    assert record.args == (canary,)
    assert record.msg == "bad args %s %s"


def test_scrubber_filter_message_right_stripped_before_exc_type() -> None:
    record = _record("Exception in ASGI application\n  ", None, with_exc=True)

    message = _filtered(record).getMessage()

    assert message == "Exception in ASGI application exc_type=RuntimeError"
