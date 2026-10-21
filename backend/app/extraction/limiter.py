"""Limit on extractions in progress in this process (threat model T6, ADR 0010).

A slot is taken without waiting before the request body is read. If none is free,
the caller answers ``503 busy`` at once: a queue would hold memory for bodies that
nobody processes yet. The app keeps one instance in ``app.state.extraction_limiter``.

The count is per process, so the backend runs as a single uvicorn worker (see the
``Dockerfile``). All callers run on the event loop thread and no method awaits, so
no lock is needed.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager


class ExtractionBusyError(Exception):
    """No free slot. Carries no data."""


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
        """Give back a slot taken by ``try_acquire``.

        Raises ``RuntimeError`` if no slot is held: a double release would let more
        extractions run than the limit allows.
        """
        if self._in_use == 0:
            msg = "release() without a held slot"
            raise RuntimeError(msg)
        self._in_use -= 1

    def try_slot(self) -> AbstractContextManager[None] | None:
        """Take a slot now (never waits) and return a context manager that holds it
        and releases it exactly once on exit, also on exceptions and cancellation.
        Return ``None`` if no slot is free.

        Enter the result at once (``with slot:``); a result that is never entered
        keeps its slot.
        """
        if not self.try_acquire():
            return None
        return self._held()

    def slot(self) -> AbstractContextManager[None]:
        """Like ``try_slot`` but raises ``ExtractionBusyError`` if no slot is free."""
        held = self.try_slot()
        if held is None:
            raise ExtractionBusyError
        return held

    @contextmanager
    def _held(self) -> Iterator[None]:
        try:
            yield
        finally:
            self.release()
