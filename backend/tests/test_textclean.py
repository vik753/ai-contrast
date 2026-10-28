# ruff: noqa: RUF001, S311, PT014
"""S5-T1b (AC 1-5, 7): the shared Layer 1 cleaning module ``app/textclean/``.

Public interface assumed (the smallest one that the acceptance criteria need):

* ``app.textclean.clean_text(text: str) -> CleanResult`` with ``.text: str`` and
  ``.removed: list`` of items with ``.reason``, ``.count`` and ``.sample``
  (one item per reason, ``count`` = removed code points, ``sample`` = the
  distinct removed code points as ``U+XXXX`` joined by one space, sorted, at most
  16 of them, as ``ControlCleaner`` does today; never longer than 200 characters).
* ``app/textclean/ignorable_table.py`` exports ``UNICODE_VERSION: str`` and
  ``RANGES: tuple[tuple[int, int], ...]`` (sorted, inclusive ``(low, high)``).
* ``backend/scripts/gen_ignorable_table.py`` exports ``render_table() -> str``:
  the exact source text of ``ignorable_table.py`` for the Unicode data in use.

Rules taken from the task text: Cc is removed except TAB, LF, CR; White_Space
that is not Cc is never removed (Cc white space such as U+000B, U+0085 follows
the Cc rule, which the task states explicitly). Where a code point has two
possible reasons (for example U+200B is both Default_Ignorable and Cf) the tests
accept either; they check an exact reason only when it is unambiguous.

Expected to fail before the implementation exists (ModuleNotFoundError).
"""

from __future__ import annotations

import importlib.util
import random
import re
import time
import unicodedata
from bisect import bisect_right
from itertools import pairwise
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

BACKEND = Path(__file__).resolve().parent.parent
APP = BACKEND / "app"
GENERATOR = BACKEND / "scripts" / "gen_ignorable_table.py"
TABLE_FILE = APP / "textclean" / "ignorable_table.py"

REASONS = {
    "default_ignorable",
    "format_character",
    "private_use",
    "unassigned",
    "surrogate",
    "control_character",
}

# Default_Ignorable_Code_Point (Unicode 15.1, DerivedCoreProperties), written out here
# on purpose: the test must not depend on the generator's own source of truth.
DEFAULT_IGNORABLE = [
    0x00AD,
    0x034F,
    0x061C,
    0x115F,
    0x1160,
    0x3164,
    0xFEFF,
    0xFFA0,
    *range(0x17B4, 0x17B6),
    *range(0x180B, 0x1810),
    *range(0x200B, 0x2010),
    *range(0x202A, 0x202F),
    *range(0x2060, 0x2070),
    *range(0xFE00, 0xFE10),
    *range(0xFFF0, 0xFFF9),
    *range(0x1BCA0, 0x1BCA4),
    *range(0x1D173, 0x1D17B),
    *range(0xE0000, 0xE1000),
]
# Named in the task (AC 3) in addition to categories and Default_Ignorable.
NAMED = [
    0x034F,
    0x115F,
    0x1160,
    0x3164,
    0xFFA0,
    0x2800,
    0x180E,
    0x2065,
    *range(0xFFF0, 0xFFFC),
    *range(0xFE00, 0xFE10),
    *range(0xE0100, 0xE01F0),
    *range(0xE0000, 0xE1000),
]
# ADR 0009 Layer 1, written out one by one.
ADR_LAYER1 = sorted(
    {
        *range(0x200B, 0x2010),  # zero-width space/joiners, LRM, RLM
        *range(0x202A, 0x202F),  # bidi embeddings and overrides
        *range(0x2060, 0x2065),  # word joiner, invisible operators
        *range(0x2066, 0x206A),  # bidi isolates
        0xFEFF,  # BOM / ZWNBSP
        0x00AD,  # soft hyphen
        0x061C,  # Arabic letter mark
        *range(0xE0000, 0xE0080),  # tag characters
        *range(0xFE00, 0xFE10),  # variation selectors
        *range(0xE0100, 0xE01F0),  # variation selectors supplement
        0x034F,
        0x115F,
        0x1160,
        0x3164,
        0xFFA0,
        0x2800,
        *range(0xFFF9, 0xFFFC),
        0x180E,
    }
)
LINE_BREAKS = {0x0B, 0x0C, 0x0D, 0x85, 0x2028, 0x2029}
CHECKBOX = {0xF0FE: "☑", 0xF0FD: "☒", 0xF0A8: "☐", 0xF06F: "☐", 0xF078: "☒"}


