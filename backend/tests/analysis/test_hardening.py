# ruff: noqa: RUF001
"""Hardening tests from the S9-T0 security review: normalization, references, numbers."""

import pytest

from app.analysis.verify import (
    Rating,
    Reason,
    ValueIn,
    ValueStatus,
    apply_green_rules,
    reference_closure,
    verify_value,
)

from .helpers import DAYS10, LANGS, c, ctx, ev, green
from .test_values import nv

# Each case: (lang, sentence with an obfuscated marker).
EXC = [
    ("en", "Nоtwithstanding any other provision of this contract, the insurer decides."),
    ("en", "Notwithstanding‑any other provision of this contract, the insurer decides."),
    ("en", "Ｅｘｃｅｐｔ in cases of intent, the insurer pays."),
    ("en", "Excеpt in cases of intent, the insurer pays."),
    ("uk", "Кpiм випадків умислу, страховик сплачує."),
    ("uk", "За виняткoм випадків умислу, страховик сплачує."),
    ("uk", "Незважаючи на будь‑які інші положення цього договору, страховик вирішує."),
    ("ru", "За исключением случаев умысла, страховщик платит."),
    ("ru", "За иcключением случаев умысла, страховщик платит."),
    ("ru", "За исключением случаев умысла, страховщик платит."),
]
EXC_PLAIN = [
    ("en", "Except in cases of intent, the insurer pays."),
    ("uk", "Крім випадків умислу, страховик сплачує."),
    ("uk", "Незважаючи на будь-які інші положення цього договору, страховик вирішує."),
    ("ru", "За исключением случаев умысла, страховщик платит."),
]


@pytest.mark.parametrize(("lang", "sentence"), EXC_PLAIN + EXC, ids=lambda x: str(x)[:30])
def test_marker_matches_through_lookalikes_and_variants(lang: str, sentence: str) -> None:
    lx = LANGS[lang]
    out = apply_green_rules(ctx(c("c1", f"{lx.base} {sentence}")), green("c1", lx.quote))
    assert out.rating is Rating.yellow
    assert {Reason.check_exceptions, Reason.global_override} & set(out.reasons)


@pytest.mark.parametrize("lang", ["en", "uk", "ru"])
def test_global_override_lookalike_in_other_clause_caps(lang: str) -> None:
    lx = LANGS[lang]
    glob = {
        "en": "Nоtwithstanding any other provision of this contract, the insurer decides.",
        "uk": "Цей пункт має переваж\u0061ну силу над іншими положеннями договору.",
        "ru": "Настоящий пункт имеет преимущественную силу над другими положениями.",
    }[lang]
    out = apply_green_rules(ctx(c("c1", lx.base), c("c4", glob)), green("c1", lx.quote))
    assert Reason.global_override in out.reasons


@pytest.mark.parametrize("apos", ["'", "’", "ʼ", "`", "＇"])
def test_uk_number_word_with_any_apostrophe_is_parsed(apos: str) -> None:
    text = f"Страховик сплачує протягом п{apos}ять днів з дня повідомлення."
    out = verify_value(ctx(c("c1", text)), ValueIn("a", (ev("c1", text),), number=nv("5", "days")))
    assert out.status is ValueStatus.verified


@pytest.mark.parametrize(
    ("lang", "text", "num", "unit"),
    [
        ("en", "The insurer pays within 10 dаys of notice.", "10", "days"),
        ("en", "The insurer pays within １０ days of notice.", "10", "days"),
        ("uk", "Страховик сплачує протягом 10 днiв з дня повідомлення.", "10", "days"),
        ("uk", "Страховик сплачує протягом １０ днів з дня повідомлення.", "10", "days"),
        ("ru", "Страховщик платит в течение 10 дней со дня уведомления.", "10", "days"),
        ("ru", "Страховщик платит в течение １０ дней со дня уведомления.", "10", "days"),
    ],
)
def test_unit_words_and_digits_match_through_variants(
    lang: str, text: str, num: str, unit: str
) -> None:
    assert lang in LANGS
    out = verify_value(ctx(c("c1", text)), ValueIn("a", (ev("c1", text),), number=nv(num, unit)))
    assert out.status is ValueStatus.verified


@pytest.mark.parametrize(
    ("lang", "ref"),
    [
        ("en", "Payment under clаuse 1.1 is limited."),
        ("en", "Payment under ｃlause 1.1 is limited."),
        ("uk", "Виплата за п． １．１ обмежена."),
        ("uk", "Виплата за пункту 1.1 обмежена."),
        ("ru", "Выплата по п． 1.1 ограничена."),
        ("ru", "Выплата по пункту １.１ ограничена."),
    ],
)
def test_reference_to_quoted_clause_through_variants_caps(lang: str, ref: str) -> None:
    lx = LANGS[lang]
    out = apply_green_rules(
        ctx(c("c1", lx.base, number="1.1"), c("c2", ref, number="2")), green("c1", lx.quote)
    )
    assert Reason.check_exceptions in out.reasons


