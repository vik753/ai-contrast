"""Linear time on 300,000 characters (ADR 0019 point 3; no regex built from client text)."""

import time
from collections.abc import Callable

from app.analysis.verify import (
    Rating,
    ValueIn,
    apply_green_rules,
    expand_quote,
    reference_closure,
    verify_quote,
    verify_value,
)

from .helpers import DAYS10, c, ctx, ev, green

N = 300_000
LIMIT = 3.0  # seconds; a quadratic implementation needs minutes


def timed[T](fn: Callable[[], T]) -> T:
    t0 = time.perf_counter()
    r = fn()
    assert time.perf_counter() - t0 < LIMIT
    return r


def test_verify_quote_absent_quote_in_300k_text_is_fast() -> None:
    cl = c("c1", "a " * (N // 2))
    assert not timed(lambda: verify_quote(cl, "a " * 50 + "b")).ok


def test_verify_quote_many_overlapping_occurrences_is_fast() -> None:
    cl = c("c1", "a" * N)
    timed(lambda: verify_quote(cl, "aaaa"))


def test_verify_quote_whitespace_flood_is_fast() -> None:
    cl = c("c1", " " * N + "x")
    assert timed(lambda: verify_quote(cl, "x")).ok


def test_expand_quote_without_terminators_is_fast() -> None:
    t = "word " * (N // 5)
    assert timed(lambda: expand_quote(t, N // 2, N // 2 + 4)) == (0, len(t))


def test_expand_quote_dense_abbreviation_periods_is_fast() -> None:
    t = "e.g. " * (N // 5)
    timed(lambda: expand_quote(t, N // 2, N // 2 + 4, abbreviations=frozenset({"e.g."})))


def test_apply_green_rules_on_300k_clause_is_fast() -> None:
    text = "The insurer pays within 10 days after notice. " + "filler words " * (N // 13)
    out = timed(
        lambda: apply_green_rules(ctx(c("c1", text, number="1")), green("c1", "within 10 days"))
    )
    assert out.rating in (Rating.green, Rating.yellow)


def test_apply_green_rules_many_clauses_is_fast() -> None:
    cls = [
        c(f"c{i}", "Plain words about nothing in particular. " * 3, number=str(i))
        for i in range(3000)
    ]
    cls[0] = c("c0", "The insurer pays within 10 days after notice. " + "x" * 100, number="1.1")
    timed(lambda: apply_green_rules(ctx(*cls), green("c0", "within 10 days", value=DAYS10)))


def test_number_check_on_digit_flood_is_fast() -> None:
    text = "1 " * (N // 2) + "days"
    timed(
        lambda: verify_value(ctx(c("c1", text)), ValueIn("a", (ev("c1", "1 1 1"),), number=DAYS10))
    )


def test_reference_closure_on_many_references_is_fast() -> None:
    text = "See clause 1. " * (N // 14)
    timed(lambda: reference_closure([c("a", text, number="1"), c("b", "x", number="2")], ["a"]))
