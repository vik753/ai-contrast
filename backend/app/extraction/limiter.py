"""Server-wide limit on extractions in progress (threat model T6, ADR 0010).

A slot is taken without waiting before the request body is read. If none is free,
the caller answers ``503 busy`` at once: a queue would hold memory for bodies that
nobody processes yet. The app keeps one instance in ``app.state.extraction_limiter``.

All callers run on the event loop thread and the methods never ``await``, so no
lock is needed.
"""

from __future__ import annotations


class ExtractionLimiter:
    def __init__(self, max_concurrent: int) -> None:
        if max_concurrent < 1:
            msg = "max_concurrent must be positive"
            raise ValueError(msg)
        self._max = max_concurrent
        self._in_use = 0

    def try_acquire(self) -> bool:
        """Take a slot if one is free. Never waits."""
        if self._in_use >= self._max:
            return False
        self._in_use += 1
        return True

    def release(self) -> None:
        """Give back a slot taken by ``try_acquire``. Extra calls are ignored."""
        if self._in_use > 0:
            self._in_use -= 1
