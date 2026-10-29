"""S6-T3 AC1: fixed-window limiter with a bounded table that fails closed."""

from __future__ import annotations

import pytest

from app.limits.window import FixedWindowLimiter


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def make(
    limit: int = 3,
    window: float = 60,
    max_keys: int = 10,
    *,
    aligned: bool = False,
    now: float = 1000.0,
) -> tuple[FixedWindowLimiter, FakeClock]:
    clock = FakeClock(now)
    return FixedWindowLimiter(limit, window, max_keys, clock, aligned=aligned), clock


def test_hit_under_limit_is_allowed() -> None:
    limiter, _ = make(limit=3)

    assert [limiter.hit("a").allowed for _ in range(3)] == [True, True, True]


def test_hit_over_limit_is_refused() -> None:
    limiter, _ = make(limit=3)
    for _ in range(3):
        limiter.hit("a")

    assert limiter.hit("a").allowed is False
    assert limiter.hit("a").allowed is False


def test_keys_are_counted_separately() -> None:
    limiter, _ = make(limit=1)
    limiter.hit("a")

    assert limiter.hit("b").allowed is True


def test_window_still_closed_just_before_end() -> None:
    limiter, clock = make(limit=1, window=60)
    limiter.hit("a")
    clock.now += 59.9

    assert limiter.hit("a").allowed is False


def test_window_resets_at_end() -> None:
    limiter, clock = make(limit=1, window=60)
    limiter.hit("a")
    clock.now += 60

    assert limiter.hit("a").allowed is True


def test_counter_starts_from_zero_after_reset() -> None:
    limiter, clock = make(limit=2, window=60)
    limiter.hit("a")
    limiter.hit("a")
    clock.now += 61
    limiter.hit("a")

    assert limiter.hit("a").allowed is True
    assert limiter.hit("a").allowed is False


def test_refused_hits_do_not_extend_the_window() -> None:
    limiter, clock = make(limit=1, window=60)
    limiter.hit("a")
    clock.now += 30
    assert limiter.hit("a").allowed is False
    clock.now += 30

    assert limiter.hit("a").allowed is True


def test_table_full_of_fresh_keys_refuses_new_key() -> None:
    limiter, _ = make(limit=5, max_keys=3)
    for key in ("a", "b", "c"):
        assert limiter.hit(key).allowed is True

    assert limiter.hit("d").allowed is False


def test_table_full_still_serves_existing_keys() -> None:
    limiter, _ = make(limit=5, max_keys=3)
    for key in ("a", "b", "c"):
        limiter.hit(key)
    limiter.hit("d")

    assert limiter.hit("a").allowed is True


def test_refused_new_key_does_not_evict_a_fresh_key() -> None:
    limiter, _ = make(limit=1, max_keys=2)
    limiter.hit("a")
    limiter.hit("b")
    limiter.hit("c")

    assert limiter.hit("a").allowed is False
    assert limiter.hit("b").allowed is False


def test_table_full_accepts_new_key_when_all_windows_expired() -> None:
    limiter, clock = make(limit=1, window=60, max_keys=2)
    limiter.hit("a")
    limiter.hit("b")
    clock.now += 61

    assert limiter.hit("c").allowed is True


def test_expired_key_is_evicted_before_fresh_keys() -> None:
    limiter, clock = make(limit=1, window=60, max_keys=3)
    limiter.hit("a")
    clock.now += 30
    limiter.hit("b")
    clock.now += 20
    limiter.hit("c")
    clock.now += 11  # a expired (61 s), b and c fresh

    assert limiter.hit("d").allowed is True
    assert limiter.hit("b").allowed is False
    assert limiter.hit("c").allowed is False


def test_table_never_accepts_more_fresh_keys_than_max_keys() -> None:
    limiter, _ = make(limit=1, window=60, max_keys=5)

    accepted = sum(limiter.hit(f"k{i}").allowed for i in range(100))

    assert accepted == 5


@pytest.mark.parametrize(
    ("limit", "window", "max_keys"),
    [(0, 60, 10), (-1, 60, 10), (1, 0, 10), (1, -5, 10), (1, 60, 0), (1, 60, -1)],
)
def test_constructor_rejects_non_positive_values(limit: int, window: float, max_keys: int) -> None:
    with pytest.raises(ValueError, match=r"\S"):
        FixedWindowLimiter(limit, window, max_keys, FakeClock())


# --- decisions, peek, refund, aligned windows (review round 1) ---

DAY = 86400
# 2026-10-29 00:00:00 UTC
MIDNIGHT = 1793232000


def test_hit_returns_a_decision_with_allowed_and_retry_after() -> None:
    limiter, _ = make(limit=1)

    decision = limiter.hit("a")

    assert decision.allowed is True
    assert isinstance(decision.retry_after, int)


def test_refused_decision_retry_after_is_seconds_until_window_end() -> None:
    limiter, clock = make(limit=1, window=60)
    limiter.hit("a")
    clock.now += 20

    decision = limiter.hit("a")

    assert decision.allowed is False
    assert decision.retry_after == 40


def test_refused_decision_retry_after_is_rounded_up_and_at_least_one() -> None:
    limiter, clock = make(limit=1, window=60)
    limiter.hit("a")
    clock.now += 59.9

    assert limiter.hit("a").retry_after == 1


