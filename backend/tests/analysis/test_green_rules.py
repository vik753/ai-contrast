"""Green rules (ADR 0019 point 3.3), each with a positive and a negative test per language."""

import dataclasses

import pytest

from app.analysis.verify import (
    Clause,
    DocFlag,
    Finding,
    Rating,
    Reason,
    apply_green_rules,
)

from .helpers import DAYS10, LANG_IDS, LANGS, c, ctx, ev, green, span_of

pytestmark = pytest.mark.parametrize("lang", LANG_IDS)


def base(lang: str, **kw: object):  # type: ignore[no-untyped-def]
    L = LANGS[lang]
    cl = c("c1", L.base, number="1.1")
    out = apply_green_rules(ctx(cl, **kw), green("c1", L.quote, value=DAYS10))
    return L, cl, out


def test_baseline_clean_green_stays_green(lang: str) -> None:
    _, cl, out = base(lang)
    assert out.rating is Rating.green and out.reasons == ()
    assert out.verified_spans == (("c1", 0, len(cl.text)),)
    assert not out.unverified and out.dropped_quotes == 0


def test_result_holds_offsets_and_ids_never_text(lang: str) -> None:
    L, _, out = base(lang, topic_clauses={"t1": frozenset({"c1"})})
    allowed = {"c1", "t1"} | {r.value for r in Reason} | {r.value for r in Rating}

    def walk(o: object) -> None:
        if isinstance(o, str):
            assert o in allowed, o
        elif isinstance(o, tuple | list | frozenset):
            for x in o:
                walk(x)
        elif dataclasses.is_dataclass(o):
            for f in dataclasses.fields(o):
                walk(getattr(o, f.name))

    walk(out)


# quote_too_short
def test_quote_too_short_sentence_under_25_chars_caps(lang: str) -> None:
    L = LANGS[lang]
    out = apply_green_rules(ctx(c("c1", L.short)), green("c1", "10"))
    assert out.rating is Rating.yellow and Reason.quote_too_short in out.reasons


def test_quote_too_short_short_quote_in_long_sentence_is_fine(lang: str) -> None:
    L = LANGS[lang]
    out = apply_green_rules(ctx(c("c1", L.base)), green("c1", "10"))
    assert out.rating is Rating.green


def test_repeated_quote_every_occurrence_is_checked(lang: str) -> None:
    L = LANGS[lang]
    cl = c("c1", f"{L.short} {L.base}")
    out = apply_green_rules(ctx(cl), green("c1", "10"))
    assert len(out.verified_spans) == 2
    assert out.rating is Rating.yellow and Reason.quote_too_short in out.reasons


# unverified / dropped quotes
def test_no_verified_quote_is_unverified_and_never_green(lang: str) -> None:
    L = LANGS[lang]
    out = apply_green_rules(ctx(c("c1", L.base)), green("c1", "not in the text anywhere at all"))
    assert out.unverified and out.rating is Rating.yellow and Reason.unverified in out.reasons
    assert out.verified_spans == ()


def test_one_bad_quote_is_dropped_the_good_one_counts(lang: str) -> None:
    L = LANGS[lang]
    f = Finding(Rating.green, (ev("c1", L.quote), ev("c1", "zzz nothing")), "t1", "a1", DAYS10)
    out = apply_green_rules(ctx(c("c1", L.base)), f)
    assert out.dropped_quotes == 1 and not out.unverified and out.rating is Rating.green


def test_quote_on_unknown_clause_is_dropped(lang: str) -> None:
    L = LANGS[lang]
    out = apply_green_rules(ctx(c("c1", L.base)), green("c9", L.quote))
    assert out.unverified and out.rating is Rating.yellow


# suspicious_span
def test_layer2_span_overlapping_quote_caps(lang: str) -> None:
    L = LANGS[lang]
    cl = c("c1", L.base)
    s, e = span_of(cl, L.quote)
    out = apply_green_rules(ctx(cl, layer2_spans=(("c1", s + 2, e - 2),)), green("c1", L.quote))
    assert Reason.suspicious_span in out.reasons and out.rating is Rating.yellow


def test_layer2_span_outside_quote_does_not_cap(lang: str) -> None:
    L = LANGS[lang]
    cl = c("c1", L.base)
    s, _ = span_of(cl, L.quote)
    out = apply_green_rules(ctx(cl, layer2_spans=(("c1", 0, s - 1),)), green("c1", L.quote))
    assert out.rating is Rating.green


def test_layer2_span_in_other_clause_does_not_cap(lang: str) -> None:
    L = LANGS[lang]
    out = apply_green_rules(
        ctx(c("c1", L.base), c("c2", L.base), layer2_spans=(("c2", 0, 10),)), green("c1", L.quote)
    )
    assert out.rating is Rating.green


def test_heuristic_layer2_hit_in_clause_caps(lang: str) -> None:
    L = LANGS[lang]
    out = apply_green_rules(
        ctx(c("c1", L.base), layer2_heuristic_clauses=frozenset({"c1"})), green("c1", L.quote)
    )
    assert Reason.suspicious_span in out.reasons


