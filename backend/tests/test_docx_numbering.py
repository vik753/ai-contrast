# ruff: noqa: RUF001 - Cyrillic list labels are the point of these tests
"""S3-T2b: list numbering labels from ``numbering.xml``.

A paragraph with ``w:numPr`` (direct or from its style) gets its label prefixed to
the block text with one space. Counters run per ``numId`` in document order.
Assumed (see the report): a cap breach raises ``ExtractionError`` with code
``suspicious_package``. Must fail before the implementation exists.
"""

from __future__ import annotations

import pytest

from app.extraction.model import ExtractionError, ExtractionResult
from tests.docxbuild import (
    NS_DECL,
    XML_DECL,
    Package,
    abstract_num,
    build_docx,
    lvl,
    num,
    num_pr,
    numbering_xml,
    p,
    para,
    r,
    styles_xml,
)
from tests.docxrun import extract, joined, texts, warning_codes

TEXT = "Item text"


def _run(
    numbering: bytes, *paragraphs: str, styles: bytes | None = None, **kw: int
) -> ExtractionResult:
    data = build_docx(Package(body="".join(paragraphs), numbering=numbering, styles=styles))
    return extract(data, **kw)


def _list(numbering: bytes, levels: list[int], num_id: int = 1) -> list[str]:
    """Extract one numbered paragraph per entry of ``levels``; return the block texts."""
    body = [para(TEXT, ppr=num_pr(num_id, level)) for level in levels]
    return texts(_run(numbering, *body))


def _single(fmt: str, text: str = "%1.", count: int = 3, **lvl_kw: int) -> list[str]:
    numbering = numbering_xml(
        abstract_num(0, lvl(0, text, fmt, **lvl_kw)),  # type: ignore[arg-type]
        num(1, 0),
    )
    return _list(numbering, [0] * count)


def _labels(blocks: list[str]) -> list[str]:
    return [b.removesuffix(" " + TEXT) for b in blocks]


# --- Basic shape ------------------------------------


def test_label_is_prefixed_with_exactly_one_space() -> None:
    assert _single("decimal", count=1) == ["1. " + TEXT]


def test_paragraph_without_numpr_is_unchanged() -> None:
    numbering = numbering_xml(abstract_num(0, lvl(0, "%1.")), num(1, 0))
    result = _run(numbering, para("Plain paragraph."), para(TEXT, ppr=num_pr(1)))

    assert texts(result) == ["Plain paragraph.", "1. " + TEXT]


def test_decimal_multilevel_labels() -> None:
    numbering = numbering_xml(
        abstract_num(0, lvl(0, "%1."), lvl(1, "%1.%2."), lvl(2, "%1.%2.%3.")),
        num(1, 0),
    )

    blocks = _list(numbering, [0, 1, 1, 2, 0, 1])

    assert _labels(blocks) == ["1.", "1.1.", "1.2.", "1.2.1.", "2.", "2.1."]


# --- Number formats ------------------------------------


@pytest.mark.parametrize(
    ("fmt", "expected"),
    [
        ("decimal", ["1.", "2.", "3."]),
        ("decimalZero", ["01.", "02.", "03."]),
        ("lowerLetter", ["a.", "b.", "c."]),
        ("upperLetter", ["A.", "B.", "C."]),
        ("lowerRoman", ["i.", "ii.", "iii."]),
        ("upperRoman", ["I.", "II.", "III."]),
        ("russianLower", ["а.", "б.", "в."]),
        ("russianUpper", ["А.", "Б.", "В."]),
        ("ukrainianCounting", ["а.", "б.", "в."]),
    ],
)
def test_number_format_labels(fmt: str, expected: list[str]) -> None:
    blocks = _single(fmt)

    assert _labels(blocks) == expected
    assert "numbering_approximate" not in warning_codes(
        _run(
            numbering_xml(abstract_num(0, lvl(0, "%1.", fmt)), num(1, 0)),
            para(TEXT, ppr=num_pr(1)),
        )
    )


def test_lower_roman_counts_past_nine() -> None:
    assert _labels(_single("lowerRoman", count=14))[8:] == [
        "ix.",
        "x.",
        "xi.",
        "xii.",
        "xiii.",
        "xiv.",
    ]


