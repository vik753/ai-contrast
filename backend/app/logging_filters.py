"""Logging filters used by ``log_config.json`` (threat model T1, control 7)."""

from __future__ import annotations

import logging

from app.exc_names import exception_type_names


class ExcInfoScrubber(logging.Filter):
    """Remove exception messages, tracebacks and stack info from every record.

    Attached to the root ``stderr`` handler, so it covers every logger, including
    ``uvicorn.error`` and third-party SDKs. Exception messages and traceback frames
    (with local source lines) may hold the provider key or contract text. Only the
    exception type names are kept, appended to the message as ``exc_type=...``.

    The record itself is always emitted.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        if exc is not None:
            # Merge args now, so that the appended names cannot be read as
            # format directives.
            record.msg = f"{record.getMessage()} exc_type={exception_type_names(exc)}"
            record.args = None
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True
