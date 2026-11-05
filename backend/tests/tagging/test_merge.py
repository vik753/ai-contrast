"""S8-T1 AC3: merge of keyword, model, check and client tags (ADR 0018 points 3-5)."""
# ruff: noqa: PT018

from __future__ import annotations

from typing import Any

import pytest

from app.tagging.merge import TaggingResult, merge_tags
from app.tagging.model import TagClause, TagMergeError

from .helpers import clause, clauses, topic

A, B, C = "custom_1", "custom_2", "custom_3"


def _merge(cl: list[TagClause], n_topics: int = 2, **kw: Any) -> TaggingResult:
    topics = [topic(i) for i in range(1, n_topics + 1)]
    kw.setdefault("keyword", {c.id: set() for c in cl})
    return merge_tags(clauses=cl, topics=topics, **kw)


def _ids(n: int, start: int = 1) -> list[str]:
    return [f"c{i}" for i in range(start, start + n)]


# --- sources and add-only ---------------------------------------------------------------


def test_merge_keyword_tag_has_source_keyword() -> None:
    r = _merge(clauses(2), keyword={"c1": {A}, "c2": set()})
    assert r.tags["c1"] == {A: "keyword"}
    assert r.tags["c2"] == {}
    assert r.other == ["c2"]


def test_merge_model_high_adds_tag_with_source_model() -> None:
    r = _merge(clauses(1), model_high={"c1": {A}})
    assert r.tags["c1"] == {A: "model"}
    assert r.other == []


def test_merge_check_yes_on_low_pair_adds_tag_with_source_check() -> None:
    r = _merge(clauses(1), model_low={"c1": {A}}, check_yes={"c1": {A}})
    assert r.tags["c1"] == {A: "check"}


def test_merge_low_pair_without_check_yes_is_not_a_tag() -> None:
    r = _merge(clauses(1), model_low={"c1": {A}})
    assert r.tags["c1"] == {}
    assert r.other == ["c1"]
    assert r.model_tagging_incomplete is False


def test_merge_model_answer_omitting_keyword_pair_changes_nothing() -> None:
    cl = clauses(2)
    kw = {"c1": {A}, "c2": {B}}
    baseline = _merge(cl, keyword=kw)
    with_model = _merge(cl, keyword=kw, model_high={"c1": set(), "c2": set()})
    assert with_model.tags == baseline.tags
    assert with_model.other == baseline.other


def test_merge_model_never_removes_or_relabels_a_keyword_pair() -> None:
    r = _merge(clauses(1), keyword={"c1": {A}}, model_high={"c1": {A, B}})
    assert r.tags["c1"] == {A: "keyword", B: "model"}


def test_merge_model_tags_do_not_change_keyword_tags_of_other_clauses() -> None:
    r = _merge(clauses(3), keyword={"c1": {A}, "c2": {B}, "c3": set()}, model_high={"c3": {A}})
    assert r.tags["c1"] == {A: "keyword"} and r.tags["c2"] == {B: "keyword"}


def test_merge_input_mappings_are_not_modified() -> None:
    kw = {"c1": {A}}
    high = {"c1": {B}}
    _merge(clauses(1), keyword=kw, model_high=high)
    assert kw == {"c1": {A}} and high == {"c1": {B}}


# --- 5 model tags per clause -------------------------------------------------------------


def test_merge_clause_keeps_at_most_five_model_tags() -> None:
    cl = clauses(1)
    r = _merge(cl, n_topics=8, model_high={"c1": {f"custom_{i}" for i in range(1, 9)}})
    sources = list(r.tags["c1"].values())
    assert sources.count("model") == 5
    assert set(r.tags["c1"]) <= {f"custom_{i}" for i in range(1, 9)}
    assert r.other == []


def test_merge_five_model_tags_cap_counts_check_tags_too() -> None:
    r = _merge(
        clauses(1),
        n_topics=8,
        model_high={"c1": {"custom_1", "custom_2", "custom_3"}},
        model_low={"c1": {"custom_4", "custom_5", "custom_6", "custom_7"}},
        check_yes={"c1": {"custom_4", "custom_5", "custom_6", "custom_7"}},
    )
    assert sum(1 for s in r.tags["c1"].values() if s in {"model", "check"}) == 5


def test_merge_keyword_tags_are_not_capped_at_five() -> None:
    kw = {"c1": {f"custom_{i}" for i in range(1, 9)}}
    r = _merge(clauses(1), n_topics=8, keyword=kw, model_high={"c1": {"custom_1"}})
    assert len(r.tags["c1"]) == 8
    assert all(s == "keyword" for s in r.tags["c1"].values())


# --- 60 model-tagged clauses per topic ---------------------------------------------------


def test_merge_sixty_model_clauses_for_a_topic_is_not_dropped() -> None:
    r = _merge(clauses(60), model_high={c: {A} for c in _ids(60)})
    assert r.topics[A].model_tags_dropped is False
    assert r.topics[A].model_clauses == 60
    assert r.other == []