def test_injection_item_with_valid_clause_id_blocks_green_even_with_bad_quote(lang: str) -> None:
    L = LANGS[lang]
    out = apply_green_rules(
        ctx(c("c1", L.base), injection=(ev("c1", "quote that is not in the text"),)),
        green("c1", L.quote),
    )
    assert out.rating is Rating.yellow and Reason.suspicious_span in out.reasons


def test_injection_item_overlapping_quote_blocks_green(lang: str) -> None:
    L = LANGS[lang]
    out = apply_green_rules(
        ctx(c("c1", L.base), injection=(ev("c1", L.quote),)), green("c1", L.quote)
    )
    assert Reason.suspicious_span in out.reasons


@pytest.mark.parametrize("other", ["c2", "c99"])
def test_injection_item_for_other_or_unknown_clause_does_not_block(lang: str, other: str) -> None:
    L = LANGS[lang]
    out = apply_green_rules(
        ctx(c("c1", L.base), c("c2", L.base), injection=(ev(other, "x"),)), green("c1", L.quote)
    )
    assert out.rating is Rating.green


# check_exceptions
def test_exception_in_text_after_quote_caps_and_attaches_clause(lang: str) -> None:
    L = LANGS[lang]
    cl = c("c1", f"{L.base} {L.exc}")
    out = apply_green_rules(ctx(cl), green("c1", L.quote))
    assert out.rating is Rating.yellow and Reason.check_exceptions in out.reasons
    assert any(a[0] == "c1" for a in out.attached)


def test_exception_in_text_before_quote_caps(lang: str) -> None:
    L = LANGS[lang]
    out = apply_green_rules(ctx(c("c1", f"{L.exc} {L.base}")), green("c1", L.quote))
    assert Reason.check_exceptions in out.reasons


def test_exception_in_heading_of_quoted_clause_caps(lang: str) -> None:
    L = LANGS[lang]
    cl = c("c1", L.base, heading=L.heading_exc)
    out = apply_green_rules(ctx(cl), green("c1", L.quote))
    assert Reason.check_exceptions in out.reasons


def test_no_exception_anywhere_in_clause_does_not_cap(lang: str) -> None:
    L = LANGS[lang]
    out = apply_green_rules(ctx(c("c1", L.base, heading="Payment")), green("c1", L.quote))
    assert Reason.check_exceptions not in out.reasons


def test_other_clause_referring_to_quoted_clause_by_number_caps(lang: str) -> None:
    L = LANGS[lang]
    out = apply_green_rules(
        ctx(c("c1", L.base, number="1.1"), c("c2", L.refto, number="2")), green("c1", L.quote)
    )
    assert Reason.check_exceptions in out.reasons
    assert any(a[0] == "c2" for a in out.attached)


def test_reference_to_a_different_number_with_same_prefix_does_not_cap(lang: str) -> None:
    L = LANGS[lang]
    out = apply_green_rules(
        ctx(
            c("c1", L.base, number="1.1"),
            c("c2", L.refnear, number="2"),
            c("c3", L.base, number="1.10"),
        ),
        green("c1", L.quote),
    )
    assert out.rating is Rating.green


def test_same_topic_clause_with_exception_marker_caps(lang: str) -> None:
    L = LANGS[lang]
    out = apply_green_rules(
        ctx(
            c("c1", L.base),
            c("c3", L.exc),
            topic_clauses={"t1": frozenset({"c1", "c3"})},
        ),
        green("c1", L.quote),
    )
    assert Reason.check_exceptions in out.reasons
    assert any(a[0] == "c3" for a in out.attached)


def test_exception_clause_of_another_topic_without_reference_does_not_cap(lang: str) -> None:
    L = LANGS[lang]
    out = apply_green_rules(
        ctx(
            c("c1", L.base),
            c("c3", L.exc),
            topic_clauses={"t1": frozenset({"c1"}), "t2": frozenset({"c3"})},
        ),
        green("c1", L.quote),
    )
    assert out.rating is Rating.green


# global_override
def test_global_override_in_any_clause_caps_every_green(lang: str) -> None:
    L = LANGS[lang]
    cx = ctx(c("c1", L.base), c("c2", L.base), c("c4", L.glob))
    for cid in ("c1", "c2"):
        out = apply_green_rules(cx, green(cid, L.quote))
        assert out.rating is Rating.yellow and Reason.global_override in out.reasons
        assert any(a[0] == "c4" for a in out.attached)


def test_no_global_override_does_not_cap(lang: str) -> None:
    L = LANGS[lang]
    out = apply_green_rules(ctx(c("c1", L.base), c("c4", L.short)), green("c1", L.quote))
    assert Reason.global_override not in out.reasons


# too_many_references
def _refs(lang: str, n: int) -> tuple[Clause, ...]:
    L = LANGS[lang]
    ref_text = " ".join(L.ref.format(n=i) for i in range(2, 2 + n))
    return (
        c("c1", f"{L.base} {ref_text}", number="1.1"),
        *(c(f"r{i}", L.short, number=str(i)) for i in range(2, 2 + n)),
    )


