"""Logging filters used by ``log_config.json`` (threat model T1, control 7).

Importing this module sets ``logging.raiseExceptions = False``: if a handler still
fails, the logging module must not print the "--- Logging error ---" report, which
includes the record's message arguments.
"""

from __future__ import annotations

import copy
import logging

from app.exc_names import exception_type_names

logging.raiseExceptions = False

FORMAT_ERROR_FLAG = " log_format_error=1"
UNPRINTABLE_MESSAGE = "<unprintable log message>"


def _safe_message(record: logging.LogRecord) -> str:
    """``record.getMessage()``; on a formatting error, the raw ``msg`` plus a flag.

    The arguments are never used in the fallback: they may hold secrets, and they
    are the likely cause of the error.
    """
    try:
        return record.getMessage()
    except Exception:  # noqa: BLE001 - any formatting error must be contained
        try:
            raw = str(record.msg)
        except Exception:  # noqa: BLE001 - a broken __str__ on msg
            raw = UNPRINTABLE_MESSAGE
        return raw + FORMAT_ERROR_FLAG


class ExcInfoScrubber(logging.Filter):
    """Emit a scrubbed copy of every record (Python 3.12+ filter semantics).

    Attached to the root ``stderr`` handler, so it covers every logger, including
    ``uvicorn.error`` and third-party SDKs. Exception messages and traceback frames
    may hold the provider key or contract text. The copy keeps only the exception
    type names, appended to the right-stripped message as ``exc_type=...``; it has
    no ``exc_info``, ``exc_text``, ``stack_info`` or ``args``. The original record
    is not changed, so other handlers see it as it was logged.
    """

    def filter(self, record: logging.LogRecord) -> logging.LogRecord:
        scrubbed = copy.copy(record)
        message = _safe_message(record)
        exc = record.exc_info[1] if record.exc_info else None
        if exc is not None:
            message = f"{message.rstrip()} exc_type={exception_type_names(exc)}"
        scrubbed.msg = message
        scrubbed.args = None
        scrubbed.exc_info = None
        scrubbed.exc_text = None
        scrubbed.stack_info = None
        return scrubbed
