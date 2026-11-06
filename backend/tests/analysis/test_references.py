# ruff: noqa: RUF001
"""Cross-reference closure (ADR 0019 point 4)."""

import pytest

from app.analysis.verify import Clause, reference_closure

from .helpers import c

PHRASES = {
    "en": "See clause {n} for details.",
    "uk-p": "Див. п. {n} цього договору.",
    "uk-punkt": "Відповідно до пункту {n} цього договору.",
    "uk-rozdil": "Відповідно до розділу {n} цього договору.",
    "ru-p": "См. п. {n} настоящего договора.",
    "ru-punkt": "В соответствии с пунктом {n} настоящего договора.",
}


@pytest.mark.parametrize("phrase", list(PHRASES))
def test_reference_phrases_resolve_to_numbered_clause(phrase: str) -> None:
    cl = [c("a", PHRASES[phrase].format(n="4.2"), number="1"), c("b", "Body.", number="4.2")]
    assert reference_closure(cl, ["a"])["a"].added == ("b",)


def test_reference_with_trailing_period_resolves() -> None:
    cl = [c("a", "Subject to clause 4.2.", number="1"), c("b", "Body.", number="4.2")]
    assert reference_closure(cl, ["a"])["a"].added == ("b",)


def test_reference_to_clause_not_in_document_adds_nothing() -> None:
    e = reference_closure([c("a", "See clause 9.", number="1")], ["a"])["a"]
    assert e.added == ()
    assert not e.too_many


def test_prefix_number_is_not_matched() -> None:
    cl = [
        c("a", "See clause 4.2.", number="1"),
        c("b", "Body.", number="4.20"),
        c("d", "x", number="4"),
    ]
    assert reference_closure(cl, ["a"])["a"].added == ()


def test_depth_is_one() -> None:
    cl = [
        c("a", "See clause 2.", number="1"),
        c("b", "See clause 3.", number="2"),
        c("d", "Deep.", number="3"),
    ]
    assert reference_closure(cl, ["a"])["a"].added == ("b",)


def test_cycle_terminates_and_does_not_duplicate() -> None:
    cl = [c("a", "See clause 2.", number="1"), c("b", "See clause 1.", number="2")]
    r = reference_closure(cl, ["a", "b"])
    assert r["a"].added == ("b",)
    assert r["b"].added == ("a",)


def test_self_reference_is_ignored() -> None:
    e = reference_closure([c("a", "See clause 1.", number="1")], ["a"])["a"]
    assert e.added == ()
    assert e.needed == 0


def test_repeated_reference_counts_once() -> None:
    cl = [c("a", "See clause 2 and clause 2.", number="1"), c("b", "x", number="2")]
    e = reference_closure(cl, ["a"])["a"]
    assert e.added == ("b",)
    assert e.needed == 1


def _fan(n: int) -> list[Clause]:
    refs = " ".join(f"See clause {i}." for i in range(2, 2 + n))
    return [c("a", refs, number="1"), *(c(f"r{i}", "x", number=str(i)) for i in range(2, 2 + n))]


def test_exactly_five_references_are_added_and_not_too_many() -> None:
    e = reference_closure(_fan(5), ["a"])["a"]
    assert len(e.added) == 5
    assert e.needed == 5
    assert not e.too_many


def test_six_references_are_too_many_and_extras_are_not_added() -> None:
    e = reference_closure(_fan(6), ["a"])["a"]
    assert e.too_many
    assert e.needed == 6
    assert len(e.added) <= 5


def test_max_refs_is_a_parameter() -> None:
    assert reference_closure(_fan(3), ["a"], max_refs=2)["a"].too_many


def test_unknown_start_id_is_ignored_or_empty() -> None:
    r = reference_closure([c("a", "x", number="1")], ["nope"])
    assert "nope" not in r or r["nope"].added == ()
