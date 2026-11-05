"""S8-T1 AC1: keyword tags (ADR 0018 point 2)."""
# ruff: noqa: PT018
# ruff: noqa: RUF001

from __future__ import annotations

from app.tagging.keywords import KEYWORD_RULES_VERSION, keyword_tags

from .helpers import clause, topic


def _tags(texts: list[str], *topics: object, heading: str | None = None) -> dict[str, set[str]]:
    cl = [clause(i + 1, t, heading) for i, t in enumerate(texts)]
    return keyword_tags(cl, topics)  # type: ignore[arg-type]


def test_keyword_tags_returns_every_clause_id_with_empty_set_when_no_match() -> None:
    result = _tags(["nothing here", "franchise applies"], topic(1, en=["franchise"]))
    assert result == {"c1": set(), "c2": {"custom_1"}}


def test_keyword_tags_topic_without_synonyms_tags_nothing() -> None:
    assert _tags(["franchise applies"], topic(1)) == {"c1": set()}


def test_keyword_tags_one_clause_gets_several_topics() -> None:
    result = _tags(
        ["The franchise and the towing are covered."],
        topic(1, en=["franchise"]),
        topic(2, en=["towing"]),
    )
    assert result["c1"] == {"custom_1", "custom_2"}


def test_keyword_tags_is_case_insensitive() -> None:
    assert _tags(["FRANCHISE applies"], topic(1, en=["Franchise"])) == {"c1": {"custom_1"}}


def test_keyword_tags_cyrillic_homoglyphs_in_latin_word_match() -> None:
    assert _tags(["The franсhise (Cyrillic s) applies"], topic(1, en=["franchise"])) == {
        "c1": {"custom_1"}
    }


def test_keyword_tags_latin_homoglyphs_in_cyrillic_word_match() -> None:
    # "франшиза" typed with Latin p, a, H look-alikes.
    text = "Безумовна фpaHшиза складає 5%"
    assert _tags([text], topic(1, uk=["франшиз"])) == {"c1": {"custom_1"}}


def test_keyword_tags_fullwidth_letters_match_after_nfkc() -> None:
    assert _tags(["ｆｒａｎｃｈｉｓｅ applies"], topic(1, en=["franchise"])) == {"c1": {"custom_1"}}


def test_keyword_tags_ukrainian_stem_matches_case_forms() -> None:
    t = topic(1, uk=["франшиз"])
    for form in ["франшиза", "франшизи", "франшизою", "Франшизу", "ФРАНШИЗІ"]:
        assert _tags([f"Сума {form} вказана"], t)["c1"] == {"custom_1"}, form


def test_keyword_tags_russian_stem_matches_case_forms() -> None:
    t = topic(1, ru=["франшиз"])
    for form in ["франшиза", "франшизы", "франшизой", "франшизу"]:
        assert _tags([f"Сумма {form} указана"], t)["c1"] == {"custom_1"}, form


def test_keyword_tags_stem_does_not_match_mid_word() -> None:
    t = topic(1, uk=["франшиз"], en=["franchise"])
    assert _tags(["суперфраншиза", "unfranchised", "xfranchise"], t) == {
        "c1": set(),
        "c2": set(),
        "c3": set(),
    }


def test_keyword_tags_stem_at_word_start_after_punctuation_matches() -> None:
    assert _tags(["(franchise), see 5.1"], topic(1, en=["franchise"]))["c1"] == {"custom_1"}
    assert _tags(["non-franchise item"], topic(1, en=["franchise"]))["c1"] == {"custom_1"}


def test_keyword_tags_phrase_matches_flexible_whitespace() -> None:
    t = topic(1, en=["roadside assistance"])
    for sep in [" ", "   ", "\t", "\n", "\r\n", " \n  ", " "]:
        assert _tags([f"Roadside{sep}assistance is free"], t)["c1"] == {"custom_1"}, repr(sep)


def test_keyword_tags_phrase_needs_the_words_in_order_and_adjacent() -> None:
    t = topic(1, en=["roadside assistance"])
    texts = ["assistance roadside", "roadside the assistance", "roadsideassistance", "roadside"]
    result = _tags(texts, t)
    assert all(v == set() for v in result.values())


def test_keyword_tags_phrase_does_not_join_two_clauses() -> None:
    result = _tags(
        ["help on the roadside", "assistance is free"], topic(1, en=["roadside assistance"])
    )
    assert result == {"c1": set(), "c2": set()}


def test_keyword_tags_heading_counts_as_clause_text() -> None:
    cl = [clause(1, "The amount is 5 days.", heading="Franchise"), clause(2, "Other text.")]
    result = keyword_tags(cl, [topic(1, en=["franchise"])])
    assert result == {"c1": {"custom_1"}, "c2": set()}


def test_keyword_tags_phrase_does_not_span_heading_and_text() -> None:
    cl = [clause(1, "assistance is free", heading="roadside")]
    assert keyword_tags(cl, [topic(1, en=["roadside assistance"])]) == {"c1": set()}


def test_keyword_tags_synonym_metacharacters_are_literal() -> None:
    t = topic(1, en=["tax.id"])
    assert _tags(["taxxid", "tax-id", "taxid"], t) == {"c1": set(), "c2": set(), "c3": set()}
    assert _tags(["See tax.id here"], t)["c1"] == {"custom_1"}


def test_keyword_tags_synonym_with_regex_syntax_does_not_raise() -> None:
    t = topic(1, en=["a.b.c", "(cover", "cover)", "x/y/z", "100%"])
    result = _tags(["axbxc cover xyz 100 percent"], t)
    assert result["c1"] in (set(), {"custom_1"})


def test_keyword_tags_languages_are_all_used_whatever_the_text() -> None:
    t = topic(1, en=["franchise"], uk=["франшиз"], ru=["неустойк"])
    assert _tags(["неустойка"], t)["c1"] == {"custom_1"}
    assert _tags(["франшиза"], t)["c1"] == {"custom_1"}


def test_keyword_tags_does_not_modify_inputs_and_is_repeatable() -> None:
    cl = [clause(1, "franchise")]
    t = [topic(1, en=["franchise"])]
    assert keyword_tags(cl, t) == keyword_tags(cl, t)
    assert cl[0].text == "franchise"


def test_keyword_rules_version_is_a_string() -> None:
    assert isinstance(KEYWORD_RULES_VERSION, str) and KEYWORD_RULES_VERSION