def test_decimal_zero_counts_past_nine() -> None:
    assert _labels(_single("decimalZero", count=11))[8:] == ["09.", "10.", "11."]


def test_lower_letter_wraps_after_z() -> None:
    assert _labels(_single("lowerLetter", count=28))[25:] == ["z.", "aa.", "bb."]


def test_bullet_label_is_the_level_text() -> None:
    blocks = _single("bullet", "•", count=2)

    assert blocks == ["• " + TEXT, "• " + TEXT]


def test_label_text_around_the_counter_is_kept() -> None:
    assert _labels(_single("decimal", "(%1)", count=2)) == ["(1)", "(2)"]
    assert _labels(_single("decimal", "Article %1:", count=1)) == ["Article 1:"]


# --- start, restart, isLgl ------------------------------------


def test_start_value_is_the_first_number() -> None:
    assert _labels(_single("decimal", start=5)) == ["5.", "6.", "7."]


def test_lower_level_restarts_after_higher_level_by_default() -> None:
    numbering = numbering_xml(
        abstract_num(0, lvl(0, "%1."), lvl(1, "%2)")),
        num(1, 0),
    )

    assert _labels(_list(numbering, [0, 1, 1, 0, 1])) == ["1.", "1)", "2)", "2.", "1)"]


def test_lvl_restart_zero_never_restarts() -> None:
    numbering = numbering_xml(
        abstract_num(0, lvl(0, "%1."), lvl(1, "%1.%2.", restart=0)),
        num(1, 0),
    )

    assert _labels(_list(numbering, [0, 1, 0, 1])) == ["1.", "1.1.", "2.", "2.2."]


def test_lvl_restart_one_restarts_only_after_level_one() -> None:
    numbering = numbering_xml(
        abstract_num(0, lvl(0, "%1."), lvl(1, "%2."), lvl(2, "%3.", restart=1)),
        num(1, 0),
    )

    labels = _labels(_list(numbering, [0, 1, 2, 1, 2, 0, 1, 2]))

    assert labels == ["1.", "1.", "1.", "2.", "2.", "2.", "1.", "1."]


def test_is_lgl_shows_earlier_levels_as_decimal() -> None:
    numbering = numbering_xml(
        abstract_num(0, lvl(0, "%1.", "upperRoman"), lvl(1, "%1.%2.", "decimal", is_lgl=True)),
        num(1, 0),
    )

    assert _labels(_list(numbering, [0, 0, 1])) == ["I.", "II.", "2.1."]


def test_is_lgl_converts_roman_level_to_decimal() -> None:
    numbering = numbering_xml(
        abstract_num(0, lvl(0, "%1.", "upperRoman"), lvl(1, "%1.%2.", "lowerRoman", is_lgl=True)),
        num(1, 0),
    )

    assert _labels(_list(numbering, [0, 0, 1, 1])) == ["I.", "II.", "2.1.", "2.2."]


# --- w:num overrides ------------------------------------


def test_start_override_changes_the_first_number() -> None:
    override = '<w:lvlOverride w:ilvl="0"><w:startOverride w:val="7"/></w:lvlOverride>'
    numbering = numbering_xml(abstract_num(0, lvl(0, "%1.")), num(1, 0, override))

    assert _labels(_list(numbering, [0, 0])) == ["7.", "8."]


def test_lvl_override_replaces_the_level_definition() -> None:
    override = f'<w:lvlOverride w:ilvl="0">{lvl(0, "%1)", "upperLetter")}</w:lvlOverride>'
    numbering = numbering_xml(abstract_num(0, lvl(0, "%1.")), num(1, 0, override))

    assert _labels(_list(numbering, [0, 0])) == ["A)", "B)"]


def test_counters_are_kept_per_num_id() -> None:
    numbering = numbering_xml(
        abstract_num(0, lvl(0, "%1.")),
        abstract_num(1, lvl(0, "(%1)")),
        num(1, 0),
        num(2, 1),
    )
    result = _run(
        numbering,
        para("First", ppr=num_pr(1)),
        para("Other", ppr=num_pr(2)),
        para("Second", ppr=num_pr(1)),
        para("Another", ppr=num_pr(2)),
    )

    assert texts(result) == ["1. First", "(1) Other", "2. Second", "(2) Another"]


