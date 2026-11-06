"""Missing-topic findings, Other completeness, not_analyzed routing (ADR 0019 point 3.5 to 3.7)."""

import pytest

from app.analysis.verify import (
    Rating,
    TaggingState,
    TopicInfo,
    TopicState,
    document_completeness,
    missing_topic_findings,
    other_clause_ids,
)

OK = TaggingState(complete=True, signed=True)


def t(i: str, n: int = 0, state: TopicState = TopicState.ok, essential: bool = False) -> TopicInfo:
    return TopicInfo(id=i, clause_count=n, state=state, essential=essential)


def test_missing_topic_non_essential_is_yellow() -> None:
    (f,) = missing_topic_findings(OK, [t("x")])
    assert f.topic == "x" and f.rating is Rating.yellow


def test_missing_topic_essential_is_red() -> None:
    (f,) = missing_topic_findings(OK, [t("x", essential=True)])
    assert f.rating is Rating.red


def test_missing_topic_is_never_green() -> None:
    res = missing_topic_findings(OK, [t("a"), t("b", essential=True), t("c", 3)])
    assert all(f.rating is not Rating.green for f in res)


def test_topic_with_clauses_has_no_missing_finding() -> None:
    assert missing_topic_findings(OK, [t("x", 2, essential=True)]) == ()


@pytest.mark.parametrize("state", [TopicState.model_tags_dropped, TopicState.not_analyzed])
def test_dropped_or_not_analyzed_topic_has_no_missing_finding(state: TopicState) -> None:
    assert missing_topic_findings(OK, [t("x", state=state, essential=True)]) == ()


@pytest.mark.parametrize(
    "state", [TaggingState(False, True), TaggingState(True, False), TaggingState(False, False)]
)
def test_incomplete_or_unsigned_tagging_gives_no_missing_findings(state: TaggingState) -> None:
    assert missing_topic_findings(state, [t("x", essential=True), t("y")]) == ()


def test_missing_topics_are_reported_per_topic_in_order() -> None:
    res = missing_topic_findings(OK, [t("a"), t("b", 1), t("c", essential=True)])
    assert [(f.topic, f.rating) for f in res] == [("a", Rating.yellow), ("c", Rating.red)]


def test_all_other_clauses_rated_is_complete() -> None:
    r = document_completeness(other_total=5, other_rated=5)
    assert not r.incomplete and r.unrated_other == 0 and r.greens_allowed


def test_zero_other_clauses_is_complete() -> None:
    assert not document_completeness(0, 0).incomplete


def test_unrated_other_clause_makes_document_incomplete_and_forbids_greens() -> None:
    r = document_completeness(other_total=5, other_rated=3)
    assert r.incomplete and r.unrated_other == 2 and not r.greens_allowed


def test_not_analyzed_topic_clauses_go_to_other() -> None:
    res = other_clause_ids(["c1"], {"t1": ["c2", "c3"], "t2": ["c4"]}, {"t1"})
    assert res == ("c1", "c2", "c3")


def test_other_clause_ids_has_no_duplicates_and_keeps_order() -> None:
    res = other_clause_ids(["c3", "c1"], {"t1": ["c1", "c2"], "t2": ["c2", "c5"]}, {"t1", "t2"})
    assert res == ("c3", "c1", "c2", "c5")


def test_no_not_analyzed_topic_leaves_other_unchanged() -> None:
    assert other_clause_ids(["c1"], {"t1": ["c2"]}, set()) == ("c1",)
