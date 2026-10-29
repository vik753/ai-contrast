"""Extraction slots held per client key (threat model T6 control 4).

Counts only slots in use, so the table is bounded by the shared pool. Taken without
waiting; the context manager releases exactly once on every exit path.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager


class ClientSlots:
    def __init__(self, max_per_client: int) -> None:
        if max_per_client < 1:
            msg = "max_per_client must be positive"
            raise ValueError(msg)
        self._max = max_per_client
        self._held: dict[str, int] = {}

    def try_slot(self, key: str) -> AbstractContextManager[None] | None:
        """Take a slot for ``key`` now, or return ``None``. Enter the result at once."""
        count = self._held.get(key, 0)
        if count >= self._max:
            return None
        self._held[key] = count + 1
        return self._release_on_exit(key)

    @contextmanager
    def _release_on_exit(self, key: str) -> Iterator[None]:
        try:
            yield
        finally:
            count = self._held[key] - 1
            if count == 0:
                del self._held[key]
            else:
                self._held[key] = count