def test_num_id_zero_removes_numbering() -> None:
    numbering = numbering_xml(abstract_num(0, lvl(0, "%1.")), num(1, 0))
    result = _run(numbering, para("Kept", ppr=num_pr(1)), para("Plain", ppr=num_pr(0)))

    assert texts(result) == ["1. Kept", "Plain"]


# --- Numbering from a style ------------------------------------


def _numbered_style(style_id: str, num_id: int, ilvl: int | None = None) -> str:
    level = f'<w:ilvl w:val="{ilvl}"/>' if ilvl is not None else ""
    return (
        f'<w:style w:type="paragraph" w:styleId="{style_id}"><w:name w:val="{style_id}"/>'
        f'<w:pPr><w:numPr>{level}<w:numId w:val="{num_id}"/></w:numPr></w:pPr></w:style>'
    )


def test_numbering_from_paragraph_style() -> None:
    numbering = numbering_xml(abstract_num(0, lvl(0, "%1.")), num(1, 0))
    styles = styles_xml(_numbered_style("Clause", 1))
    result = _run(
        numbering,
        para("One", ppr='<w:pStyle w:val="Clause"/>'),
        para("Two", ppr='<w:pStyle w:val="Clause"/>'),
        styles=styles,
    )

    assert texts(result) == ["1. One", "2. Two"]


def test_style_level_is_used() -> None:
    numbering = numbering_xml(abstract_num(0, lvl(0, "%1."), lvl(1, "%1.%2.")), num(1, 0))
    styles = styles_xml(_numbered_style("Sub", 1, ilvl=1))
    result = _run(
        numbering,
        para("Top", ppr=num_pr(1, 0)),
        para("Sub", ppr='<w:pStyle w:val="Sub"/>'),
        styles=styles,
    )

    assert texts(result) == ["1. Top", "1.1. Sub"]


def test_numbering_inherited_through_based_on() -> None:
    numbering = numbering_xml(abstract_num(0, lvl(0, "%1.")), num(1, 0))
    child = (
        '<w:style w:type="paragraph" w:styleId="Child"><w:name w:val="Child"/>'
        '<w:basedOn w:val="Clause"/></w:style>'
    )
    styles = styles_xml(_numbered_style("Clause", 1), child)
    result = _run(numbering, para("One", ppr='<w:pStyle w:val="Child"/>'), styles=styles)

    assert texts(result) == ["1. One"]


def test_direct_numpr_overrides_style_numpr() -> None:
    numbering = numbering_xml(
        abstract_num(0, lvl(0, "%1.")), abstract_num(1, lvl(0, "(%1)")), num(1, 0), num(2, 1)
    )
    styles = styles_xml(_numbered_style("Clause", 1))
    result = _run(
        numbering, para("One", ppr='<w:pStyle w:val="Clause"/>' + num_pr(2)), styles=styles
    )

    assert texts(result) == ["(1) One"]


# --- Document order, tables, uncounted paragraphs ------------------------------------


def test_counter_continues_across_table_cells_in_document_order() -> None:
    numbering = numbering_xml(abstract_num(0, lvl(0, "%1.")), num(1, 0))
    table = (
        "<w:tbl><w:tr><w:tc>"
        + para("Cell A", ppr=num_pr(1))
        + "</w:tc><w:tc>"
        + para("Cell B", ppr=num_pr(1))
        + "</w:tc></w:tr></w:tbl>"
    )
    result = _run(numbering, para("Before", ppr=num_pr(1)), table, para("After", ppr=num_pr(1)))

    text = joined(result)
    for expected in ("1. Before", "2. Cell A", "3. Cell B", "4. After"):
        assert expected in text


def test_hidden_paragraph_does_not_count() -> None:
    numbering = numbering_xml(abstract_num(0, lvl(0, "%1.")), num(1, 0))
    # Round 1 (PR #31): counting follows the paragraph mark, so the mark is hidden too.
    hidden_mark = "<w:rPr><w:vanish/></w:rPr>"
    hidden = p(r("Hidden clause text.", "<w:vanish/>"), ppr=num_pr(1) + hidden_mark)
    result = _run(numbering, para("One", ppr=num_pr(1)), hidden, para("Two", ppr=num_pr(1)))

    assert "Hidden clause" not in joined(result)
    assert texts(result) == ["1. One", "2. Two"]


