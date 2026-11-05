# ruff: noqa: RUF001
"""S8-T1 review: synonym grammar, apostrophe folding, merge and layer 2 rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.tagging.keywords import keyword_tags
from app.tagging.layer2 import clause_hits
from app.tagging.merge import merge_tags
from app.tagging.model import TagMergeError
from app.topics.catalog import load_catalog
from app.topics.safety import TextKind, TopicTextError, check_topic_text

from .helpers import clause, topic

REPO = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("aa bbb", "en"),
        ("tow tr", "en"),
        ("roadside towing service fee limit amount extra", "en"),
        ("ab/cde fgh", "en"),
    ],
)
def test_synonym_word_under_three_letters_or_over_six_words_is_refused(
    text: str, lang: str
) -> None:
    with pytest.raises(TopicTextError) as info:
        check_topic_text(text, TextKind.SYNONYM, lang)
    assert info.value.code == "invalid_topic_text"


@pytest.mark.parametrize(
    ("text", "lang"),
    [("франшиза ав", "uk"), ("ав франшиза", "ru"), ("a a a", "en"), ("a aa aaa", "en")],
)
def test_synonym_short_word_in_any_language_is_refused(text: str, lang: str) -> None:
    with pytest.raises(TopicTextError) as info:
        check_topic_text(text, TextKind.SYNONYM, lang)
    assert info.value.code == "invalid_topic_text"


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("roadside towing service fee limit amount", "en"),
        ("tow truck", "en"),
        ("франшиза", "uk"),
        ("безумовна франшиза", "ru"),
    ],
)
def test_synonym_of_three_letter_words_and_up_to_six_words_passes(text: str, lang: str) -> None:
    check_topic_text(text, TextKind.SYNONYM, lang)


def test_shared_catalog_still_loads_with_the_synonym_rule() -> None:
    catalog = load_catalog(REPO / "shared" / "topics")
    assert catalog.domains


def test_topic_with_short_word_synonym_is_refused_by_confirm() -> None:
    with pytest.raises(TopicTextError):
        topic(1, en=["a aa aaa"])


# --- apostrophes ------------------------------------------------------------------------

FORMS = ["об'єкт", "обʼєкт", "об’єкт"]


@pytest.mark.parametrize("synonym", FORMS)
@pytest.mark.parametrize("text", FORMS)
def test_keyword_tags_apostrophe_forms_match_each_other(synonym: str, text: str) -> None:
    result = keyword_tags([clause(1, f"Вартість {text} страхування")], [topic(1, uk=[synonym])])
    assert result["c1"] == {"custom_1"}


def test_keyword_tags_apostrophe_in_english_synonym_matches_other_forms() -> None:
    t = topic(1, en=["owner's liability"])
    for mark in ["'", "’", "ʼ"]:
        assert keyword_tags([clause(1, f"The owner{mark}s liability")], [t])["c1"] == {"custom_1"}


# --- model cap counts only non-keyword pairs ---------------------------------------------


def _ids(a: int, b: int) -> list[str]:
    return [f"c{i}" for i in range(a, b + 1)]


def test_merge_topic_with_many_keyword_clauses_and_few_model_tags_is_not_dropped() -> None:
    cl = [clause(i, "text") for i in range(1, 76)]
    kw = {c.id: set() for c in cl}
    for cid in _ids(1, 70):
        kw[cid] = {"custom_1"}
    high = {c.id: {"custom_1"} for c in cl}
    r = merge_tags(clauses=cl, topics=[topic(1)], keyword=kw, model_high=high)
    assert r.topics["custom_1"].model_tags_dropped is False
    assert r.topics["custom_1"].model_clauses == 5
    assert r.topics["custom_1"].keyword_clauses == 70
    assert r.topics["custom_1"].not_analyzed is None


def test_merge_model_asserted_counts_all_model_and_check_pairs() -> None:
    cl = [clause(i, "text") for i in range(1, 11)]
    kw = {c.id: set() for c in cl}
    kw["c1"] = {"custom_1"}
    high = {c.id: {"custom_1"} for c in cl[:6]}
    low = {c.id: {"custom_1"} for c in cl[6:8]}
    r = merge_tags(
        clauses=cl, topics=[topic(1)], keyword=kw, model_high=high, model_low=low, check_yes=low
    )
    assert r.topics["custom_1"].model_asserted == 8


def test_merge_model_asserted_is_zero_without_model_tags() -> None:
    r = merge_tags(clauses=[clause(1, "x")], topics=[topic(1)], keyword={"c1": {"custom_1"}})
    assert r.topics["custom_1"].model_asserted == 0


def test_merge_sixty_one_model_only_clauses_still_drop_the_topic() -> None:
    cl = [clause(i, "text") for i in range(1, 62)]
    r = merge_tags(
        clauses=cl,
        topics=[topic(1)],
        keyword={c.id: set() for c in cl},
        model_high={c.id: {"custom_1"} for c in cl},
    )
    assert r.topics["custom_1"].model_tags_dropped is True


# --- per-clause cap overflow -------------------------------------------------------------


def test_merge_clause_cap_overflow_sets_incomplete_reason_clause_cap() -> None:
    topics = [topic(i) for i in range(1, 9)]
    r = merge_tags(
        clauses=[clause(1, "x")],
        topics=topics,
        keyword={"c1": set()},
        model_high={"c1": {t.topic_id for t in topics}},
    )
    assert r.model_tagging_incomplete is True
    assert "clause_cap" in r.incomplete_reasons


def test_merge_clause_cap_overflow_keeps_topics_out_of_missing() -> None:
    topics = [topic(i) for i in range(1, 9)]
    r = merge_tags(
        clauses=[clause(1, "x")],
        topics=topics,
        keyword={"c1": set()},
        model_high={"c1": {t.topic_id for t in topics}},
    )
    assert r.missing_topics == ()


def test_merge_exactly_five_model_tags_is_not_a_clause_cap_overflow() -> None:
    topics = [topic(i) for i in range(1, 9)]
    r = merge_tags(
        clauses=[clause(1, "x")],
        topics=topics,
        keyword={"c1": set()},
        model_high={"c1": {f"custom_{i}" for i in range(1, 6)}},
    )
    assert "clause_cap" not in r.incomplete_reasons
    assert r.model_tagging_incomplete is False


# --- duplicate clause ids ----------------------------------------------------------------


def test_merge_duplicate_clause_ids_are_refused() -> None:
    cl = [clause(1, "a"), clause(1, "b")]
    with pytest.raises(TagMergeError) as info:
        merge_tags(clauses=cl, topics=[topic(1)], keyword={"c1": set()})
    assert info.value.code == "duplicate_clause_id"


def test_clause_hits_duplicate_clause_ids_are_refused() -> None:
    with pytest.raises(TagMergeError) as info:
        clause_hits([clause(1, "a"), clause(1, "b")])
    assert info.value.code == "duplicate_clause_id"