def _clean(text: str) -> Any:
    from app.textclean import clean_text  # noqa: PLC0415 - fail per test

    return clean_text(text)


def _table() -> ModuleType:
    from app.textclean import ignorable_table  # noqa: PLC0415 - fail per test

    return ignorable_table


def _in_table(code_point: int) -> bool:
    ranges = _table().RANGES
    index = bisect_right(ranges, (code_point, 0x10FFFF)) - 1
    return index >= 0 and ranges[index][0] <= code_point <= ranges[index][1]


def _by_reason(result: Any) -> dict[str, Any]:
    reasons = [item.reason for item in result.removed]
    assert len(reasons) == len(set(reasons)), "one removed item per reason"
    return {item.reason: item for item in result.removed}


def _expected_removed() -> set[int]:
    out = set(DEFAULT_IGNORABLE) | set(NAMED)
    for cp in range(0x110000):
        if unicodedata.category(chr(cp)) in {"Cf", "Co", "Cs", "Cn", "Cc"}:
            out.add(cp)
    out -= {0x09, 0x0A, 0x0D}
    return out


# --- AC 1: no other cleaner remains ---------------------------------------------------------


def test_policy_old_cleaner_modules_are_gone() -> None:
    assert not (APP / "segment" / "clean.py").exists()
    offenders = [
        str(path.relative_to(APP))
        for path in APP.rglob("*.py")
        if "textclean" not in path.parts
        and re.search(r"ControlCleaner|InputCleaner|_REMOVED_CONTROLS", path.read_text("utf-8"))
    ]
    assert offenders == []


def test_policy_no_module_outside_textclean_removes_format_private_or_unassigned() -> None:
    pattern = re.compile(
        r"""["'](?:Cf|Co|Cn|Cs)["']|\\u200[bBcCdDeEfF]|\\u202[a-eA-E]|\\u[fF][eE][fF][fF]"""
    )
    offenders = [
        str(path.relative_to(APP))
        for path in APP.rglob("*.py")
        if "textclean" not in path.parts and pattern.search(path.read_text("utf-8"))
    ]
    assert offenders == []


def test_policy_textclean_package_exports_clean_text() -> None:
    from app import textclean  # noqa: PLC0415 - fail per test

    assert callable(textclean.clean_text)


# --- AC 2: order ----------------------------------------------------------------------------


@pytest.mark.parametrize(("code", "glyph"), sorted(CHECKBOX.items()))
def test_symbol_font_checkbox_is_mapped_not_removed(code: int, glyph: str) -> None:
    result = _clean(f"{chr(code)} covered")

    assert result.text == f"{glyph} covered"
    assert result.removed == []


def test_symbol_glyph_is_mapped_before_other_private_use_is_removed() -> None:
    result = _clean("\uf0fe\ue000\uf0a8\uf8ff")

    assert result.text == "☑☐"
    assert _by_reason(result)["private_use"].count == 2


def test_removal_happens_before_nfc() -> None:
    # "e", zero-width space, combining acute: only after removal do they compose to "é".
    assert _clean("e\u200b́").text == "é"


def test_result_is_nfc() -> None:
    assert _clean("é Å").text == "é Å"


def test_nfc_not_nfkc_legal_symbols_are_kept() -> None:
    assert _clean("№ 5, м², ½").text == "№ 5, м², ½"


