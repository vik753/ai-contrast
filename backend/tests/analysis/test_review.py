# ruff: noqa: RUF001
"""PR #98 review findings (tests first)."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.analysis.verify import (
    Clause,
    Rating,
    Reason,
    ValueIn,
    ValueOut,
    ValueStatus,
    apply_green_rules,
    build_document_index,
    verify_quote,
    verify_value,
)

from .helpers import LANGS, c, ctx, ev, green
from .test_values import nv

BACKEND = Path(__file__).resolve().parents[2]


def value_out(text: str, num: str, unit: str | None) -> ValueOut:
    return verify_value(ctx(c("c1", text)), ValueIn("a", (ev("c1", text),), number=nv(num, unit)))


# 1. parent number covers sub-clauses
PARENT = {
    "en": "Section 4 does not apply if the insurer decides otherwise.",
    "uk": "Розділ 4 не застосовується, якщо страховик вирішить інакше.",
    "ru": "Раздел 4 не применяется, если страховщик решит иначе.",
}


@pytest.mark.parametrize("lang", list(PARENT))
def test_reference_to_parent_number_caps_green_on_subclause(lang: str) -> None:
    lx = LANGS[lang]
    out = apply_green_rules(
        ctx(c("c1", lx.base, number="4.2"), c("c2", PARENT[lang], number="9.1")),
        green("c1", lx.quote),
    )
    assert out.rating is Rating.yellow
    assert Reason.check_exceptions in out.reasons
    assert any(a[0] == "c2" for a in out.attached)


@pytest.mark.parametrize("lang", list(PARENT))
@pytest.mark.parametrize("number", ["40.2", "14.2"])
def test_reference_to_parent_number_is_exact_at_dot_boundary(lang: str, number: str) -> None:
    lx = LANGS[lang]
    out = apply_green_rules(
        ctx(c("c1", lx.base, number=number), c("c2", PARENT[lang], number="9.1")),
        green("c1", lx.quote),
    )
    assert out.rating is Rating.green


# 2. currency + scale
SCALE = [
    ("The limit is USD 10 million per event.", "USD", ["10", "10000000"]),
    ("The limit is $10 million per event.", "USD", ["10", "10000000"]),
    ("The limit is EUR 5 thousand per event.", "EUR", ["5", "5000"]),
    ("Ліміт становить 10 тис. грн за випадок.", "UAH", ["10", "10000"]),
    ("Ліміт становить 10 млн грн за випадок.", "UAH", ["10", "10000000"]),
    ("Лимит составляет 10 тыс. грн за случай.", "UAH", ["10", "10000"]),
    ("The limit is UAH 5k per event.", "UAH", ["5", "5000"]),
    ("The limit is USD 2 bn per event.", "USD", ["2", "2000000000"]),
]


@pytest.mark.parametrize(("text", "unit", "values"), SCALE)
def test_currency_with_scale_word_is_mismatch_for_any_value(
    text: str, unit: str, values: list[str]
) -> None:
    for v in values:
        out = value_out(text, v, unit)
        assert out.status is ValueStatus.not_confirmed
        assert Reason.number_mismatch in out.reasons


# 3. digits then disagreeing words
@pytest.mark.parametrize(
    "text",
    [
        "The insurer pays within 10 (eleven) days of notice.",
        "Страховик сплачує протягом 10 (одинадцять) днів з дня повідомлення.",
        "Страховщик платит в течение 10 (одиннадцать) дней со дня уведомления.",
    ],
)
@pytest.mark.parametrize("value", ["10", "11"])
def test_digits_then_disagreeing_words_are_mismatch(text: str, value: str) -> None:
    out = value_out(text, value, "days")
    assert out.status is ValueStatus.not_confirmed
    assert Reason.number_mismatch in out.reasons


@pytest.mark.parametrize(
    "text",
    [
        "The insurer pays within 10 (ten) days of notice.",
        "Страховик сплачує протягом 10 (десять) днів з дня повідомлення.",
        "Страховщик платит в течение 10 (десять) дней со дня уведомления.",
    ],
)
def test_digits_then_agreeing_words_are_verified(text: str) -> None:
    assert value_out(text, "10", "days").status is ValueStatus.verified


# 4. ranges
RANGES = [
    ("The limit is UAH 1 000–100 000 per event.", "UAH", ["1000", "100000"]),
    ("The deductible is 0–50 % of the sum.", None, ["0", "50"]),
    ("The insurer pays from 5 to 10 days after notice.", "days", ["5", "10"]),
    ("Страховик платить від 5 до 10 днів після повідомлення.", "days", ["5", "10"]),
    ("Страховщик платит от 5 до 10 дней после уведомления.", "days", ["5", "10"]),
]


@pytest.mark.parametrize(("text", "unit", "values"), RANGES)
def test_range_is_mismatch_for_any_value(text: str, unit: str | None, values: list[str]) -> None:
    for v in values:
        out = value_out(text, v, unit)
        assert out.status is ValueStatus.not_confirmed
        assert Reason.number_mismatch in out.reasons


# 10. ambiguous separators
@pytest.mark.parametrize(
    ("text", "values"),
    [
        ("The limit is 1.2,3 UAH per event.", ["1.23", "1.2", "3", "123"]),
        ("The limit is 1,5.2 UAH per event.", ["1.52", "1.5", "5.2", "152"]),
    ],
)
def test_two_different_separators_are_mismatch(text: str, values: list[str]) -> None:
    for v in values:
        assert value_out(text, v, "UAH").status is ValueStatus.not_confirmed


@pytest.mark.parametrize("value", ["5", "100", "5100"])
def test_single_digit_head_then_space_and_three_digits_is_mismatch(value: str) -> None:
    out = value_out("The insurer pays within 5 100 days of notice.", value, "days")
    assert out.status is ValueStatus.not_confirmed
    assert Reason.number_mismatch in out.reasons


# 5. reference in another clause's heading
HEADING = {
    "en": ("Limits of clause 4.2", "Does not apply."),
    "uk": ("Обмеження пункту 4.2", "Не застосовується."),
    "ru": ("Ограничения пункта 4.2", "Не применяется."),
}


@pytest.mark.parametrize("lang", list(HEADING))
def test_reference_in_other_clause_heading_caps_green(lang: str) -> None:
    lx = LANGS[lang]
    head, body = HEADING[lang]
    out = apply_green_rules(
        ctx(c("c1", lx.base, number="4.2"), c("c2", body, number="9", heading=head)),
        green("c1", lx.quote),
    )
    assert Reason.check_exceptions in out.reasons
    assert any(a[0] == "c2" for a in out.attached)


@pytest.mark.parametrize("lang", list(HEADING))
def test_heading_naming_a_different_number_does_not_cap(lang: str) -> None:
    lx = LANGS[lang]
    head, body = HEADING[lang]
    head = head.replace("4.2", "4.20")
    out = apply_green_rules(
        ctx(c("c1", lx.base, number="4.2"), c("c2", body, number="9", heading=head)),
        green("c1", lx.quote),
    )
    assert out.rating is Rating.green


# 6. overlapping occurrences
def test_verify_quote_reports_overlapping_occurrences() -> None:
    r = verify_quote(c("c1", "a" * 32), "a" * 30)
    assert r.spans == ((0, 30), (1, 31), (2, 32))


def test_layer2_overlap_on_second_overlapping_occurrence_blocks_green() -> None:
    cl = c("c1", "a" * 32)
    out = apply_green_rules(ctx(cl, layer2_spans=(("c1", 31, 32),)), green("c1", "a" * 30))
    assert Reason.suspicious_span in out.reasons


# 7. parent body and outgoing closure markers
PARENT_EXC = {
    "en": [
        "Under this section the insurer pays only if the notice is timely.",
        "Except in cases of intent, the insurer pays.",
    ],
    "uk": ["За винятком випадків умислу, страховик сплачує."],
    "ru": ["За исключением случаев умысла, страховщик платит."],
}


@pytest.mark.parametrize(("lang", "sentence"), [(k, s) for k, v in PARENT_EXC.items() for s in v])
def test_exception_marker_in_parent_clause_body_caps_subclause(lang: str, sentence: str) -> None:
    lx = LANGS[lang]
    out = apply_green_rules(
        ctx(c("p", sentence, number="4"), c("c1", lx.base, number="4.1")), green("c1", lx.quote)
    )
    assert Reason.check_exceptions in out.reasons
    assert any(a[0] == "p" for a in out.attached)


@pytest.mark.parametrize("lang", list(PARENT_EXC))
def test_exception_marker_in_unrelated_number_does_not_cap(lang: str) -> None:
    lx = LANGS[lang]
    out = apply_green_rules(
        ctx(c("p", PARENT_EXC[lang][-1], number="40"), c("c1", lx.base, number="4.1")),
        green("c1", lx.quote),
    )
    assert out.rating is Rating.green


@pytest.mark.parametrize("lang", list(PARENT_EXC))
def test_exception_marker_in_outgoing_reference_closure_caps(lang: str) -> None:
    lx = LANGS[lang]
    out = apply_green_rules(
        ctx(
            c("c1", f"{lx.base} {lx.ref.format(n='8')}", number="1.1"),
            c("c8", PARENT_EXC[lang][-1], number="8"),
        ),
        green("c1", lx.quote),
    )
    assert Reason.check_exceptions in out.reasons
    assert any(a[0] == "c8" for a in out.attached)


@pytest.mark.parametrize("lang", list(PARENT_EXC))
def test_clean_outgoing_reference_closure_does_not_cap(lang: str) -> None:
    lx = LANGS[lang]
    out = apply_green_rules(
        ctx(
            c("c1", f"{lx.base} {lx.ref.format(n='8')}", number="1.1"),
            c("c8", lx.short, number="8"),
        ),
        green("c1", lx.quote),
    )
    assert out.rating is Rating.green


# 8. startup loads the lexicon
def _import_main(lexicon_dir: Path | None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "LEXICON_DIR"}
    env.update({"ENVIRONMENT": "development", "ALLOWED_ORIGINS": "http://localhost:5173"})
    if lexicon_dir is not None:
        env["LEXICON_DIR"] = str(lexicon_dir)
    return subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=BACKEND,
        env={**env, "PYTHONPATH": str(BACKEND)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_importing_app_main_with_bad_lexicon_dir_fails(tmp_path: Path) -> None:
    r = _import_main(tmp_path)
    assert r.returncode != 0
    assert "LexiconError" in r.stderr
    assert "ModuleNotFoundError" not in r.stderr


def test_importing_app_main_with_default_lexicon_succeeds() -> None:
    r = _import_main(None)
    assert r.returncode == 0, r.stderr[-500:]


# 9. DocumentIndex and performance
def _big_doc() -> tuple[list[Clause], int]:
    body = "Страховик сплачує відшкодування протягом 10 днів після отримання повідомлення. "
    clauses = [
        c(
            f"c{i}",
            (body + "Інші умови визначені сторонами. ") * 5,
            number=f"{i // 10 + 1}.{i % 10 + 1}",
        )
        for i in range(440)
    ]
    return clauses, sum(len(x.text) for x in clauses)


def test_big_document_has_264k_characters() -> None:
    _, n = _big_doc()
    assert n >= 200_000


def test_hundred_findings_over_big_document_with_index_are_fast() -> None:
    clauses, _ = _big_doc()
    quote = "протягом 10 днів"
    t0 = time.perf_counter()
    cx = ctx(*clauses)
    idx = build_document_index(clauses)
    for i in range(100):
        apply_green_rules(cx, green(f"c{i * 4}", quote, topic=f"t{i}"), idx)
    assert time.perf_counter() - t0 < 3.0


def test_index_does_not_change_results() -> None:
    lx = LANGS["en"]
    clauses = [c("c1", f"{lx.base} {lx.exc}", number="1.1"), c("c2", lx.glob, number="2")]
    cx = ctx(*clauses)
    f = green("c1", lx.quote)
    assert apply_green_rules(cx, f) == apply_green_rules(cx, f, build_document_index(clauses))


def test_index_is_not_cached_between_documents() -> None:
    lx = LANGS["en"]
    a = [c("c1", lx.base, number="1.1")]
    b = [c("c1", f"{lx.base} {lx.exc}", number="1.1")]
    ia = build_document_index(a)
    ib = build_document_index(b)
    assert apply_green_rules(ctx(*a), green("c1", lx.quote), ia).rating is Rating.green
    assert apply_green_rules(ctx(*b), green("c1", lx.quote), ib).rating is Rating.yellow
    assert apply_green_rules(ctx(*a), green("c1", lx.quote), ia).rating is Rating.green


# Security delta: unknown word after a number, alternatives
UNREADABLE = [
    ("The limit is USD 10 mln per event.", "USD"),
    ("The limit is USD 10mln per event.", "USD"),
    ("The limit is USD 10 bln per event.", "USD"),
    ("The limit is EUR 5 mio per event.", "EUR"),
    ("The limit is EUR 5 Mio. per event.", "EUR"),
    ("The limit is USD 10 MM per event.", "USD"),
    ("The limit is USD 10 thsd per event.", "USD"),
    ("The limit is USD 10 ths per event.", "USD"),
    ("Ліміт становить 10 тис за випадок.", "UAH"),
    ("Ліміт становить 10 млн грн за випадок.", "UAH"),
    ("Лимит составляет 10 тыс за случай.", "UAH"),
    ("Лимит составляет 10 млн руб за случай.", "UAH"),
]


@pytest.mark.parametrize(("text", "unit"), UNREADABLE)
@pytest.mark.parametrize("value", ["10", "5", "10000", "10000000", "5000000"])
def test_unknown_word_after_number_makes_it_unreadable(text: str, unit: str, value: str) -> None:
    out = value_out(text, value, unit)
    assert out.status is ValueStatus.not_confirmed
    assert Reason.number_mismatch in out.reasons


ALTERNATIVES = [
    ("The insurer pays within 10 or 15 days of notice.", "days"),
    ("The insurer pays within 10…15 days of notice.", "days"),
    ("Страховик сплачує протягом 10 або 15 днів з дня повідомлення.", "days"),
    ("Страховщик платит в течение 10 или 15 дней со дня уведомления.", "days"),
]


@pytest.mark.parametrize(("text", "unit"), ALTERNATIVES)
@pytest.mark.parametrize("value", ["10", "15"])
def test_alternatives_are_mismatch_like_ranges(text: str, unit: str, value: str) -> None:
    out = value_out(text, value, unit)
    assert out.status is ValueStatus.not_confirmed
    assert Reason.number_mismatch in out.reasons


CLEAN = [
    ("The insurer pays within 10 days of notice.", "10", "days"),
    ("The limit is UAH 10 000 per event.", "10000", "UAH"),
    ("The insurer pays within 10 working days of notice.", "10", "working_days"),
    ("Страховик сплачує протягом 10 днів з дня повідомлення.", "10", "days"),
    ("Страховщик платит в течение 10 дней со дня уведомления.", "10", "days"),
    ("The limit is 10 000 UAH per event.", "10000", "UAH"),
]


@pytest.mark.parametrize(("text", "num", "unit"), CLEAN[:6])
def test_clean_numbers_stay_verified(text: str, num: str, unit: str) -> None:
    assert value_out(text, num, unit).status is ValueStatus.verified


# Window rule: 3 tokens after a number, 2 before (currency first)
WINDOW = [
    ("The limit is USD 10 in thousands per event.", "USD", ["10", "10000"]),
    ("The limit is USD 10 per thousand of the sum.", "USD", ["10", "1000"]),
    ("The limit is USD 10 × 1000 per event.", "USD", ["10", "1000", "10000"]),
    ("The limit is USD 10*1000 per event.", "USD", ["10", "1000", "10000"]),
    ("The limit is USD 10 x 1000 per event.", "USD", ["10", "1000", "10000"]),
    ("The limit is USD 10 plus 5 per event.", "USD", ["10", "5", "15"]),
    ("The insurer pays within between 10 and 15 days of notice.", "days", ["10", "15"]),
    ("The insurer pays within 10 minus 2 days of notice.", "days", ["10", "2", "8"]),
    ("The insurer pays within 10 through 15 days of notice.", "days", ["10", "15"]),
    ("Страховик сплачує протягом 10 і 15 днів з дня повідомлення.", "days", ["10", "15"]),
    ("Страховик сплачує протягом 10 днів та 5 днів після повідомлення.", "days", ["10", "5", "15"]),
    ("Страховик сплачує протягом 10 плюс 5 днів після повідомлення.", "days", ["10", "5", "15"]),
    ("Страховик сплачує протягом 10 мінус 2 дні після повідомлення.", "days", ["10", "2", "8"]),
    ("Ліміт становить USD 10 у тисячах за випадок.", "USD", ["10", "10000"]),
    ("Страховщик платит в течение 10 и 15 дней со дня уведомления.", "days", ["10", "15"]),
    ("Страховщик платит в течение 10 либо 15 дней со дня уведомления.", "days", ["10", "15"]),
    ("Страховщик платит в течение 10 минус 2 дня со дня уведомления.", "days", ["10", "2", "8"]),
    ("Страховщик платит в течение 10 плюс 5 дней со дня уведомления.", "days", ["10", "5", "15"]),
    ("Лимит составляет USD 10 в тысячах за случай.", "USD", ["10", "10000"]),
]


@pytest.mark.parametrize(("text", "unit", "values"), WINDOW)
def test_number_with_number_scale_operator_or_alternative_in_window_is_unreadable(
    text: str, unit: str, values: list[str]
) -> None:
    for v in values:
        out = value_out(text, v, unit)
        assert out.status is ValueStatus.not_confirmed
        assert Reason.number_mismatch in out.reasons


WINDOW_CLEAN = [
    ("The insurer pays within 10 days.", "10", "days"),
    ("The limit is UAH 10 000 per event.", "10000", "UAH"),
    ("The insurer pays within 10 working days after notice.", "10", "working_days"),
    ("Страховик сплачує протягом 10 днів з дня повідомлення.", "10", "days"),
    ("Страховщик платит в течение 10 дней с момента получения.", "10", "days"),
]


@pytest.mark.parametrize(("text", "num", "unit"), WINDOW_CLEAN)
def test_number_with_clean_window_stays_verified(text: str, num: str, unit: str) -> None:
    assert value_out(text, num, unit).status is ValueStatus.verified
