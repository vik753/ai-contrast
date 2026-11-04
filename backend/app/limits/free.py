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
# Topic calls together may use at most this share of the daily Neuron budget, in percent.
TOPIC_BUDGET_PERCENT: Final = 30
# Cloudflare price of the free model, in Neurons per million tokens (input, output).
NEURONS_PER_M_INPUT: Final = 31818
NEURONS_PER_M_OUTPUT: Final = 68182
# A token is estimated as three characters of input (worst case for Latin and Cyrillic text).
CHARS_PER_TOKEN: Final = 3

type Reason = Literal["ip", "budget", "table"]


@dataclass(frozen=True, slots=True)
class QuotaDecision:
    allowed: bool
    retry_after: int = 0  # whole seconds until 00:00 UTC, at least 1 when refused
    reason: Reason | None = None


def _ceil_div(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def topic_neurons(input_chars: int, max_tokens: int, *, repair: bool) -> int:
    """The worst-case Neurons of one topic job: input at three characters per token, output at
    ``max_tokens``; doubled when a repair call can follow. At least 1."""
    if input_chars < 0 or max_tokens < 0:
        msg = "input_chars and max_tokens must not be negative"
        raise ValueError(msg)
    micro = input_chars * NEURONS_PER_M_INPUT + CHARS_PER_TOKEN * max_tokens * NEURONS_PER_M_OUTPUT
    neurons = max(1, _ceil_div(micro, CHARS_PER_TOKEN * 1_000_000))
    return neurons * 2 if repair else neurons


def usage_neurons(input_tokens: int, output_tokens: int) -> int:
    """The Neurons of reported token usage, rounded up."""
    micro = (
        max(0, input_tokens) * NEURONS_PER_M_INPUT + max(0, output_tokens) * NEURONS_PER_M_OUTPUT
    )
    return _ceil_div(micro, 1_000_000)


class FreeQuota:
    def __init__(
        self,
        calls_per_ip: int,
        neuron_budget: int,
        max_keys: int,
        clock: Callable[[], float],
        *,
        topic_calls_per_ip: int = 40,
    ) -> None:
        if calls_per_ip < 1 or neuron_budget < 1 or max_keys < 1 or topic_calls_per_ip < 1:
            msg = "calls_per_ip, neuron_budget and max_keys must be positive"
            raise ValueError(msg)
        self._budget = neuron_budget
        self._clock = clock
        self._calls = FixedWindowLimiter(calls_per_ip, DAY_SECONDS, max_keys, clock, aligned=True)
        self._day = self._day_of(clock())
        self._spent = 0
        # Free topic calls have their own per-key counter and their own share of the budget.
        self._topic_calls = FixedWindowLimiter(
            topic_calls_per_ip, DAY_SECONDS, max_keys, clock, aligned=True
        )
        self._topic_cap = neuron_budget * TOPIC_BUDGET_PERCENT // 100
        self._topic_spent = 0

    @staticmethod
    def _day_of(now: float) -> int:
        return math.floor(now / DAY_SECONDS)

    def _roll(self) -> float:
        now = self._clock()
        day = self._day_of(now)
        if day != self._day:
            self._day = day
            self._spent = 0
            self._topic_spent = 0
        return now

    def _until_midnight(self, now: float) -> int:
        return max(1, math.ceil((self._day + 1) * DAY_SECONDS - now))

    @property
    def remaining_neurons(self) -> int:
        self._roll()
        return max(0, self._budget - self._spent)

    def _reserve(
        self, key: str, neurons: int, calls: FixedWindowLimiter, *, topic: bool
    ) -> QuotaDecision:
        if neurons < 1:
            msg = "neurons must be positive"
            raise ValueError(msg)
        now = self._roll()
        over_share = topic and self._topic_spent + neurons > self._topic_cap
        if self._spent + neurons > self._budget or over_share:
            return QuotaDecision(False, self._until_midnight(now), "budget")
        decision = calls.hit(key)
        if not decision.allowed:
            # A key without a fresh entry is refused only because the table is full.
            reason: Reason = "ip" if calls.has(key) else "table"
            return QuotaDecision(False, decision.retry_after, reason)
        self._spent += neurons
        if topic:
            self._topic_spent += neurons
        return QuotaDecision(True)

    def _settle(self, estimate: int, actual: int, *, topic: bool) -> None:
        self._roll()
        self._spent = max(0, self._spent - estimate + max(0, actual))
        if topic:
            self._topic_spent = max(0, self._topic_spent - estimate + max(0, actual))

    def reserve(self, key: str, neurons: int) -> QuotaDecision:
        """Count one call for ``key`` and reserve ``neurons``, or refuse and count nothing."""
        return self._reserve(key, neurons, self._calls, topic=False)

    def settle(self, estimate: int, actual: int) -> None:
        """Replace the reserved ``estimate`` by the ``actual`` Neurons (never below 0 spent)."""
        self._settle(estimate, actual, topic=False)

    def refund_call(self, key: str) -> None:
        """Undo the per-key call of a reserve whose model did no work (never below 0)."""
        self._calls.refund(key)

    def reserve_topic(self, key: str, neurons: int) -> QuotaDecision:
        """Like ``reserve`` for a free topic call: the topic counter and the topic share apply."""
        return self._reserve(key, neurons, self._topic_calls, topic=True)

    def settle_topic(self, estimate: int, actual: int) -> None:
        """Replace the reserved ``estimate`` of a topic call by the ``actual`` Neurons."""
        self._settle(estimate, actual, topic=True)

    def refund_topic_call(self, key: str) -> None:
        """Undo the per-key call of a ``reserve_topic`` whose model did no work."""
        self._topic_calls.refund(key)