# --- AC 3: table contents, generator ---------------------------------------------------------


def test_table_matches_independent_expectation_exactly() -> None:
    table = {cp for low, high in _table().RANGES for cp in range(low, high + 1)}
    expected = _expected_removed()

    assert sorted(expected - table)[:10] == []
    assert sorted(table - expected)[:10] == []


def test_table_ranges_are_sorted_and_not_overlapping() -> None:
    ranges = _table().RANGES
    assert all(low <= high for low, high in ranges)
    assert all(a[1] < b[0] for a, b in pairwise(ranges))


def test_table_contains_every_named_code_point() -> None:
    missing = [f"U+{cp:04X}" for cp in sorted(set(NAMED)) if not _in_table(cp)]

    assert missing == []


def test_table_never_contains_tab_lf_cr_or_non_control_white_space() -> None:
    for cp in (0x09, 0x0A, 0x0D, 0x20, 0xA0, 0x1680, 0x2028, 0x2029, 0x202F, 0x205F, 0x3000):
        assert not _in_table(cp), f"U+{cp:04X}"
    for cp in range(0x2000, 0x200B):
        assert not _in_table(cp), f"U+{cp:04X}"


def test_table_records_the_unicode_version_of_its_source() -> None:
    assert re.fullmatch(r"\d+\.\d+(\.\d+)?", _table().UNICODE_VERSION)
    assert unicodedata.unidata_version == _table().UNICODE_VERSION


def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_ignorable_table", GENERATOR)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generator_output_equals_checked_in_table_file() -> None:
    generated = _generator().render_table()

    assert generated == TABLE_FILE.read_text(encoding="utf-8")


def test_generator_output_is_deterministic() -> None:
    generator = _generator()
    assert generator.render_table() == generator.render_table()


def test_generator_records_the_unicode_version_it_used() -> None:
    assert unicodedata.unidata_version in _generator().render_table()


# --- AC 4: report ---------------------------------------------------------------------------


def test_clean_text_without_removals_returns_same_text_and_empty_report() -> None:
    text = "1. Payment is due in 30 days.\tСтаття 5.\nLine two."
    result = _clean(text)

    assert result.text == text
    assert result.removed == []


@pytest.mark.parametrize(
    ("char", "allowed"),
    [
        ("\u0007", {"control_character"}),
        ("\u007f", {"control_character"}),
        ("\u0080", {"control_character"}),
        ("\ue000", {"private_use"}),
        ("\U000f0000", {"private_use"}),
        ("\u0378", {"unassigned"}),
        ("\U0010ffff", {"unassigned"}),
        ("\ud800", {"surrogate"}),
        ("\udfff", {"surrogate"}),
        ("\u0600", {"format_character"}),
        ("\u3164", {"default_ignorable"}),
        ("\ufe0f", {"default_ignorable"}),
        ("\u034f", {"default_ignorable"}),
        ("\u200b", {"default_ignorable", "format_character"}),
        ("\u2065", {"default_ignorable", "unassigned"}),
        ("\U000e0041", {"default_ignorable", "format_character"}),
        ("\u2800", REASONS),
    ],
)
def test_removed_reason_for_each_kind(char: str, allowed: set[str]) -> None:
    result = _clean(f"a{char}b")

    assert result.text == "ab"
    assert len(result.removed) == 1
    item = result.removed[0]
    assert item.reason in allowed
    assert item.count == 1
    assert item.sample == f"U+{ord(char):04X}"


def test_removed_counts_and_sample_are_sorted_distinct_code_points() -> None:
    result = _clean("a\u200b\u200bb\u202ec\u200b")

    assert result.text == "abc"
    assert sum(i.count for i in result.removed) == 4
    samples = " ".join(i.sample for i in result.removed)
    assert "U+200B" in samples
    assert "U+202E" in samples
    assert samples.count("U+200B") == 1


