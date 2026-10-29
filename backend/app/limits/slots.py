"""Extraction slots held per client key (threat model T6 control 4).

Counts only slots in use, so the table is bounded by the shared pool. Taken without
waiting. The caller pairs ``try_acquire`` with ``release`` in one ``try``/``finally``.
"""

from __future__ import annotations


class ClientSlots:
    def __init__(self, max_per_client: int) -> None:
        if max_per_client < 1:
            msg = "max_per_client must be positive"
            raise ValueError(msg)
        self._max = max_per_client
        self._held: dict[str, int] = {}

    def try_acquire(self, key: str) -> bool:
        """Take a slot for ``key`` now. Never waits."""
        count = self._held.get(key, 0)
        if count >= self._max:
            return False
        self._held[key] = count + 1
        return True

    def release(self, key: str) -> None:
        """Give back a slot taken by ``try_acquire``; ``RuntimeError`` if none is held."""
        count = self._held.get(key, 0)
        if count == 0:
            msg = "release() without a held slot"
            raise RuntimeError(msg)
        if count == 1:
            del self._held[key]
        else:
            self._held[key] = count - 1

    def in_use(self, key: str) -> int:
        return self._held.get(key, 0)
