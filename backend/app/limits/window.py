"""Fixed-window counter per key with a bounded table that fails closed.

Two modes:

- rolling (default): a window starts at the first hit of a key and ends at
  ``start + window_seconds``. The clock must never go back: pass ``time.monotonic``.
- aligned: windows are ``[k * window_seconds, (k + 1) * window_seconds)`` on the clock
  value, which must then be wall time (``time.time``). A daily limiter resets at
  00:00 UTC.

Refused hits do not extend a window. When the table holds ``max_keys`` keys, expired
keys are dropped first; if every key is still fresh, a new key is refused (fail closed)
and no fresh key is evicted. Keys are kept in window-start order, so dropping expired
keys is amortized O(1). Callers run on the event loop thread; no method awaits.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    retry_after: int = 0  # whole seconds, rounded up, at least 1 when refused


class FixedWindowLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: float,
        max_keys: int,
        clock: Callable[[], float],
        *,
        aligned: bool = False,
    ) -> None:
        if limit < 1 or window_seconds <= 0 or max_keys < 1:
            msg = "limit, window_seconds and max_keys must be positive"
            raise ValueError(msg)
        self._limit = limit
        self._window = window_seconds
        self._max_keys = max_keys
        self._clock = clock
        self._aligned = aligned
        # key -> (window start, hits); oldest window first.
        self._table: dict[str, tuple[float, int]] = {}

    def _start_of_new_window(self, now: float) -> float:
        if self._aligned:
            return math.floor(now / self._window) * self._window
        return now

    def _expired(self, start: float, now: float) -> bool:
        return now - start >= self._window

    def _retry_after(self, start: float, now: float) -> int:
        return max(1, math.ceil(start + self._window - now))

    def _drop_expired(self, now: float) -> None:
        while self._table:
            oldest = next(iter(self._table))
            if not self._expired(self._table[oldest][0], now):
                return
            del self._table[oldest]

    def _current(self, key: str, now: float) -> tuple[float, int] | None:
        entry = self._table.get(key)
        if entry is not None and self._expired(entry[0], now):
            del self._table[key]
            return None
        return entry

    def _full(self, now: float) -> bool:
        if len(self._table) >= self._max_keys:
            self._drop_expired(now)
        return len(self._table) >= self._max_keys

    def hit(self, key: str) -> Decision:
        """Count one hit."""
        now = self._clock()
        entry = self._current(key, now)
        if entry is None:
            if self._full(now):
                return Decision(False, self._retry_after(self._oldest_start(), now))
            self._table[key] = (self._start_of_new_window(now), 1)
            return Decision(True)
        start, count = entry
        if count >= self._limit:
            return Decision(False, self._retry_after(start, now))
        self._table[key] = (start, count + 1)
        return Decision(True)

    def _oldest_start(self) -> float:
        return self._table[next(iter(self._table))][0]

    def peek(self, key: str) -> bool:
        """Would a hit be allowed now? Counts nothing and adds no key."""
        now = self._clock()
        entry = self._table.get(key)
        if entry is not None and not self._expired(entry[0], now):
            return entry[1] < self._limit
        if entry is not None:
            return True
        return not self._full(now)

    def refund(self, key: str) -> None:
        """Undo one counted hit in the current window (never below 0)."""
        now = self._clock()
        entry = self._current(key, now)
        if entry is not None and entry[1] > 0:
            self._table[key] = (entry[0], entry[1] - 1)
