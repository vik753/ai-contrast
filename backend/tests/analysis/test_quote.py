"""Quote check and expansion (ADR 0019 point 3.1, 3.2)."""

import dataclasses
import pytest

from app.analysis.verify import Clause, Evidence, expand_quote, verify_quote

from .helpers import c


def test_verify_quote_exact_match_returns_offsets() -> None:
    cl = c("c1", "Pay within 10 days of notice.")
    r = verify_quote(cl, "within 10 days")
    assert r.ok and r.spans == ((4, 18),)


def test_verify_quote_whitespace_runs_in_quote_fold_to_one_space() -> None:
    cl = c("c1", "Pay within 10 days of notice.")
    assert verify_quote(cl, "within   10\n\tdays").ok


def test_verify_quote_whitespace_runs_in_text_fold_and_offsets_use_original_text() -> None:
    cl = c("c1", "Pay within  10 \n days of notice.")
    r = verify_quote(cl, "within 10 days")
    assert r.ok
    ((s, e),) = r.spans
    assert cl.text[s:e] == "within  10 \n days"


def test_verify_quote_case_is_not_folded() -> None:
    assert not verify_quote(c("c1", "Pay within 10 days."), "WITHIN 10 DAYS").ok


@pytest.mark.parametrize(
    ("text", "quote"),
    [
        ("Pay within 10 days", "Pay within 10 days."),
        ("Pay within 10 days.", "Pay within 10 days"),  # sub-string is fine, see below
        ("Pay, within 10 days", "Pay within 10 days"),
        ("He said “ten days”", 'said "ten days"'),
    ],
)
def test_verify_quote_punctuation_is_not_folded(text: str, quote: str) -> None:
    ok = verify_quote(c("c1", text), quote).ok
    assert ok == (quote in text)


def test_verify_quote_absent_quote_fails() -> None:
    r = verify_quote(c("c1", "Pay within 10 days."), "within 20 days")
    assert not r.ok and r.spans == ()


@pytest.mark.parametrize("quote", ["", " ", "\n\t"])
def test_verify_quote_empty_or_blank_quote_fails(quote: str) -> None:
    assert not verify_quote(c("c1", "Pay within 10 days."), quote).ok


def test_verify_quote_returns_every_occurrence() -> None:
    cl = c("c1", "In 10 days we act. After 10 days we stop; in 10 days we end.")
    r = verify_quote(cl, "10 days")
    assert [cl.text[s:e] for s, e in r.spans] == ["10 days"] * 3


def test_verify_quote_regex_metacharacters_are_literal() -> None:
    cl = c("c1", "Cost (a.*b) here")
    assert verify_quote(cl, "(a.*b)").ok
    assert not verify_quote(c("c1", "Cost axxb here"), "a.*b").ok
    assert not verify_quote(c("c1", "anything"), ".*").ok


def test_verify_quote_matches_only_cited_clause_text() -> None:
    cl = Clause(id="c1", text="Body text only.", heading="Secret heading words")
    assert not verify_quote(cl, "Secret heading").ok


def test_result_and_inputs_are_frozen() -> None:
    r = verify_quote(c("c1", "abc def"), "abc")
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.ok = False  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        Evidence("c1", "x").quote = "y"  # type: ignore[misc]


def test_expand_quote_to_sentence_inside_clause() -> None:
    t = "First one. The quoted words are here; Third one."
    s = t.index("quoted")
    a, b = expand_quote(t, s, s + 6)
    assert t[a:b] == "The quoted words are here;"


@pytest.mark.parametrize("end", [".", ";", "!", "?"])
def test_expand_quote_stops_at_each_sentence_terminator(end: str) -> None:
    t = f"Before part{end} Middle part here{end} After part{end}"
    s = t.index("Middle")
    a, b = expand_quote(t, s + 7, s + 11)
    assert t[a:b] == f"Middle part here{end}"


def test_expand_quote_last_sentence_ends_at_text_end() -> None:
    t = "One. Two without end"
    a, b = expand_quote(t, 6, 9)
    assert t[a:b] == "Two without end"


def test_expand_quote_covering_two_sentences_keeps_both() -> None:
    t = "A. Bb cc. Dd ee. F."
    a, b = expand_quote(t, 3, 12)
    assert t[a:b] == "Bb cc. Dd ee."


def test_expand_quote_decimal_point_is_not_a_sentence_end() -> None:
    t = "The rate is 2.5 percent of the sum. Next."
    s = t.index("percent")
    a, b = expand_quote(t, s, s + 7)
    assert t[a:b] == "The rate is 2.5 percent of the sum."


def test_expand_quote_dot_before_space_digit_marker_is_not_special() -> None:
    t = "Pay the sum. Fee 5 percent applies."
    s = t.index("percent")
    a, b = expand_quote(t, s, s + 7)
    assert t[a:b] == "Fee 5 percent applies."


@pytest.mark.parametrize(
    ("text", "abbr", "inside", "start_word"),
    [
        ("The fee, e.g. 100 UAH, is paid within 10 days. Next.", "e.g.", "within", "The fee"),
        ("Оплата послуг, штрафи і т.д. входить у вартість. Інше.", "т.д.", "вартість", "Оплата"),
        ("Согласно ст. 5 договора страховщик платит. Дальше.", "ст.", "платит", "Согласно"),
    ],
)
def test_expand_quote_abbreviation_period_is_not_a_sentence_end(
    text: str, abbr: str, inside: str, start_word: str
) -> None:
    s = text.index(inside)
    a, b = expand_quote(text, s, s + len(inside), abbreviations=frozenset({abbr}))
    assert text[a:b].startswith(start_word)
    assert text[a:b].endswith(".") and "Next" not in text[a:b] and "Дальше" not in text[a:b]


def test_expand_quote_without_that_abbreviation_the_period_ends_the_sentence() -> None:
    text = "Согласно ст. 5 договора страховщик платит. Дальше."
    s = text.index("договора")
    a, b = expand_quote(text, s, s + 8, abbreviations=frozenset())
    assert text[a:b] == "5 договора страховщик платит."


def test_expand_quote_never_leaves_the_text() -> None:
    t = "no terminator at all"
    assert expand_quote(t, 3, 7) == (0, len(t))
