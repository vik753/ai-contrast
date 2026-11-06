"""Number check and verified values (ADR 0019 point 3.3 number_mismatch, point 3.4)."""

from decimal import Decimal

import pytest

from app.analysis.verify import (
    DocFlag,
    NumericValue,
    Reason,
    ValueIn,
    ValueStatus,
    verify_value,
)

from .helpers import DAYS10, LANG_IDS, LANGS, c, ctx, ev


def nv(n: str, unit: str) -> NumericValue:
    return NumericValue(Decimal(n), unit)


def check(text: str, value: NumericValue, quote: str | None = None):  # type: ignore[no-untyped-def]
    q = quote if quote is not None else text
    return verify_value(ctx(c("c1", text)), ValueIn("a1", (ev("c1", q),), number=value))


OK = [
    ("The insurer pays within 10 days of notice.", nv("10", "days")),
    ("Страховик сплачує протягом 10 днів з дня повідомлення.", nv("10", "days")),
    ("Страховщик платит в течение 10 дней со дня уведомления.", nv("10", "days")),
    ("The insurer pays within 5 working days of notice.", nv("5", "working_days")),
    ("The deductible is 2,5 % of the sum.", nv("2.5", "percent")),
    ("The deductible is 2.5% of the sum.", nv("2.5", "percent")),
    ("Франшиза становить 2,5% від суми.", nv("2.5", "percent")),
    ("Франшиза составляет 2,5% от суммы.", nv("2.5", "percent")),
    ("The limit is 100 000 UAH per event.", nv("100000", "UAH")),
    ("The limit is 1 000 000 UAH per event.", nv("1000000", "UAH")),
    ("The insurer pays within ten days of notice.", nv("10", "days")),
    ("The insurer pays within ten (10) days of notice.", nv("10", "days")),
    ("Страховик сплачує протягом десять (10) днів з дня повідомлення.", nv("10", "days")),
    ("Страховщик платит в течение десять (10) дней со дня уведомления.", nv("10", "days")),
    ("The insurer pays within 10 days and a penalty of 5% applies.", nv("10", "days")),
]


@pytest.mark.parametrize(("text", "value"), OK)
def test_number_check_accepts_matching_forms(text: str, value: NumericValue) -> None:
    assert check(text, value).status is ValueStatus.verified


BAD = [
    ("The insurer pays within 15 days of notice.", nv("10", "days")),
    ("Страховик сплачує протягом 15 днів з дня повідомлення.", nv("10", "days")),
    ("Страховщик платит в течение 15 дней со дня уведомления.", nv("10", "days")),
    ("The insurer pays within 10 months of notice.", nv("10", "days")),
    ("The insurer pays within 10 days of notice.", nv("10", "months")),
    ("The insurer pays within 10 days, but not later than 30 days.", nv("10", "days")),
    ("Страховик платить протягом 10 днів, але не пізніше 30 днів.", nv("10", "days")),
    ("Страховщик платит в течение 10 дней, но не позднее 30 дней.", nv("10", "days")),
    ("The deductible is 25% of the sum.", nv("2.5", "percent")),
    ("The deductible is 2,5 % of the sum.", nv("25", "percent")),
    ("The limit is 100 000 UAH per event.", nv("100", "UAH")),
    ("The limit is 1 000 UAH per event.", nv("1000000", "UAH")),
    ("The insurer pays within ten days of notice.", nv("11", "days")),
    ("Страховик сплачує протягом десять (15) днів.", nv("10", "days")),
    ("Страховик сплачує протягом десять (15) днів.", nv("15", "days")),
    ("Страховщик платит в течение десять (15) дней.", nv("10", "days")),
    ("The insurer pays within ten (15) days of notice.", nv("10", "days")),
    ("The insurer pays within 10 days of notice.", nv("10", "UAH")),
]


@pytest.mark.parametrize(("text", "value"), BAD)
def test_number_check_rejects_mismatch(text: str, value: NumericValue) -> None:
    out = check(text, value)
    assert out.status is ValueStatus.not_confirmed and Reason.number_mismatch in out.reasons


def test_several_numbers_of_other_units_do_not_break_the_check() -> None:
    t = "Pay 10 days after 3 months of delay or 5% of 100 000 UAH."
    assert check(t, nv("10", "days")).status is ValueStatus.verified