def test_tracked_deleted_paragraph_does_not_count() -> None:
    numbering = numbering_xml(abstract_num(0, lvl(0, "%1.")), num(1, 0))
    deleted_run = (
        '<w:del w:id="1" w:author="A" w:date="2026-01-01T00:00:00Z">'
        '<w:r><w:delText xml:space="preserve">Deleted clause text.</w:delText></w:r></w:del>'
    )
    # Round 1 (PR #31): counting follows the paragraph mark, so the mark is deleted too.
    deleted_mark = '<w:rPr><w:del w:id="2" w:author="A" w:date="2026-01-01T00:00:00Z"/></w:rPr>'
    deleted = p(deleted_run, ppr=num_pr(1) + deleted_mark)
    result = _run(numbering, para("One", ppr=num_pr(1)), deleted, para("Two", ppr=num_pr(1)))

    assert "Deleted clause" not in joined(result)
    assert texts(result) == ["1. One", "2. Two"]


def test_empty_numbered_paragraph_adds_no_label_only_block() -> None:
    numbering = numbering_xml(abstract_num(0, lvl(0, "%1.")), num(1, 0))
    result = _run(numbering, para("One", ppr=num_pr(1)), p(ppr=num_pr(1)))

    assert texts(result) == ["1. One"]


# --- Approximation and fail-closed caps ------------------------


def test_unknown_format_falls_back_to_decimal_with_warning() -> None:
    numbering = numbering_xml(abstract_num(0, lvl(0, "%1.", "fooBarFutureFormat")), num(1, 0))
    result = _run(numbering, para("A", ppr=num_pr(1)), para("B", ppr=num_pr(1)))

    assert texts(result) == ["1. A", "2. B"]
    assert "numbering_approximate" in warning_codes(result)


def test_missing_numbering_part_leaves_text_unlabelled() -> None:
    data = build_docx(Package(body=para(TEXT, ppr=num_pr(1))))

    assert texts(extract(data)) == [TEXT]


def test_missing_num_definition_leaves_text_unlabelled() -> None:
    numbering = numbering_xml(abstract_num(0, lvl(0, "%1.")), num(1, 0))
    result = _run(numbering, para(TEXT, ppr=num_pr(99)))

    assert texts(result) == [TEXT]


def test_ninth_level_is_accepted() -> None:
    levels = [lvl(i, ".".join(f"%{k}" for k in range(1, i + 2)) + ".") for i in range(9)]
    numbering = numbering_xml(abstract_num(0, *levels), num(1, 0))

    blocks = _list(numbering, list(range(9)))

    assert _labels(blocks)[-1] == "1.1.1.1.1.1.1.1.1."


def test_more_than_nine_levels_fails_closed() -> None:
    levels = [lvl(i, f"%{i + 1}.") for i in range(10)]
    numbering = numbering_xml(abstract_num(0, *levels), num(1, 0))

    with pytest.raises(ExtractionError) as info:
        _run(numbering, para(TEXT, ppr=num_pr(1)))

    assert info.value.code == "suspicious_package"


def test_paragraph_level_above_eight_uses_level_zero_and_warns() -> None:
    # Round 1 (PR #31), item 5: a bad paragraph `ilvl` is approximate, not fatal.
    numbering = numbering_xml(abstract_num(0, lvl(0, "%1.")), num(1, 0))

    result = _run(numbering, para(TEXT, ppr=num_pr(1, 9)))

    assert texts(result) == [f"1. {TEXT}"]
    assert "numbering_approximate" in [w.code for w in result.warnings]


def test_too_many_definitions_fails_closed() -> None:
    # 100,000 definitions: far above any sane cap, still small enough to build.
    items = "".join(abstract_num(i, lvl(0, "%1.")) + num(i + 1, i) for i in range(100_000))
    numbering = f"{XML_DECL}<w:numbering {NS_DECL}>{items}</w:numbering>".encode()

    with pytest.raises(ExtractionError) as info:
        _run(numbering, para(TEXT, ppr=num_pr(1)))

    assert info.value.code == "suspicious_package"