def test_closure_over_five_clauses_caps(lang: str) -> None:
    out = apply_green_rules(ctx(*_refs(lang, 6)), green("c1", LANGS[lang].quote))
    assert Reason.too_many_references in out.reasons and out.rating is Rating.yellow


def test_closure_of_exactly_five_clauses_does_not_cap(lang: str) -> None:
    out = apply_green_rules(ctx(*_refs(lang, 5)), green("c1", LANGS[lang].quote))
    assert Reason.too_many_references not in out.reasons and out.rating is Rating.green


# number_mismatch
def test_number_mismatch_different_number_caps(lang: str) -> None:
    L = LANGS[lang]
    out = apply_green_rules(
        ctx(c("c1", L.fifteen)), green("c1", L.quote.replace("10", "15"), value=DAYS10)
    )
    assert Reason.number_mismatch in out.reasons and out.rating is Rating.yellow


def test_number_mismatch_two_numbers_of_one_unit_caps(lang: str) -> None:
    L = LANGS[lang]
    out = apply_green_rules(ctx(c("c1", L.two)), green("c1", "10", value=DAYS10))
    assert Reason.number_mismatch in out.reasons


def test_number_in_words_and_digits_matching_passes(lang: str) -> None:
    L = LANGS[lang]
    out = apply_green_rules(ctx(c("c1", L.words)), green("c1", "10", value=DAYS10))
    assert Reason.number_mismatch not in out.reasons and out.rating is Rating.green


def test_finding_without_numeric_value_has_no_number_check(lang: str) -> None:
    L = LANGS[lang]
    out = apply_green_rules(ctx(c("c1", L.two)), green("c1", "10", value=None))
    assert Reason.number_mismatch not in out.reasons


# document_flags
@pytest.mark.parametrize("flag", list(DocFlag))
def test_document_flag_removes_every_green(lang: str, flag: DocFlag) -> None:
    L = LANGS[lang]
    out = apply_green_rules(ctx(c("c1", L.base), flags=frozenset({flag})), green("c1", L.quote))
    assert out.rating is Rating.yellow and Reason.document_flags in out.reasons


def test_unprovided_reference_caps_only_that_clause(lang: str) -> None:
    L = LANGS[lang]
    cx = ctx(c("c1", L.base), c("c2", L.base), unprovided_reference_clauses=frozenset({"c1"}))
    assert Reason.document_flags in apply_green_rules(cx, green("c1", L.quote)).reasons
    assert apply_green_rules(cx, green("c2", L.quote)).rating is Rating.green


def test_no_flags_no_cap(lang: str) -> None:
    _, _, out = base(lang)
    assert Reason.document_flags not in out.reasons


# other_not_green
def test_other_finding_green_becomes_yellow_other_not_green(lang: str) -> None:
    L = LANGS[lang]
    out = apply_green_rules(ctx(c("c1", L.base)), green("c1", L.quote, topic=None))
    assert out.rating is Rating.yellow and Reason.other_not_green in out.reasons


@pytest.mark.parametrize("r", [Rating.yellow, Rating.red])
def test_other_finding_non_green_is_unchanged_without_reason(lang: str, r: Rating) -> None:
    L = LANGS[lang]
    f = Finding(r, (ev("c1", L.quote),), None)
    out = apply_green_rules(ctx(c("c1", L.base)), f)
    assert out.rating is r and Reason.other_not_green not in out.reasons


def test_topic_finding_is_not_marked_other_not_green(lang: str) -> None:
    _, _, out = base(lang)
    assert Reason.other_not_green not in out.reasons


# incomplete document
def test_incomplete_document_has_no_green(lang: str) -> None:
    L = LANGS[lang]
    out = apply_green_rules(ctx(c("c1", L.base), incomplete=True), green("c1", L.quote))
    assert out.rating is Rating.yellow and Reason.incomplete in out.reasons


# the model cannot lift a cap, caps touch only greens
@pytest.mark.parametrize("r", [Rating.yellow, Rating.red])
def test_non_green_is_never_changed_by_caps_or_raised(lang: str, r: Rating) -> None:
    L = LANGS[lang]
    clean = apply_green_rules(ctx(c("c1", L.base)), Finding(r, (ev("c1", L.quote),), "t1"))
    capped = apply_green_rules(
        ctx(c("c1", f"{L.base} {L.exc}"), c("c4", L.glob), flags=frozenset(DocFlag)),
        Finding(r, (ev("c1", L.quote),), "t1"),
    )
    assert clean.rating is r and capped.rating is r


def test_several_caps_collect_all_reasons(lang: str) -> None:
    L = LANGS[lang]
    cx = ctx(
        c("c1", f"{L.base} {L.exc}"), c("c4", L.glob), flags=frozenset({DocFlag.not_read_material})
    )
    out = apply_green_rules(cx, green("c1", L.quote))
    assert {Reason.check_exceptions, Reason.global_override, Reason.document_flags} <= set(
        out.reasons
    )