def test_reference_closure_normalizes_variants() -> None:
    cl = [c("a", "See clаuse ４.2.", number="1"), c("b", "Body.", number="4.2")]
    assert reference_closure(cl, ["a"])["a"].added == ("b",)


# 2. References without prefix word, ranges
@pytest.mark.parametrize(
    "text",
    ["Payment as in 4.2 above.", "Виплата як у 4.2, і далі.", "Выплата как в 4.2, и далее."],
)
def test_dotted_number_without_prefix_word_is_a_reference(text: str) -> None:
    cl = [c("a", text, number="1"), c("b", "Body.", number="4.2")]
    assert reference_closure(cl, ["a"])["a"].added == ("b",)


def test_dotted_number_matching_no_clause_is_not_a_reference() -> None:
    cl = [
        c("a", "The rate is 2.5 percent and costs 3.75 UAH.", number="1"),
        c("b", "x", number="4.2"),
    ]
    assert reference_closure(cl, ["a"])["a"].added == ()


RANGE = [
    "See 4.1–4.3.",
    "See 4.1-4.3.",
    "See 4.1 – 4.3.",
    "Див. з 4.1 по 4.3.",
    "См. с 4.1 по 4.3.",
]


@pytest.mark.parametrize("text", RANGE)
def test_range_expands_to_existing_clauses_in_range(text: str) -> None:
    nums = ["4.0", "4.1", "4.2", "4.3", "4.4"]
    cl = [c("a", text, number="1"), *(c(f"n{n}", "x", number=n) for n in nums)]
    e = reference_closure(cl, ["a"])["a"]
    assert set(e.added) == {"n4.1", "n4.2", "n4.3"}
    assert e.needed == 3


def test_range_with_missing_end_clause_expands_to_existing_ones() -> None:
    cl = [
        c("a", "See 4.1-4.9.", number="1"),
        *(c(f"n{i}", "x", number=f"4.{i}") for i in (1, 2, 3)),
    ]
    assert reference_closure(cl, ["a"])["a"].needed == 3


def test_range_counts_toward_limit() -> None:
    cl = [
        c("a", "See 4.1-4.9.", number="1"),
        *(c(f"n{i}", "x", number=f"4.{i}") for i in range(1, 10)),
    ]
    e = reference_closure(cl, ["a"])["a"]
    assert e.too_many
    assert e.needed == 9
    assert len(e.added) <= 5


def test_range_of_five_is_not_too_many() -> None:
    cl = [
        c("a", "See 4.1-4.5.", number="1"),
        *(c(f"n{i}", "x", number=f"4.{i}") for i in range(1, 6)),
    ]
    e = reference_closure(cl, ["a"])["a"]
    assert not e.too_many
    assert len(e.added) == 5


def test_range_plus_single_reference_are_added_together() -> None:
    cl = [
        c("a", "See 4.1-4.2 and clause 7.", number="1"),
        c("p", "x", number="4.1"),
        c("q", "x", number="4.2"),
        c("r", "x", number="7"),
    ]
    assert reference_closure(cl, ["a"])["a"].needed == 3


@pytest.mark.parametrize(
    ("lang", "text"),
    [
        ("en", "Provisions 3.2 do not apply."),
        ("uk", "Положення 3.2 не застосовуються."),
        ("ru", "Положения 3.2 не применяются."),
    ],
)
def test_other_clause_naming_the_number_without_prefix_caps_green(lang: str, text: str) -> None:
    lx = LANGS[lang]
    out = apply_green_rules(
        ctx(c("c1", lx.base, number="3.2"), c("c2", text, number="9")), green("c1", lx.quote)
    )
    assert out.rating is Rating.yellow
    assert Reason.check_exceptions in out.reasons
    assert any(a[0] == "c2" for a in out.attached)


def test_range_in_other_clause_covering_quoted_clause_caps_green() -> None:
    lx = LANGS["en"]
    out = apply_green_rules(
        ctx(
            c("c1", lx.base, number="3.2"),
            c("c2", "Sections 3.1-3.3 are void.", number="9"),
            c("c3", "x", number="3.1"),
            c("c4", "x", number="3.3"),
        ),
        green("c1", lx.quote),
    )
    assert Reason.check_exceptions in out.reasons


# 3. unresolved_reference
UNRESOLVED = [
    ("en", "The conditions are as set out above."),
    ("uk", "Умови визначені згідно з Правилами страхування."),
    ("ru", "Условия определены в указанных выше документах."),
]