def test_removed_reports_one_item_per_reason_with_totals() -> None:
    result = _clean("x\u0007\u0001y\ue000z\u0378")
    by = _by_reason(result)

    assert by["control_character"].count == 2
    assert by["control_character"].sample == "U+0001 U+0007"
    assert by["private_use"].count == 1
    assert by["unassigned"].count == 1
    assert {i.reason for i in result.removed} <= REASONS


def test_removed_sample_lists_at_most_16_code_points_and_200_characters() -> None:
    result = _clean("".join(chr(c) for c in range(0xE000, 0xE100)))

    (item,) = result.removed
    assert item.count == 256
    assert len(item.sample.split()) <= 16
    assert len(item.sample) <= 200


def test_removed_sample_contains_no_removable_character() -> None:
    result = _clean("a\u202eb\ue000c\u0007d")

    for item in result.removed:
        assert _clean(item.sample).text == item.sample
        assert all(unicodedata.category(ch)[0] != "C" for ch in item.sample)


# --- AC 5: idempotence and ADR 0009 code points --------------------------------------------


def test_clean_is_idempotent_on_random_strings_from_all_planes() -> None:
    rng = random.Random(20261028)
    interesting = sorted(_expected_removed() | set(CHECKBOX) | {0x0301, 0x0041, 0x0020, 0x000A})
    sample_interesting = [interesting[i] for i in range(0, len(interesting), 97)]
    for _ in range(400):
        chars = []
        for _ in range(rng.randint(0, 60)):
            roll = rng.random()
            if roll < 0.4:
                chars.append(chr(rng.randrange(0x110000)))
            elif roll < 0.8:
                chars.append(chr(rng.choice(sample_interesting)))
            else:
                chars.append(rng.choice("abc ДЖє\n\t.-"))
        text = "".join(chars)
        once = _clean(text)
        twice = _clean(once.text)
        assert twice.text == once.text, repr(text)
        assert twice.removed == [], repr(text)
        assert unicodedata.is_normalized("NFC", once.text)


def test_every_adr_layer1_code_point_is_removed() -> None:
    survivors = [cp for cp in ADR_LAYER1 if _clean(f"a{chr(cp)}b").text != "ab"]

    assert [f"U+{cp:04X}" for cp in survivors] == []


def test_every_code_point_in_the_table_is_removed_and_nothing_else_is() -> None:
    expected = _expected_removed()
    wrongly_kept: list[int] = []
    wrongly_removed: list[int] = []
    for cp in range(0x110000):
        if cp in CHECKBOX:
            continue
        out = _clean(f"a{chr(cp)}b").text
        if cp in LINE_BREAKS:
            if out != "a\nb":
                wrongly_removed.append(cp)
            continue
        if cp in expected and out != "ab":
            wrongly_kept.append(cp)
        if cp not in expected and unicodedata.normalize("NFC", f"a{chr(cp)}b") != out:
            wrongly_removed.append(cp)
        if len(wrongly_kept) + len(wrongly_removed) > 10:
            break
    assert wrongly_kept == []
    assert wrongly_removed == []


# --- AC 7: linear time ----------------------------------------------------------------------


def _timed(size: int) -> float:
    unit = "Pay\u200bment\u202e is\u2800 due\U000e0041 ☑ 30 дн́ів. "
    text = (unit * (size // len(unit) + 1))[:size]
    start = time.perf_counter()
    _clean(text)
    return time.perf_counter() - start


def test_clean_text_runs_in_linear_time_at_one_million_characters() -> None:
    small = min(_timed(200_000) for _ in range(2))
    large = min(_timed(1_000_000) for _ in range(2))

    assert large < 10.0
    assert large < 12 * max(small, 0.02)


def test_line_breaks_become_lf_and_are_not_reported() -> None:
    result = _clean("a\r\nb\rc\u0085d\u2028e\u2029f\u000bg\u000ch")

    assert result.text == "a\nb\nc\nd\ne\nf\ng\nh"
    assert result.removed == []