def test_merge_sixty_one_model_clauses_drop_all_model_tags_of_the_topic() -> None:
    r = _merge(clauses(61), model_high={c: {A} for c in _ids(61)})
    assert r.topics[A].model_tags_dropped is True
    assert r.topics[A].model_clauses == 0
    assert all(t == {} for t in r.tags.values())
    assert r.other == _ids(61)


def test_merge_drop_counts_check_tags_with_model_tags() -> None:
    high = {c: {A} for c in _ids(30)}
    low = {c: {A} for c in _ids(31, 31)}
    r = _merge(clauses(61), model_high=high, model_low=low, check_yes=low)
    assert r.topics[A].model_tags_dropped is True
    assert r.other == _ids(61)


def test_merge_drop_keeps_keyword_tags_of_the_topic() -> None:
    kw = {c: set() for c in _ids(62)}
    kw["c1"] = {A}
    r = _merge(clauses(62), keyword=kw, model_high={c: {A} for c in _ids(62)})
    assert r.topics[A].model_tags_dropped
    assert r.tags["c1"] == {A: "keyword"}
    assert "c1" not in r.other
    assert "c2" in r.other


def test_merge_drop_of_one_topic_leaves_other_topics_model_tags() -> None:
    high = {c: {A} for c in _ids(61)}
    high["c1"] = {A, B}
    r = _merge(clauses(61), model_high=high)
    assert r.tags["c1"] == {B: "model"}
    assert "c1" not in r.other
    assert r.topics[B].model_tags_dropped is False


def test_merge_dropped_topic_clauses_with_another_tag_are_not_in_other() -> None:
    kw = {c: set() for c in _ids(61)}
    kw["c5"] = {B}
    r = _merge(clauses(61), keyword=kw, model_high={c: {A} for c in _ids(61)})
    assert "c5" not in r.other


# --- 120 keyword clauses -----------------------------------------------------------------


def test_merge_one_hundred_twenty_keyword_clauses_are_analyzed() -> None:
    r = _merge(clauses(120), keyword={c: {A} for c in _ids(120)})
    assert r.topics[A].not_analyzed is None
    assert r.topics[A].keyword_clauses == 120
    assert r.other == []


def test_merge_over_one_hundred_twenty_keyword_clauses_is_not_analyzed() -> None:
    r = _merge(clauses(121), keyword={c: {A} for c in _ids(121)})
    assert r.topics[A].not_analyzed == "too_many_clauses"
    assert r.topics[A].keyword_clauses == 121


def test_merge_not_analyzed_topic_keeps_keyword_tags_and_clauses_also_go_to_other() -> None:
    r = _merge(clauses(121), keyword={c: {A} for c in _ids(121)})
    assert all(t == {A: "keyword"} for t in r.tags.values())
    assert r.other == _ids(121)


def test_merge_not_analyzed_topic_does_not_touch_other_topics() -> None:
    kw = {c: {A} for c in _ids(121)}
    kw["c1"] = {A, B}
    r = _merge(clauses(121), keyword=kw)
    assert r.topics[B].not_analyzed is None
    assert "c1" not in r.other


def test_merge_client_tags_count_towards_keyword_cap() -> None:
    kw = {c: ({A} if int(c[1:]) <= 100 else set()) for c in _ids(121)}
    client = {c: {A} for c in _ids(21, 101)}
    r = _merge(clauses(121), keyword=kw, client=client)
    assert r.topics[A].keyword_clauses == 121
    assert r.topics[A].not_analyzed == "too_many_clauses"


def test_merge_client_tag_on_a_keyword_pair_is_counted_once() -> None:
    r = _merge(clauses(120), keyword={c: {A} for c in _ids(120)}, client={"c1": {A}})
    assert r.topics[A].keyword_clauses == 120
    assert r.topics[A].not_analyzed is None
    assert r.tags["c1"] == {A: "keyword"}


# --- client tags -------------------------------------------------------------------------


def test_merge_client_tag_adds_a_tag_with_source_client() -> None:
    r = _merge(clauses(2), client={"c1": {A}})
    assert r.tags["c1"] == {A: "client"}
    assert r.other == ["c2"]


def test_merge_client_tag_with_unknown_clause_id_is_refused() -> None:
    with pytest.raises(TagMergeError) as info:
        _merge(clauses(2), client={"c99": {A}})
    assert str(info.value) == "invalid_client_tag"


def test_merge_client_tag_with_unknown_topic_id_is_refused() -> None:
    with pytest.raises(TagMergeError) as info:
        _merge(clauses(2), client={"c1": {"custom_99"}})
    assert info.value.code == "invalid_client_tag"


def test_merge_client_tag_with_malformed_ids_is_refused() -> None:
    for bad in ({"": {A}}, {"c1": {""}}, {"__proto__": {A}}, {"c1": {"../x"}}):
        with pytest.raises(TagMergeError):
            _merge(clauses(1), client=bad)


