"""Fixed-window counter per key with a bounded table that fails closed.

A window starts at the first hit of a key and ends at ``start + window_seconds``.
Refused hits do not extend it. When the table holds ``max_keys`` keys, expired keys
are dropped first; if every key is still fresh, a new key is refused (fail closed)
and no fresh key is evicted. Keys are kept in window-start order, so dropping
expired keys is amortized O(1). Callers run on the event loop thread; no method awaits.
"""

from __future__ import annotations

from collections.abc import Callable


class FixedWindowLimiter:
    def __init__(
        self, limit: int, window_seconds: float, max_keys: int, clock: Callable[[], float]
    ) -> None:
        if limit < 1 or window_seconds <= 0 or max_keys < 1:
            msg = "limit, window_seconds and max_keys must be positive"
            raise ValueError(msg)
        self._limit = limit
        self._window = window_seconds
        self._max_keys = max_keys
        self._clock = clock
        # key -> (window start, hits); oldest window first.
        self._table: dict[str, tuple[float, int]] = {}

    def _drop_expired(self, now: float) -> None:
        while self._table:
            oldest = next(iter(self._table))
            if now - self._table[oldest][0] < self._window:
                return
            del self._table[oldest]

    def hit(self, key: str) -> bool:
        """Count one hit. ``True`` means allowed."""
        now = self._clock()
        entry = self._table.get(key)
        if entry is not None and now - entry[0] >= self._window:
            del self._table[key]
            entry = None
        if entry is None:
            if len(self._table) >= self._max_keys:
                self._drop_expired(now)
                if len(self._table) >= self._max_keys:
                    return False
            self._table[key] = (now, 1)
            return True
        start, count = entry
        if count >= self._limit:
            return False
        self._table[key] = (start, count + 1)
        return True