def test_refused_new_key_on_full_table_has_retry_after_at_least_one() -> None:
    limiter, _ = make(limit=1, max_keys=1)
    limiter.hit("a")

    decision = limiter.hit("b")

    assert decision.allowed is False
    assert decision.retry_after >= 1


def test_peek_does_not_count() -> None:
    limiter, _ = make(limit=1)

    assert limiter.peek("a") is True
    assert limiter.peek("a") is True
    assert limiter.hit("a").allowed is True


def test_peek_is_false_when_over_the_limit() -> None:
    limiter, _ = make(limit=1)
    limiter.hit("a")

    assert limiter.peek("a") is False


def test_peek_is_true_again_after_the_window() -> None:
    limiter, clock = make(limit=1, window=60)
    limiter.hit("a")
    clock.now += 60

    assert limiter.peek("a") is True


def test_peek_new_key_on_full_table_is_false() -> None:
    limiter, _ = make(limit=5, max_keys=1)
    limiter.hit("a")

    assert limiter.peek("b") is False


def test_peek_does_not_add_a_key() -> None:
    limiter, _ = make(limit=5, max_keys=1)

    limiter.peek("a")

    assert limiter.hit("b").allowed is True


def test_refund_gives_back_one_hit() -> None:
    limiter, _ = make(limit=1)
    limiter.hit("a")

    limiter.refund("a")

    assert limiter.hit("a").allowed is True


def test_refund_undoes_only_one_hit() -> None:
    limiter, _ = make(limit=3)
    for _ in range(3):
        limiter.hit("a")

    limiter.refund("a")

    assert limiter.hit("a").allowed is True
    assert limiter.hit("a").allowed is False


def test_refund_never_goes_below_zero() -> None:
    limiter, _ = make(limit=2)
    limiter.hit("a")
    limiter.refund("a")
    limiter.refund("a")
    limiter.refund("a")

    assert limiter.hit("a").allowed is True
    assert limiter.hit("a").allowed is True
    assert limiter.hit("a").allowed is False


def test_refund_unknown_key_is_a_no_op() -> None:
    limiter, _ = make(limit=1, max_keys=1)

    limiter.refund("nobody")

    assert limiter.hit("a").allowed is True
    assert limiter.hit("a").allowed is False


def test_refund_after_window_end_without_new_hit_is_a_no_op() -> None:
    limiter, clock = make(limit=1, window=60)
    limiter.hit("a")
    clock.now += 61

    limiter.refund("a")

    assert limiter.hit("a").allowed is True
    assert limiter.hit("a").allowed is False


def test_aligned_window_resets_at_the_next_multiple_not_after_window_seconds() -> None:
    limiter, clock = make(limit=1, window=DAY, aligned=True, now=MIDNIGHT - 600)
    assert limiter.hit("a").allowed is True
    clock.now = MIDNIGHT - 1

    assert limiter.hit("a").allowed is False

    clock.now = MIDNIGHT

    assert limiter.hit("a").allowed is True


def test_aligned_daily_window_resets_at_midnight_whatever_the_first_hit_time() -> None:
    limiter, clock = make(limit=1, window=DAY, aligned=True, now=MIDNIGHT + 13 * 3600 + 17)
    limiter.hit("a")
    clock.now = MIDNIGHT + DAY - 1
    assert limiter.hit("a").allowed is False

    clock.now = MIDNIGHT + DAY

    assert limiter.hit("a").allowed is True


def test_aligned_hit_at_exact_boundary_starts_a_new_window() -> None:
    limiter, _ = make(limit=1, window=DAY, aligned=True, now=MIDNIGHT)

    assert limiter.hit("a").allowed is True
    assert limiter.hit("a").allowed is False


def test_aligned_retry_after_counts_to_the_next_boundary() -> None:
    limiter, clock = make(limit=1, window=DAY, aligned=True, now=MIDNIGHT + DAY - 3600)
    limiter.hit("a")
    clock.now = MIDNIGHT + DAY - 90

    assert limiter.hit("a").retry_after == 90


def test_aligned_keys_expire_together_at_the_boundary() -> None:
    limiter, clock = make(limit=1, window=DAY, aligned=True, max_keys=2, now=MIDNIGHT + 10)
    limiter.hit("a")
    clock.now = MIDNIGHT + DAY - 10
    limiter.hit("b")
    clock.now = MIDNIGHT + DAY + 1

    assert limiter.hit("c").allowed is True  # both old keys expired: table not full


def test_aligned_refund_works_in_the_current_window() -> None:
    limiter, _ = make(limit=1, window=DAY, aligned=True, now=MIDNIGHT + 5)
    limiter.hit("a")

    limiter.refund("a")

    assert limiter.hit("a").allowed is True


def test_rolling_mode_is_the_default() -> None:
    clock = FakeClock(MIDNIGHT - 600)
    limiter = FixedWindowLimiter(1, DAY, 10, clock)
    limiter.hit("a")
    clock.now = MIDNIGHT  # a boundary, but rolling mode counts from the first hit

    assert limiter.hit("a").allowed is False
