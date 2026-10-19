"""S1-T1b AC1: redaction filter on the stderr handler from log_config.json.

The filter ``app.logging_filters.ExcInfoScrubber`` removes exception
messages, tracebacks and stack info from every record of every logger
(including ``uvicorn.error``) and keeps only the exception type names (T1).
"""

from __future__ import annotations

import io
import json
import logging
import logging.config
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NoReturn

import pytest

from tests.helpers import new_canary

LOG_CONFIG_PATH = Path(__file__).resolve().parent.parent / "log_config.json"
SCRUBBER_CLASS_PATH = "app.logging_filters.ExcInfoScrubber"
WATCHED_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access", "ai_contrast")


class CanaryLeakError(RuntimeError):
    """Exception type with a distinctive name; its message carries a canary."""


def _raise(exc: BaseException) -> NoReturn:
    raise exc


def _exc_info(exc: BaseException) -> tuple[type[BaseException], BaseException, Any]:
    try:
        _raise(exc)
    except BaseException as caught:  # noqa: BLE001 - we need the traceback
        return type(caught), caught, caught.__traceback__


@pytest.fixture
def configured_stream() -> Iterator[io.StringIO]:
    """Apply log_config.json with dictConfig, point its ``stderr`` handler at
    a StringIO and restore the previous logging state afterwards."""
    root = logging.getLogger()
    saved_root = (root.level, list(root.handlers), list(root.filters))
    saved_loggers = {}
    for name in WATCHED_LOGGERS:
        lg = logging.getLogger(name)
        saved_loggers[name] = (lg.level, list(lg.handlers), lg.propagate, lg.disabled)
    saved_disabled = {
        name: lg.disabled
        for name, lg in logging.Logger.manager.loggerDict.items()
        if isinstance(lg, logging.Logger)
    }

    config = json.loads(LOG_CONFIG_PATH.read_text(encoding="utf-8"))
    logging.config.dictConfig(config)
    handler = logging.getHandlerByName("stderr")
    assert handler is not None, "log_config.json must define a handler named 'stderr'"
    assert isinstance(handler, logging.StreamHandler)
    stream = io.StringIO()
    handler.setStream(stream)
    try:
        yield stream
    finally:
        handler.setStream(sys.stderr)
        root.handlers.clear()
        handler.close()
        root.setLevel(saved_root[0])
        root.handlers.extend(saved_root[1])
        root.filters[:] = saved_root[2]
        for name, (level, handlers, propagate, disabled) in saved_loggers.items():
            lg = logging.getLogger(name)
            lg.setLevel(level)
            lg.handlers[:] = handlers
            lg.propagate = propagate
            lg.disabled = disabled
        for name, disabled in saved_disabled.items():
            existing = logging.Logger.manager.loggerDict.get(name)
            if isinstance(existing, logging.Logger):
                existing.disabled = disabled


def test_log_config_stderr_handler_has_exc_info_scrubber_filter() -> None:
    config = json.loads(LOG_CONFIG_PATH.read_text(encoding="utf-8"))

    handler_filters = config["handlers"]["stderr"].get("filters", [])
    filter_classes = {
        config["filters"][name].get("()") or config["filters"][name].get("class")
        for name in handler_filters
    }
    assert SCRUBBER_CLASS_PATH in filter_classes


def test_log_config_stderr_handler_is_root_handler() -> None:
    config = json.loads(LOG_CONFIG_PATH.read_text(encoding="utf-8"))

    assert "stderr" in config["root"]["handlers"]


def test_log_redaction_uvicorn_error_exception_message_canary_not_formatted(
    configured_stream: io.StringIO,
) -> None:
    canary = new_canary()

    logging.getLogger("uvicorn.error").error(
        "Exception in ASGI application", exc_info=_exc_info(CanaryLeakError(canary))
    )

    assert canary not in configured_stream.getvalue()


def test_log_redaction_uvicorn_error_exception_type_name_kept(
    configured_stream: io.StringIO,
) -> None:
    logging.getLogger("uvicorn.error").error(
        "Exception in ASGI application",
        exc_info=_exc_info(CanaryLeakError(new_canary())),
    )

    assert CanaryLeakError.__name__ in configured_stream.getvalue()


def test_log_redaction_uvicorn_error_traceback_not_formatted(
    configured_stream: io.StringIO,
) -> None:
    logging.getLogger("uvicorn.error").error(
        "Exception in ASGI application",
        exc_info=_exc_info(CanaryLeakError(new_canary())),
    )

    output = configured_stream.getvalue()
    assert "Traceback" not in output
    assert __file__ not in output


def test_log_redaction_logger_exception_canary_not_formatted(
    configured_stream: io.StringIO,
) -> None:
    canary = new_canary()

    try:
        _raise(CanaryLeakError(canary))
    except CanaryLeakError:
        logging.getLogger("some.third_party.sdk").exception("request failed")

    assert canary not in configured_stream.getvalue()


def test_log_redaction_stack_info_not_formatted(configured_stream: io.StringIO) -> None:
    logging.getLogger("uvicorn.error").error("with stack", stack_info=True)

    output = configured_stream.getvalue()
    assert "Stack (most recent call last)" not in output
    assert __file__ not in output


def test_log_redaction_exception_group_canary_not_formatted(
    configured_stream: io.StringIO,
) -> None:
    canary = new_canary()
    group = BaseExceptionGroup(
        "outer",
        [ExceptionGroup("inner", [ValueError(canary)]), KeyError(canary)],
    )

    logging.getLogger("uvicorn.error").error("boom", exc_info=_exc_info(group))

    assert canary not in configured_stream.getvalue()


def test_log_redaction_exception_group_leaf_type_names_kept(
    configured_stream: io.StringIO,
) -> None:
    group = BaseExceptionGroup(
        "outer",
        [ExceptionGroup("inner", [ValueError(new_canary())]), KeyError(new_canary())],
    )

    logging.getLogger("uvicorn.error").error("boom", exc_info=_exc_info(group))

    output = configured_stream.getvalue()
    assert "ValueError" in output
    assert "KeyError" in output


def test_log_redaction_record_without_exception_message_kept(
    configured_stream: io.StringIO,
) -> None:
    logging.getLogger("uvicorn.error").info("Started server process")

    assert "Started server process" in configured_stream.getvalue()


def test_exc_info_scrubber_clears_exc_info_exc_text_and_stack_info() -> None:
    # Local import: keeps the other tests in this module collectable while
    # the filter module does not exist yet.
    from app.logging_filters import ExcInfoScrubber  # noqa: PLC0415

    canary = new_canary()
    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="boom",
        args=None,
        exc_info=_exc_info(CanaryLeakError(canary)),
        sinfo="Stack (most recent call last):\n  fake frame",
    )
    record.exc_text = f"Traceback ... {canary}"

    keep = ExcInfoScrubber().filter(record)

    # Read the attributes through getattr: mypy narrows them after the
    # first ``is None`` assertion and would flag the rest as unreachable.
    assert keep  # the record itself is still emitted
    assert getattr(record, "exc_info") is None  # noqa: B009
    assert getattr(record, "exc_text") is None  # noqa: B009
    assert getattr(record, "stack_info") is None  # noqa: B009
    assert canary not in record.getMessage()
    assert CanaryLeakError.__name__ in record.getMessage()