@pytest.mark.parametrize("lang", LANG_IDS)
def test_value_with_failing_quote_is_not_confirmed(lang: str) -> None:
    L = LANGS[lang]
    out = verify_value(
        ctx(c("c1", L.base)), ValueIn("a1", (ev("c1", "text that is absent"),), number=DAYS10)
    )
    assert out.status is ValueStatus.not_confirmed and Reason.unverified in out.reasons


@pytest.mark.parametrize("lang", LANG_IDS)
def test_value_without_evidence_is_not_confirmed(lang: str) -> None:
    out = verify_value(ctx(c("c1", LANGS[lang].base)), ValueIn("a1", (), number=DAYS10))
    assert out.status is ValueStatus.not_confirmed


@pytest.mark.parametrize("lang", LANG_IDS)
def test_clean_value_is_verified_with_no_reasons(lang: str) -> None:
    L = LANGS[lang]
    out = verify_value(ctx(c("c1", L.base)), ValueIn("a1", (ev("c1", L.quote),), number=DAYS10))
    assert out.status is ValueStatus.verified and out.reasons == ()


@pytest.mark.parametrize("lang", LANG_IDS)
def test_enum_value_without_number_is_verified_by_quote(lang: str) -> None:
    L = LANGS[lang]
    out = verify_value(ctx(c("c1", L.base)), ValueIn("a1", (ev("c1", L.quote),)))
    assert out.status is ValueStatus.verified


CAPS = {
    "exception": (lambda L: dict(clauses=(c("c1", f"{L.base} {L.exc}"),)), Reason.check_exceptions),
    "override": (
        lambda L: dict(clauses=(c("c1", L.base), c("c4", L.glob))),
        Reason.global_override,
    ),
    "layer2": (
        lambda L: dict(clauses=(c("c1", L.base),), layer2_heuristic_clauses=frozenset({"c1"})),
        Reason.suspicious_span,
    ),
    "injection": (
        lambda L: dict(clauses=(c("c1", L.base),), injection=(ev("c1", "zzz"),)),
        Reason.suspicious_span,
    ),
    "flags": (
        lambda L: dict(clauses=(c("c1", L.base),), flags=frozenset({DocFlag.hidden_text_removed})),
        Reason.document_flags,
    ),
    "incomplete": (lambda L: dict(clauses=(c("c1", L.base),), incomplete=True), Reason.incomplete),
}


@pytest.mark.parametrize("lang", LANG_IDS)
@pytest.mark.parametrize("cap", list(CAPS))
@pytest.mark.parametrize("with_number", [True, False])
def test_value_under_any_cap_is_not_confirmed(lang: str, cap: str, with_number: bool) -> None:
    L = LANGS[lang]
    make, reason = CAPS[cap]
    from app.analysis.verify import DocumentContext

    out = verify_value(
        DocumentContext(**make(L)),
        ValueIn("a1", (ev("c1", L.quote),), number=DAYS10 if with_number else None),
    )
    assert out.status is ValueStatus.not_confirmed and reason in out.reasons


@pytest.mark.parametrize("lang", LANG_IDS)
def test_value_with_more_than_five_references_is_not_confirmed(lang: str) -> None:
    from .test_green_rules import _refs

    L = LANGS[lang]
    out = verify_value(ctx(*_refs(lang, 6)), ValueIn("a1", (ev("c1", L.quote),), number=DAYS10))
    assert out.status is ValueStatus.not_confirmed and Reason.too_many_references in out.reasons


@pytest.mark.parametrize("lang", LANG_IDS)
def test_short_quote_does_not_make_a_value_not_confirmed(lang: str) -> None:
    L = LANGS[lang]
    out = verify_value(ctx(c("c1", L.short)), ValueIn("a1", (ev("c1", "10"),), number=DAYS10))
    assert out.status is ValueStatus.verified


@pytest.mark.parametrize("lang", LANG_IDS)
def test_value_in_other_topic_clause_is_not_marked_other_not_green(lang: str) -> None:
    L = LANGS[lang]
    out = verify_value(
        ctx(c("c1", L.base)), ValueIn("a1", (ev("c1", L.quote),), topic=None, number=DAYS10)
    )
    assert out.status is ValueStatus.verified and Reason.other_not_green not in out.reasons
