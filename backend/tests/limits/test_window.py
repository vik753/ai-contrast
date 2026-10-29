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
    limit: int = 3, window: float = 60, max_keys: int = 10
) -> tuple[FixedWindowLimiter, FakeClock]:
    clock = FakeClock()
    return FixedWindowLimiter(limit, window, max_keys, clock), clock


def test_hit_under_limit_is_allowed() -> None:
    limiter, _ = make(limit=3)

    assert [limiter.hit("a") for _ in range(3)] == [True, True, True]


def test_hit_over_limit_is_refused() -> None:
    limiter, _ = make(limit=3)
    for _ in range(3):
        limiter.hit("a")

    assert limiter.hit("a") is False
    assert limiter.hit("a") is False


def test_keys_are_counted_separately() -> None:
    limiter, _ = make(limit=1)
    limiter.hit("a")

    assert limiter.hit("b") is True


def test_window_still_closed_just_before_end() -> None:
    limiter, clock = make(limit=1, window=60)
    limiter.hit("a")
    clock.now += 59.9

    assert limiter.hit("a") is False


def test_window_resets_at_end() -> None:
    limiter, clock = make(limit=1, window=60)
    limiter.hit("a")
    clock.now += 60

    assert limiter.hit("a") is True


def test_counter_starts_from_zero_after_reset() -> None:
    limiter, clock = make(limit=2, window=60)
    limiter.hit("a")
    limiter.hit("a")
    clock.now += 61
    limiter.hit("a")

    assert limiter.hit("a") is True
    assert limiter.hit("a") is False


def test_refused_hits_do_not_extend_the_window() -> None:
    limiter, clock = make(limit=1, window=60)
    limiter.hit("a")
    clock.now += 30
    assert limiter.hit("a") is False
    clock.now += 30

    assert limiter.hit("a") is True


def test_table_full_of_fresh_keys_refuses_new_key() -> None:
    limiter, _ = make(limit=5, max_keys=3)
    for key in ("a", "b", "c"):
        assert limiter.hit(key) is True

    assert limiter.hit("d") is False


def test_table_full_still_serves_existing_keys() -> None:
    limiter, _ = make(limit=5, max_keys=3)
    for key in ("a", "b", "c"):
        limiter.hit(key)
    limiter.hit("d")

    assert limiter.hit("a") is True


def test_refused_new_key_does_not_evict_a_fresh_key() -> None:
    limiter, _ = make(limit=1, max_keys=2)
    limiter.hit("a")
    limiter.hit("b")
    limiter.hit("c")

    assert limiter.hit("a") is False
    assert limiter.hit("b") is False


def test_table_full_accepts_new_key_when_all_windows_expired() -> None:
    limiter, clock = make(limit=1, window=60, max_keys=2)
    limiter.hit("a")
    limiter.hit("b")
    clock.now += 61

    assert limiter.hit("c") is True


def test_expired_key_is_evicted_before_fresh_keys() -> None:
    limiter, clock = make(limit=1, window=60, max_keys=3)
    limiter.hit("a")
    clock.now += 30
    limiter.hit("b")
    clock.now += 20
    limiter.hit("c")
    clock.now += 11  # a expired (61 s), b and c fresh

    assert limiter.hit("d") is True
    assert limiter.hit("b") is False
    assert limiter.hit("c") is False


def test_table_never_accepts_more_fresh_keys_than_max_keys() -> None:
    limiter, _ = make(limit=1, window=60, max_keys=5)

    accepted = sum(limiter.hit(f"k{i}") for i in range(100))

    assert accepted == 5


@pytest.mark.parametrize(
    ("limit", "window", "max_keys"),
    [(0, 60, 10), (-1, 60, 10), (1, 0, 10), (1, -5, 10), (1, 60, 0), (1, 60, -1)],
)
def test_constructor_rejects_non_positive_values(limit: int, window: float, max_keys: int) -> None:
    with pytest.raises(ValueError, match=".+"):
        FixedWindowLimiter(limit, window, max_keys, FakeClock())
