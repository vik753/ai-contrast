"""Bounded table of used Turnstile tokens (threat model T10, ADR 0016 point 7).

A token is stored (as a SHA-256 digest, so the table holds no token text) only after
Turnstile accepted it. An entry lives ``ttl_seconds``. When the table holds ``max_entries``
fresh entries, a new token is refused (fail closed) and no fresh entry is evicted.
Entries are kept in insertion order, so dropping expired ones is amortized O(1).
Callers run on the event loop thread and no method awaits.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from collections.abc import Callable


class ReplayTable:
    def __init__(self, max_entries: int, ttl_seconds: float, clock: Callable[[], float]) -> None:
        if max_entries < 1 or ttl_seconds <= 0:
            msg = "max_entries and ttl_seconds must be positive"
            raise ValueError(msg)
        self._max = max_entries
        self._ttl = ttl_seconds
        self._clock = clock
        self._seen: OrderedDict[bytes, float] = OrderedDict()

    def _drop_expired(self, now: float) -> None:
        while self._seen:
            digest, stored_at = next(iter(self._seen.items()))
            if now - stored_at < self._ttl:
                return
            del self._seen[digest]

    @staticmethod
    def _digest(token: str) -> bytes:
        return hashlib.sha256(token.encode("utf-8", "surrogatepass")).digest()

    def would_accept(self, token: str) -> bool:
        """Could ``add`` store this token now? Stores nothing."""
        now = self._clock()
        self._drop_expired(now)
        return self._digest(token) not in self._seen and len(self._seen) < self._max

    def add(self, token: str) -> bool:
        """Store the token. ``False`` if it is already stored or the table is full."""
        now = self._clock()
        self._drop_expired(now)
        digest = self._digest(token)
        if digest in self._seen or len(self._seen) >= self._max:
            return False
        self._seen[digest] = now
        return True