def test_merge_more_than_five_client_tags_on_a_clause_is_refused() -> None:
    topics = {f"custom_{i}" for i in range(1, 7)}
    with pytest.raises(TagMergeError) as info:
        _merge(clauses(1), n_topics=6, client={"c1": topics})
    assert info.value.code == "too_many_client_tags"


def test_merge_five_client_tags_on_a_clause_are_accepted() -> None:
    topics = {f"custom_{i}" for i in range(1, 6)}
    r = _merge(clauses(1), n_topics=6, client={"c1": topics})
    assert set(r.tags["c1"]) == topics


def test_merge_client_tag_cannot_remove_a_keyword_tag() -> None:
    r = _merge(clauses(1), keyword={"c1": {A}}, client={"c1": {B}})
    assert r.tags["c1"] == {A: "keyword", B: "client"}


# --- incomplete model tagging ------------------------------------------------------------


def test_merge_no_failures_means_complete() -> None:
    r = _merge(clauses(1))
    assert r.model_tagging_incomplete is False
    assert r.incomplete_reasons == ()


@pytest.mark.parametrize("reason", ["bad_output", "timeout", "quota", "check_failed"])
def test_merge_failure_sets_incomplete_with_reason(reason: str) -> None:
    r = _merge(clauses(1), failures=[reason])
    assert r.model_tagging_incomplete is True
    assert r.incomplete_reasons == (reason,)


def test_merge_reasons_are_sorted_and_unique() -> None:
    r = _merge(clauses(1), failures=["timeout", "bad_output", "timeout"])
    assert r.incomplete_reasons == ("bad_output", "timeout")


def test_merge_check_failed_drops_low_tags_and_flags_incomplete() -> None:
    r = _merge(clauses(2), model_low={"c1": {A}, "c2": {A}}, failures=["check_failed"])
    assert r.tags == {"c1": {}, "c2": {}}
    assert r.other == ["c1", "c2"]
    assert r.incomplete_reasons == ("check_failed",)


def test_merge_check_failed_keeps_high_and_keyword_tags() -> None:
    r = _merge(
        clauses(2),
        keyword={"c1": {A}, "c2": set()},
        model_high={"c2": {B}},
        model_low={"c1": {B}},
        failures=["check_failed"],
    )
    assert r.tags["c1"] == {A: "keyword"}
    assert r.tags["c2"] == {B: "model"}


def test_merge_failed_batch_clause_with_keyword_tag_keeps_it_and_untagged_goes_to_other() -> None:
    r = _merge(clauses(2), keyword={"c1": {A}, "c2": set()}, failures=["bad_output"])
    assert r.tags["c1"] == {A: "keyword"}
    assert r.other == ["c2"]


# --- missing topics ----------------------------------------------------------------------


def test_merge_topic_with_no_clause_is_missing_when_tagging_is_complete() -> None:
    r = _merge(clauses(2), n_topics=3, keyword={"c1": {A}, "c2": set()})
    assert r.missing_topics == (B, C)


def test_merge_no_missing_topic_when_tagging_is_incomplete() -> None:
    for reason in ["bad_output", "timeout", "quota", "check_failed"]:
        r = _merge(clauses(2), n_topics=3, keyword={"c1": {A}, "c2": set()}, failures=[reason])
        assert r.missing_topics == ()


def test_merge_topic_with_only_a_client_tag_is_not_missing() -> None:
    r = _merge(clauses(1), client={"c1": {A}})
    assert r.missing_topics == (B,)


def test_merge_dropped_topic_is_never_missing() -> None:
    r = _merge(clauses(61), model_high={c: {A} for c in _ids(61)})
    assert r.topics[A].model_tags_dropped
    assert A not in r.missing_topics
    assert B in r.missing_topics


def test_merge_not_analyzed_topic_is_never_missing() -> None:
    r = _merge(clauses(121), keyword={c: {A} for c in _ids(121)})
    assert A not in r.missing_topics


def test_merge_every_topic_has_a_status() -> None:
    r = _merge(clauses(1), n_topics=3)
    assert set(r.topics) == {A, B, C}


# --- Other and risk terms ----------------------------------------------------------------


def test_merge_other_clause_with_risk_term_has_hits() -> None:
    cl = [clause(1, "The seller pays a penalty of 5%."), clause(2, "Nothing special.")]
    r = _merge(cl)
    assert r.other == ["c1", "c2"]
    assert list(r.risk) == ["c1"]
    start, end = r.risk["c1"][0]
    assert cl[0].text[start:end].lower().startswith("penal")


def test_merge_tagged_clause_with_risk_term_is_not_scanned() -> None:
    cl = [clause(1, "The seller pays a penalty of 5%.")]
    r = _merge(cl, keyword={"c1": {A}})
    assert r.risk == {}


def test_merge_other_keeps_document_order() -> None:
    r = _merge(clauses(5), keyword={"c1": set(), "c2": {A}, "c3": set(), "c4": set(), "c5": {A}})
    assert r.other == ["c1", "c3", "c4"]
