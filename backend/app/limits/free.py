"""Free-mode quota: a per-key daily call limit and a global daily Neuron budget (ADR 0016 point 7).

Both reset at 00:00 UTC (the Cloudflare allowance resets then). ``reserve`` takes the
estimated Neurons of one call from the budget and counts one call for the key; a refusal
counts nothing. ``settle`` corrects the spent budget after the call. The per-key table is
bounded and fails closed: when it holds ``max_keys`` fresh keys, a new key is refused.
The budget is process memory only; a restart gives a fresh budget (single worker, no state
kept by design). Callers run on the event loop thread and no method awaits.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal

from app.limits.window import FixedWindowLimiter

DAY_SECONDS: Final = 86400
# The Neurons that a free check reserves before the call (a probe of a few tokens).
CHECK_NEURONS: Final = 10

type Reason = Literal["ip", "budget", "table"]


@dataclass(frozen=True, slots=True)
class QuotaDecision:
    allowed: bool
    retry_after: int = 0  # whole seconds until 00:00 UTC, at least 1 when refused
    reason: Reason | None = None


class FreeQuota:
    def __init__(
        self,
        calls_per_ip: int,
        neuron_budget: int,
        max_keys: int,
        clock: Callable[[], float],
    ) -> None:
        if calls_per_ip < 1 or neuron_budget < 1 or max_keys < 1:
            msg = "calls_per_ip, neuron_budget and max_keys must be positive"
            raise ValueError(msg)
        self._budget = neuron_budget
        self._clock = clock
        self._calls = FixedWindowLimiter(calls_per_ip, DAY_SECONDS, max_keys, clock, aligned=True)
        self._day = self._day_of(clock())
        self._spent = 0

    @staticmethod
    def _day_of(now: float) -> int:
        return math.floor(now / DAY_SECONDS)

    def _roll(self) -> float:
        now = self._clock()
        day = self._day_of(now)
        if day != self._day:
            self._day = day
            self._spent = 0
        return now

    def _until_midnight(self, now: float) -> int:
        return max(1, math.ceil((self._day + 1) * DAY_SECONDS - now))

    @property
    def remaining_neurons(self) -> int:
        self._roll()
        return max(0, self._budget - self._spent)

    def reserve(self, key: str, neurons: int) -> QuotaDecision:
        """Count one call for ``key`` and reserve ``neurons``, or refuse and count nothing."""
        if neurons < 1:
            msg = "neurons must be positive"
            raise ValueError(msg)
        now = self._roll()
        if self._spent + neurons > self._budget:
            return QuotaDecision(False, self._until_midnight(now), "budget")
        decision = self._calls.hit(key)
        if not decision.allowed:
            # A key without a fresh entry is refused only because the table is full.
            reason: Reason = "ip" if self._calls.has(key) else "table"
            return QuotaDecision(False, decision.retry_after, reason)
        self._spent += neurons
        return QuotaDecision(True)

    def settle(self, estimate: int, actual: int) -> None:
        """Replace the reserved ``estimate`` by the ``actual`` Neurons (never below 0 spent)."""
        self._roll()
        self._spent = max(0, self._spent - estimate + max(0, actual))
