"""Analysis pass of the free mode (ADR 0018 point 7; threat model T10).

Same format and key handling as the topic pass (``app.limits.free_pass``) with audience
``analysis`` and a life of 30 minutes: ``v1.analysis.<expiry>.<client-key-hash>.<nonce>.<mac>``.
One pass covers one analysis: at most ``MAX_DOCUMENTS`` recorded document digests and
``MAX_CHARS`` characters in total, and its own caps of worst-case AI calls and Neurons. Calls and
Neurons are reserved in full before a request starts and settled after it, so re-tagging
cannot spend more than the caps. The table is bounded and fails closed when full. Callers run
on the event loop thread and no method awaits. Nothing here logs.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from app.limits.free_pass import FreePassError, FreePasses

__all__ = ["AnalysisPasses", "FreePassError"]

TTL_SECONDS: Final = 1800
AUDIENCE: Final = "analysis"
MAX_DOCUMENTS: Final = 2
PAGE_CHARS: Final = 3000
MAX_PAGES: Final = 30
MAX_CHARS: Final = PAGE_CHARS * MAX_PAGES

TOO_MANY_DOCUMENTS: Final = "too_many_documents"
TOO_LARGE: Final = "free_too_large"


class AnalysisPasses(FreePasses):
    def __init__(
        self,
        max_entries: int,
        max_calls: int,
        max_neurons: int,
        clock: Callable[[], float],
    ) -> None:
        super().__init__(
            max_entries,
            max_calls,
            clock,
            ttl=TTL_SECONDS,
            audience=AUDIENCE,
            code_prefix="analysis_pass",
        )
        self._max_neurons = max_neurons

    def issue(self, client: str) -> tuple[str, str] | None:
        issued = super().issue(client)
        if issued is not None:
            entry = self.entry(issued[1])
            if entry is not None:
                entry.calls = 0  # here ``calls`` counts reserved AI calls
        return issued

    def fits(self, nonce: str | None, calls: int, neurons: int) -> bool:
        """Do ``calls`` and ``neurons`` fit the caps of pass ``nonce`` (a new pass: ``None``)?"""
        entry = self.entry(nonce) if nonce is not None else None
        used_calls, used_neurons = (entry.calls, entry.neurons) if entry is not None else (0, 0)
        return used_calls + calls <= self._max_calls and used_neurons + neurons <= self._max_neurons

    def size_error(self, nonce: str | None, digest: str, chars: int) -> str | None:
        """``free_too_large`` or ``too_many_documents`` when the document does not fit the
        pass, else ``None``. The size check comes first. A recorded digest is counted once."""
        entry = self.entry(nonce) if nonce is not None else None
        documents = dict(entry.documents) if entry is not None else {}
        documents[digest] = chars
        if sum(documents.values()) > MAX_CHARS:
            return TOO_LARGE
        if len(documents) > MAX_DOCUMENTS:
            return TOO_MANY_DOCUMENTS
        return None

    def reserve(self, nonce: str, calls: int, neurons: int, digest: str, chars: int) -> None:
        """Take the worst case of a request and record its document."""
        entry = self.entry(nonce)
        if entry is None:
            return
        entry.calls += calls
        entry.neurons += neurons
        entry.documents[digest] = chars

    def settle(self, nonce: str, calls: tuple[int, int], neurons: tuple[int, int]) -> None:
        """Replace the reserved ``(estimate, actual)`` calls and Neurons by the actual ones."""
        entry = self.entry(nonce)
        if entry is None:
            return
        entry.calls = max(0, entry.calls - calls[0] + max(0, calls[1]))
        entry.neurons = max(0, entry.neurons - neurons[0] + max(0, neurons[1]))
