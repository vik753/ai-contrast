"""S3-T2 AC5: hidden text by effective formatting (ADR 0009 Layer 1, DOCX visibility).

Effective formatting: docDefaults -> paragraph style (``basedOn`` chain, cycle
guard) -> character style -> direct ``w:rPr``. Removed text is reported in
``removed`` with a reason and a sample; borderline text is kept with the warning
``borderline_text``. Unit tests of ``extract_docx``; must fail before the
implementation exists.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from app.extraction.model import ExtractionError
from tests.docxbuild import CLAUSE, Package, body_docx, build_docx, p, para, r, style, styles_xml
from tests.docxrun import extract, joined, reasons, texts, warning_codes

HIDDEN = "Hidden clause: the Client waives every claim."
VISIBLE = "Visible clause: the Client pays within 30 days."


def _with(rpr: str = "", *, ppr: str = "", styles: bytes | None = None) -> tuple[str, list[str]]:
    """Extract a body with one visible paragraph and one paragraph whose run has
    ``rpr`` (and paragraph properties ``ppr``). Returns the joined text and the
    warning codes."""
    data = build_docx(Package(body=para(VISIBLE) + p(r(HIDDEN, rpr), ppr=ppr), styles=styles))
    result = extract(data)
    return joined(result), warning_codes(result)


def _removed(rpr: str = "", *, ppr: str = "", styles: bytes | None = None) -> set[str]:
    """The reasons in ``removed`` (counts are not asserted: their unit is the
    implementation's choice)."""
    data = build_docx(Package(body=para(VISIBLE) + p(r(HIDDEN, rpr), ppr=ppr), styles=styles))
    return set(reasons(extract(data)))


def _outcome(data: bytes) -> Any:
    """The result, or the error code. A ``basedOn`` cycle may be broken (text
    extracted) or fail closed with ``suspicious_package``; it must not hang."""
    try:
        return extract(data)
    except ExtractionError as error:
        return error.code


# --- Hidden formatting -----------------------------------------------------------------------


# w:webHidden is visible in print layout (review round 1, item 6).
@pytest.mark.parametrize("element", ["<w:vanish/>", "<w:specVanish/>"])
def test_hidden_direct_formatting_removed(element: str) -> None:
    text, _ = _with(element)

    assert HIDDEN not in text
    assert VISIBLE in text


# w:webHidden is visible in print layout (review round 1, item 6).
@pytest.mark.parametrize("element", ["<w:vanish/>", "<w:specVanish/>"])
def test_hidden_direct_formatting_reported(element: str) -> None:
    assert _removed(element) == {"hidden_formatting"}


@pytest.mark.parametrize("value", ["1", "true", "on"])
def test_hidden_on_values_removed(value: str) -> None:
    text, _ = _with(f'<w:vanish w:val="{value}"/>')

    assert HIDDEN not in text


@pytest.mark.parametrize("value", ["0", "false", "off"])
def test_hidden_off_values_kept(value: str) -> None:
    text, _ = _with(f'<w:vanish w:val="{value}"/>')

    assert HIDDEN in text


def test_hidden_sample_holds_removed_text() -> None:
    result = extract(body_docx(para(VISIBLE), p(r(HIDDEN, "<w:vanish/>"))))

    assert [x.reason for x in result.removed] == ["hidden_formatting"]
    assert HIDDEN[:50] in result.removed[0].sample
    assert len(result.removed[0].sample) <= 200


def test_hidden_long_text_sample_capped() -> None:
    result = extract(body_docx(para(VISIBLE), p(r("hidden words " * 100, "<w:vanish/>"))))

    assert len(result.removed[0].sample) <= 200


def test_hidden_part_of_paragraph_removed_rest_kept() -> None:
    result = extract(body_docx(p(r("The fee is "), r("not ", "<w:vanish/>"), r("refundable."))))

    assert texts(result) == ["The fee is refundable."]


def test_hidden_paragraph_mark_only_keeps_text() -> None:
    # A hidden paragraph mark (w:pPr/w:rPr/w:vanish) does not hide the runs.
    text, _ = _with(ppr="<w:rPr><w:vanish/></w:rPr>")

    assert HIDDEN in text


def test_hidden_in_footnote_removed() -> None:
    pkg = Package(body=para(VISIBLE), footnotes=[p(r(HIDDEN, "<w:vanish/>"))])

    assert HIDDEN not in joined(extract(build_docx(pkg)))


def test_hidden_in_header_removed() -> None:
    pkg = Package(body=para(VISIBLE), headers=[p(r(HIDDEN, "<w:vanish/>"))])

    assert HIDDEN not in joined(extract(build_docx(pkg)))


def test_all_text_hidden_no_text_extracted() -> None:
    with pytest.raises(ExtractionError) as info:
        extract(body_docx(p(r(HIDDEN, "<w:vanish/>"))))

    assert info.value.code == "no_text_extracted"


# --- Effective formatting chain ----------------------------------------------------------------


def test_chain_doc_defaults_hidden_removed() -> None:
    styles = styles_xml(default_rpr="<w:vanish/>")
    data = build_docx(
        Package(body=para(HIDDEN) + para(VISIBLE, '<w:vanish w:val="0"/>'), styles=styles)
    )

    assert texts(extract(data)) == [VISIBLE]


def test_chain_paragraph_style_hidden_removed() -> None:
    styles = styles_xml(style("HiddenPara", rpr="<w:vanish/>"))

    text, _ = _with(ppr='<w:pStyle w:val="HiddenPara"/>', styles=styles)

    assert HIDDEN not in text


def test_chain_based_on_chain_hidden_removed() -> None:
    styles = styles_xml(
        style("Base", rpr="<w:vanish/>"),
        style("Middle", based_on="Base"),
        style("Leaf", based_on="Middle"),
    )

    text, _ = _with(ppr='<w:pStyle w:val="Leaf"/>', styles=styles)

    assert HIDDEN not in text


def test_chain_based_on_override_shows_text() -> None:
    styles = styles_xml(
        style("Base", rpr="<w:vanish/>"),
        style("Leaf", based_on="Base", rpr='<w:vanish w:val="0"/>'),
    )

    text, _ = _with(ppr='<w:pStyle w:val="Leaf"/>', styles=styles)

    assert HIDDEN in text


def test_chain_based_on_cycle_terminates() -> None:
    styles = styles_xml(
        style("A", based_on="B", rpr="<w:vanish/>"),
        style("B", based_on="A"),
    )
    data = build_docx(
        Package(body=para(VISIBLE) + para(HIDDEN, ppr='<w:pStyle w:val="B"/>'), styles=styles)
    )

    started = time.monotonic()
    outcome = _outcome(data)

    assert time.monotonic() - started < 5
    assert outcome == "suspicious_package" or VISIBLE in joined(outcome)


def test_chain_self_based_on_terminates() -> None:
    styles = styles_xml(style("Self", based_on="Self"))
    data = build_docx(Package(body=para(VISIBLE, ppr='<w:pStyle w:val="Self"/>'), styles=styles))

    outcome = _outcome(data)

    assert outcome == "suspicious_package" or texts(outcome) == [VISIBLE]


def test_chain_character_style_hidden_removed() -> None:
    styles = styles_xml(style("HiddenChar", kind="character", rpr="<w:vanish/>"))

    text, _ = _with('<w:rStyle w:val="HiddenChar"/>', styles=styles)

    assert HIDDEN not in text


def test_chain_character_style_based_on_hidden_removed() -> None:
    styles = styles_xml(
        style("CharBase", kind="character", rpr="<w:vanish/>"),
        style("CharLeaf", kind="character", based_on="CharBase"),
    )

    text, _ = _with('<w:rStyle w:val="CharLeaf"/>', styles=styles)

    assert HIDDEN not in text


# Toggle properties (review round 0): tests/test_docx_round0.py.


def test_chain_direct_overrides_styles() -> None:
    styles = styles_xml(style("HiddenChar", kind="character", rpr="<w:vanish/>"))

    text, _ = _with('<w:rStyle w:val="HiddenChar"/><w:vanish w:val="0"/>', styles=styles)

    assert HIDDEN in text


def test_chain_direct_hidden_overrides_shown_style() -> None:
    styles = styles_xml(style("ShownChar", kind="character", rpr='<w:vanish w:val="0"/>'))

    text, _ = _with('<w:rStyle w:val="ShownChar"/><w:vanish/>', styles=styles)

    assert HIDDEN not in text


def test_chain_default_paragraph_style_applies_without_pstyle() -> None:
    hidden_default = (
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
        '<w:name w:val="Normal"/><w:rPr><w:color w:val="FFFFFF"/></w:rPr></w:style>'
    )
    data = build_docx(
        Package(
            body=para(HIDDEN) + para(VISIBLE, '<w:color w:val="000000"/>'),
            styles=styles_xml(hidden_default),
        )
    )

    assert texts(extract(data)) == [VISIBLE]


def test_chain_unknown_style_id_ignored() -> None:
    text, _ = _with('<w:rStyle w:val="Missing"/>', ppr='<w:pStyle w:val="AlsoMissing"/>')

    assert HIDDEN in text


def test_chain_style_colour_from_based_on_with_shading() -> None:
    styles = styles_xml(
        style("White", rpr='<w:color w:val="FFFFFF"/>'),
        style("WhiteOnBlack", based_on="White", rpr='<w:shd w:val="clear" w:fill="000000"/>'),
    )

    text, _ = _with(ppr='<w:pStyle w:val="WhiteOnBlack"/>', styles=styles)

    assert HIDDEN in text


# --- Same colour ---------------------------------------------------------------------------------


@pytest.mark.parametrize("colour", ["FFFFFF", "ffffff"])
def test_same_color_white_without_shading_removed(colour: str) -> None:
    assert _removed(f'<w:color w:val="{colour}"/>') == {"same_color"}


def test_same_color_white_on_white_shading_removed() -> None:
    rpr = '<w:color w:val="FFFFFF"/><w:shd w:val="clear" w:color="auto" w:fill="FFFFFF"/>'

    assert _removed(rpr) == {"same_color"}


def test_same_color_white_on_dark_shading_kept() -> None:
    rpr = '<w:color w:val="FFFFFF"/><w:shd w:val="clear" w:color="auto" w:fill="1F3864"/>'
    text, _ = _with(rpr)

    assert HIDDEN in text


def test_same_color_white_on_dark_paragraph_shading_kept() -> None:
    text, _ = _with('<w:color w:val="FFFFFF"/>', ppr='<w:shd w:val="clear" w:fill="000000"/>')

    assert HIDDEN in text


def test_same_color_text_equal_to_fill_removed() -> None:
    rpr = '<w:color w:val="00B050"/><w:shd w:val="clear" w:color="auto" w:fill="00B050"/>'

    assert _removed(rpr) == {"same_color"}


def test_same_color_text_equal_to_fill_case_insensitive_removed() -> None:
    rpr = '<w:color w:val="00b050"/><w:shd w:val="clear" w:fill="00B050"/>'

    assert _removed(rpr) == {"same_color"}


def test_same_color_text_different_from_fill_kept() -> None:
    rpr = '<w:color w:val="000000"/><w:shd w:val="clear" w:fill="00B050"/>'
    text, _ = _with(rpr)

    assert HIDDEN in text


def test_same_color_black_text_kept() -> None:
    text, warnings = _with('<w:color w:val="000000"/>')

    assert HIDDEN in text
    assert warnings == []


# --- Tiny text ----------------------------------------------------------------------------------


@pytest.mark.parametrize("size", ["1", "2"])
def test_tiny_text_size_at_most_two_half_points_removed(size: str) -> None:
    assert _removed(f'<w:sz w:val="{size}"/>') == {"tiny_text"}


@pytest.mark.parametrize("scale", ["1", "10", "19"])
def test_tiny_text_character_scale_below_20_percent_removed(scale: str) -> None:
    assert _removed(f'<w:w w:val="{scale}"/>') == {"tiny_text"}


def test_tiny_text_scale_20_percent_kept() -> None:
    text, _ = _with('<w:w w:val="20"/>')

    assert HIDDEN in text


def test_tiny_text_size_from_style_removed() -> None:
    styles = styles_xml(style("Tiny", kind="character", rpr='<w:sz w:val="2"/>'))

    text, _ = _with('<w:rStyle w:val="Tiny"/>', styles=styles)

    assert HIDDEN not in text


def test_tiny_text_complex_script_size_alone_not_tiny() -> None:
    # w:szCs applies to complex-script text only.
    text, _ = _with('<w:szCs w:val="2"/>')

    assert HIDDEN in text


# --- Borderline text: kept and flagged ---------------------------------------------------------


@pytest.mark.parametrize(
    "rpr",
    [
        '<w:sz w:val="8"/>',
        '<w:sz w:val="3"/>',
        '<w:color w:val="F2F2F2"/>',
        '<w:color w:val="FEFEFE"/>',
        '<w:spacing w:val="-20"/>',
        '<w:position w:val="-10"/>',
    ],
    ids=["size-8", "size-3", "near-white", "almost-white", "spacing", "position"],
)
def test_borderline_text_kept_and_warned(rpr: str) -> None:
    text, warnings = _with(rpr)

    assert HIDDEN in text
    assert "borderline_text" in warnings


@pytest.mark.parametrize(
    "rpr",
    [
        '<w:sz w:val="9"/>',
        '<w:sz w:val="22"/>',
        '<w:color w:val="808080"/>',
        '<w:spacing w:val="20"/>',
        '<w:position w:val="6"/>',
    ],
    ids=["size-9", "size-11pt", "grey", "spacing-positive", "position-positive"],
)
def test_normal_text_not_borderline(rpr: str) -> None:
    _, warnings = _with(rpr)

    assert "borderline_text" not in warnings


def test_borderline_text_not_in_removed() -> None:
    assert _removed('<w:sz w:val="8"/>') == set()


def test_borderline_warning_page_null() -> None:
    result = extract(body_docx(para(VISIBLE), p(r(HIDDEN, '<w:sz w:val="8"/>'))))

    assert [w.page for w in result.warnings if w.code == "borderline_text"] == [None]


def test_plain_document_has_no_removed_text() -> None:
    assert extract(body_docx(para(CLAUSE))).removed == []