@pytest.mark.parametrize(("lang", "sentence"), UNRESOLVED)
def test_relative_or_external_reference_in_quoted_clause_caps(lang: str, sentence: str) -> None:
    lx = LANGS[lang]
    out = apply_green_rules(ctx(c("c1", f"{lx.base} {sentence}")), green("c1", lx.quote))
    assert out.rating is Rating.yellow
    assert Reason.unresolved_reference in out.reasons


@pytest.mark.parametrize("lang", ["en", "uk", "ru"])
def test_clause_without_relative_reference_is_not_unresolved(lang: str) -> None:
    lx = LANGS[lang]
    out = apply_green_rules(ctx(c("c1", lx.base)), green("c1", lx.quote))
    assert Reason.unresolved_reference not in out.reasons
    assert out.rating is Rating.green


def test_unresolved_reference_in_other_clause_does_not_cap() -> None:
    lx = LANGS["en"]
    out = apply_green_rules(
        ctx(c("c1", lx.base), c("c2", "Terms are as set out above.")), green("c1", lx.quote)
    )
    assert Reason.unresolved_reference not in out.reasons


# 4. unparseable number words and contradicting words
UNPARSED = [
    ("en", "The insurer pays within two hundred days of notice.", "200", "days"),
    ("en", "The insurer pays within half a month of notice.", "0.5", "months"),
    ("uk", "Страховик сплачує протягом півтора місяця з дня повідомлення.", "1.5", "months"),
    ("ru", "Страховщик платит в течение полтора месяца со дня уведомления.", "1.5", "months"),
]


@pytest.mark.parametrize(("lang", "text", "num", "unit"), UNPARSED)
def test_unparseable_number_word_next_to_unit_is_mismatch(
    lang: str, text: str, num: str, unit: str
) -> None:
    assert lang in LANGS
    out = verify_value(ctx(c("c1", text)), ValueIn("a", (ev("c1", text),), number=nv(num, unit)))
    assert out.status is ValueStatus.not_confirmed
    assert Reason.number_mismatch in out.reasons


@pytest.mark.parametrize("lang", ["en", "uk", "ru"])
def test_unparseable_number_word_caps_green_with_number_mismatch(lang: str) -> None:
    text = {u[0]: u[1] for u in UNPARSED if u[3] == "months"}.get(lang, UNPARSED[0][1])
    unit = "months" if lang != "en" else "days"
    out = apply_green_rules(
        ctx(c("c1", text)), green("c1", text[: len(text) - 1], value=nv("10", unit))
    )
    assert Reason.number_mismatch in out.reasons


@pytest.mark.parametrize("value", ["10", "45"])
@pytest.mark.parametrize(
    "text",
    [
        "The insurer pays within ten (45) days of notice.",
        "Страховик сплачує протягом десять (45) днів з дня повідомлення.",
        "Страховщик платит в течение десять (45) дней со дня уведомления.",
    ],
)
def test_words_contradicting_digits_are_mismatch_for_any_value(text: str, value: str) -> None:
    out = verify_value(
        ctx(c("c1", text)), ValueIn("a", (ev("c1", text),), number=nv(value, "days"))
    )
    assert out.status is ValueStatus.not_confirmed
    assert Reason.number_mismatch in out.reasons


def test_clean_value_still_verified_next_to_new_checks() -> None:
    lx = LANGS["en"]
    out = verify_value(ctx(c("c1", lx.base)), ValueIn("a", (ev("c1", lx.quote),), number=DAYS10))
    assert out.status is ValueStatus.verified


@pytest.mark.parametrize(
    "sentence",
    [
        "Условия определены в размещённых выше документах.",
        "Условия определены в размещенных выше документах.",
        "УСЛОВИЯ ОПРЕДЕЛЕНЫ В РАЗМЕЩЁННЫХ ВЫШЕ ДОКУМЕНТАХ.",
    ],
)
def test_yo_and_ye_spellings_match_the_same_relative_reference(sentence: str) -> None:
    lx = LANGS["ru"]
    out = apply_green_rules(ctx(c("c1", f"{lx.base} {sentence}")), green("c1", lx.quote))
    assert Reason.unresolved_reference in out.reasons


SELF_REF = [
    ("en", "The deadline in this section may be changed."),
    ("uk", "Строк згідно з умовами цього розділу може бути змінений."),
    ("ru", "Срок согласно условиям настоящего раздела может быть изменён."),
]


@pytest.mark.parametrize(("lang", "sentence"), SELF_REF)
def test_self_reference_phrase_caps_green_as_unresolved_reference(lang: str, sentence: str) -> None:
    lx = LANGS[lang]
    out = apply_green_rules(ctx(c("c1", f"{lx.base} {sentence}")), green("c1", lx.quote))
    assert out.rating is Rating.yellow
    assert Reason.unresolved_reference in out.reasons
