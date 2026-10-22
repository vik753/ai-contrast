"""S3-T2 review round 1 (PR #26), items 1-4, and the principle: remove text only
when its invisibility is resolved exactly; when an input cannot be resolved, keep
the text and add ``borderline_text``.

1. Colour and background: theme colours (``clrSchemeMapping``, tint, shade),
   ``auto``, run -> paragraph -> cell -> table style background, conditional table
   styles, page background with ``displayBackgroundShape``, ``w:szCs`` for complex
   script runs, sizes with units.
2. Markup compatibility: ``Requires`` allowlist, unknown ignorable elements.
3. Content controls: ``w:dataBinding``, checkbox controls.
4. Hidden objects, tracked deleted rows, duplicate note and relationship ids.

Theme tints and shades use the extreme values ``00`` (tint -> white, shade ->
black), so the tests do not depend on rounding.
"""

from __future__ import annotations

import pytest

from tests.docxbuild import (
    CLAUSE,
    NS_DECL,
    REL_FOOTNOTES,
    REL_HEADER,
    STANDARD_MAPPING,
    Package,
    Rel,
    body_docx,
    build_docx,
    document_xml,
    hdr_xml,
    p,
    para,
    r,
    rels_xml,
    settings_xml,
    styles_xml,
    theme_xml,
)
from tests.docxrun import code, extract, joined, reasons, texts, warning_codes

HIDDEN = "Hidden clause: the Client waives every claim (synthetic)."
SUSPICIOUS = "suspicious_package"
BORDERLINE = "borderline_text"


def _run(rpr: str, *, ppr: str = "", **pkg: object) -> tuple[bool, set[str], list[str]]:
    """Body = a visible clause + a paragraph with one run of ``HIDDEN``.
    Returns (HIDDEN is in the text, removed reasons, warning codes)."""
    data = build_docx(Package(body=para(CLAUSE) + p(r(HIDDEN, rpr), ppr=ppr), **pkg))  # type: ignore[arg-type]
    result = extract(data)
    return HIDDEN in joined(result), set(reasons(result)), warning_codes(result)


THEMED = {"theme": theme_xml(), "settings": settings_xml(STANDARD_MAPPING)}


# --- 1. Theme colours -------------------------------------------------------------------------


def test_theme_background1_text_removed_same_color() -> None:
    # w:val is a cache; the theme colour wins: background1 -> lt1 = FFFFFF.
    shown, removed, _ = _run('<w:color w:val="000000" w:themeColor="background1"/>', **THEMED)

    assert not shown
    assert removed == {"same_color"}


def test_theme_accent_equal_to_fill_removed() -> None:
    rpr = '<w:color w:val="000000" w:themeColor="accent1"/><w:shd w:val="clear" w:fill="00B050"/>'
    shown, removed, _ = _run(rpr, **THEMED)

    assert not shown
    assert removed == {"same_color"}


def test_theme_tint_00_is_white_removed() -> None:
    rpr = '<w:color w:val="1F3864" w:themeColor="accent2" w:themeTint="00"/>'
    shown, removed, _ = _run(rpr, **THEMED)

    assert not shown
    assert removed == {"same_color"}


def test_theme_shade_00_on_black_fill_removed() -> None:
    rpr = (
        '<w:color w:val="1F3864" w:themeColor="accent2" w:themeShade="00"/>'
        '<w:shd w:val="clear" w:fill="000000"/>'
    )
    shown, removed, _ = _run(rpr, **THEMED)

    assert not shown
    assert removed == {"same_color"}


def test_theme_fill_equal_to_text_removed() -> None:
    rpr = '<w:color w:val="00B050"/><w:shd w:val="clear" w:fill="FFFFFF" w:themeFill="accent1"/>'
    shown, _, _ = _run(rpr, **THEMED)

    assert not shown


def test_theme_mapping_background1_to_dark1_kept() -> None:
    mapping = STANDARD_MAPPING.replace('w:bg1="light1"', 'w:bg1="dark1"')
    shown, removed, _ = _run(
        '<w:color w:val="FFFFFF" w:themeColor="background1"/>',
        theme=theme_xml(),
        settings=settings_xml(mapping),
    )

    assert shown
    assert removed == set()


def test_theme_mapping_text1_to_light1_removed() -> None:
    mapping = STANDARD_MAPPING.replace('w:t1="dark1"', 'w:t1="light1"')
    shown, _, _ = _run(
        '<w:color w:val="000000" w:themeColor="text1"/>',
        theme=theme_xml(),
        settings=settings_xml(mapping),
    )

    assert not shown


def test_theme_colour_from_style_removed() -> None:
    styles = styles_xml(
        '<w:style w:type="character" w:styleId="Bg"><w:name w:val="Bg"/>'
        '<w:rPr><w:color w:val="000000" w:themeColor="background1"/></w:rPr></w:style>'
    )
    shown, _, _ = _run('<w:rStyle w:val="Bg"/>', styles=styles, **THEMED)

    assert not shown


# --- Principle: unresolved input -> kept + borderline ----------------------------------------


def test_theme_colour_without_theme_part_kept_borderline() -> None:
    shown, removed, warnings = _run('<w:color w:val="FFFFFF" w:themeColor="background1"/>')

    assert shown
    assert removed == set()
    assert BORDERLINE in warnings


def test_theme_colour_unknown_name_kept_borderline() -> None:
    shown, _, warnings = _run('<w:color w:val="FFFFFF" w:themeColor="noSuchColour"/>', **THEMED)

    assert shown
    assert BORDERLINE in warnings


def test_theme_fill_without_theme_part_kept_borderline() -> None:
    rpr = '<w:color w:val="00B050"/><w:shd w:val="clear" w:fill="00B050" w:themeFill="accent1"/>'
    shown, removed, warnings = _run(rpr)

    assert shown
    assert removed == set()
    assert BORDERLINE in warnings


# --- auto colour ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fill", ["", "FFFFFF", "000000", "auto"], ids=["none", "white", "black", "auto"]
)
def test_auto_colour_never_removed(fill: str) -> None:
    shd = f'<w:shd w:val="clear" w:fill="{fill}"/>' if fill else ""
    shown, removed, _ = _run(f'<w:color w:val="auto"/>{shd}')

    assert shown
    assert "same_color" not in removed


# --- Background chain: paragraph, cell, table style ------------------------------------------


def _table(cell_paragraph: str, *, tbl_style: str = "", tc_pr: str = "") -> str:
    tbl_pr = f'<w:tblPr><w:tblStyle w:val="{tbl_style}"/></w:tblPr>' if tbl_style else "<w:tblPr/>"
    tcp = f"<w:tcPr>{tc_pr}</w:tcPr>" if tc_pr else ""
    return (
        f'<w:tbl>{tbl_pr}<w:tblGrid><w:gridCol w:w="5000"/></w:tblGrid>'
        f"<w:tr><w:tc>{tcp}{cell_paragraph}</w:tc></w:tr></w:tbl>"
    )


WHITE = '<w:color w:val="FFFFFF"/>'


def _table_doc(table: str, styles: bytes | None = None) -> tuple[bool, set[str], list[str]]:
    result = extract(build_docx(Package(body=para(CLAUSE) + table, styles=styles)))
    return HIDDEN in joined(result), set(reasons(result)), warning_codes(result)


def test_white_text_on_dark_cell_kept() -> None:
    table = _table(p(r(HIDDEN, WHITE)), tc_pr='<w:shd w:val="clear" w:fill="1F3864"/>')

    shown, removed, _ = _table_doc(table)

    assert shown
    assert removed == set()


def test_white_text_on_white_cell_removed() -> None:
    table = _table(p(r(HIDDEN, WHITE)), tc_pr='<w:shd w:val="clear" w:fill="FFFFFF"/>')

    shown, removed, _ = _table_doc(table)

    assert not shown
    assert removed == {"same_color"}


def test_run_shading_over_cell_shading_decides() -> None:
    # Dark cell, but the run's own white shading is the background of the text.
    rpr = WHITE + '<w:shd w:val="clear" w:fill="FFFFFF"/>'
    table = _table(p(r(HIDDEN, rpr)), tc_pr='<w:shd w:val="clear" w:fill="000000"/>')

    shown, _, _ = _table_doc(table)

    assert not shown


def test_paragraph_shading_over_cell_shading_decides() -> None:
    cell = p(r(HIDDEN, WHITE), ppr='<w:shd w:val="clear" w:fill="000000"/>')
    table = _table(cell, tc_pr='<w:shd w:val="clear" w:fill="FFFFFF"/>')

    shown, _, _ = _table_doc(table)

    assert shown


def _table_style(style_id: str, inner: str, *, default: bool = False) -> str:
    flag = ' w:default="1"' if default else ""
    return (
        f'<w:style w:type="table"{flag} w:styleId="{style_id}"><w:name w:val="{style_id}"/>'
        f"{inner}</w:style>"
    )


DARK_TC = '<w:tcPr><w:shd w:val="clear" w:fill="000000"/></w:tcPr>'


def test_white_text_in_dark_table_style_kept() -> None:
    styles = styles_xml(_table_style("Dark", DARK_TC))

    shown, removed, _ = _table_doc(_table(p(r(HIDDEN, WHITE)), tbl_style="Dark"), styles)

    assert shown
    assert removed == set()


def test_white_text_in_dark_default_table_style_kept() -> None:
    styles = styles_xml(_table_style("DarkDefault", DARK_TC, default=True))

    shown, removed, _ = _table_doc(_table(p(r(HIDDEN, WHITE))), styles)

    assert shown
    assert removed == set()


def test_conditional_table_style_kept_borderline() -> None:
    conditional = (
        '<w:tblStylePr w:type="firstRow"><w:tcPr><w:shd w:val="clear" w:fill="000000"/>'
        "</w:tcPr></w:tblStylePr>"
    )
    styles = styles_xml(_table_style("Banded", conditional))

    shown, removed, warnings = _table_doc(_table(p(r(HIDDEN, WHITE)), tbl_style="Banded"), styles)

    assert shown
    assert removed == set()
    assert BORDERLINE in warnings


# --- Page background ------------------------------------------------------------------------

BLACK_PAGE = '<w:background w:color="000000"/>'


def _page(rpr: str, settings: bytes | None) -> tuple[bool, set[str]]:
    document = document_xml(para(CLAUSE) + p(r(HIDDEN, rpr)), before_body=BLACK_PAGE)
    result = extract(build_docx(Package(document=document, settings=settings)))
    return HIDDEN in joined(result), set(reasons(result))


def test_page_background_without_display_setting_ignored() -> None:
    shown, removed = _page(WHITE, settings_xml())

    assert not shown
    assert removed == {"same_color"}


def test_page_background_with_display_setting_white_text_kept() -> None:
    shown, removed = _page(WHITE, settings_xml("<w:displayBackgroundShape/>"))

    assert shown
    assert removed == set()


def test_page_background_with_display_setting_same_colour_removed() -> None:
    shown, _ = _page('<w:color w:val="000000"/>', settings_xml("<w:displayBackgroundShape/>"))

    assert not shown


# --- Complex script size and units --------------------------------------------------------------


@pytest.mark.parametrize("flag", ["<w:cs/>", "<w:rtl/>"], ids=["cs", "rtl"])
def test_complex_script_run_tiny_szcs_removed(flag: str) -> None:
    shown, removed, _ = _run(f'{flag}<w:sz w:val="22"/><w:szCs w:val="2"/>')

    assert not shown
    assert removed == {"tiny_text"}


def test_complex_script_run_tiny_sz_normal_szcs_kept() -> None:
    shown, removed, _ = _run('<w:cs/><w:sz w:val="2"/><w:szCs w:val="22"/>')

    assert shown
    assert "tiny_text" not in removed


def test_size_with_unit_parsed_tiny_removed() -> None:
    shown, removed, _ = _run('<w:sz w:val="1pt"/>')

    assert not shown
    assert removed == {"tiny_text"}


def test_size_with_unit_parsed_normal_kept() -> None:
    shown, removed, warnings = _run('<w:sz w:val="11pt"/>')

    assert shown
    assert removed == set()
    assert BORDERLINE not in warnings


# --- 2. Markup compatibility ----------------------------------------------------------------

W16SE = "http://schemas.microsoft.com/office/word/2015/wordml/symex"


def _alternate(requires: str, extra_decl: str = "") -> bytes:
    content = (
        f'<mc:AlternateContent><mc:Choice Requires="{requires}">'
        + r("Choice text.")
        + "</mc:Choice><mc:Fallback>"
        + r("Fallback text.")
        + "</mc:Fallback></mc:AlternateContent>"
    )
    return build_docx(
        Package(document=document_xml(para(CLAUSE) + p(content), decl=NS_DECL + extra_decl))
    )


def test_mc_choice_w16se_read() -> None:
    result = extract(_alternate("w16se", f' xmlns:w16se="{W16SE}"'))

    assert "Choice text." in joined(result)
    assert "Fallback text." not in joined(result)


def test_mc_choice_unknown_requires_suspicious() -> None:
    assert code(_alternate("xu")) == SUSPICIOUS


def test_mc_choice_one_unknown_of_several_requires_suspicious() -> None:
    assert code(_alternate("w14 xu")) == SUSPICIOUS


IGNORABLE_DECL = NS_DECL.replace('mc:Ignorable="w14 wp"', 'mc:Ignorable="w14 wp xu"')


def test_unknown_ignorable_element_with_text_suspicious() -> None:
    smuggled = "<xu:extra>" + r("Text in an unknown ignorable element.") + "</xu:extra>"
    data = build_docx(
        Package(document=document_xml(p(r("Visible. "), smuggled), decl=IGNORABLE_DECL))
    )

    assert code(data) == SUSPICIOUS


def test_unknown_ignorable_element_with_text_at_body_level_suspicious() -> None:
    smuggled = "<xu:extra>" + para("Paragraph in an unknown ignorable element.") + "</xu:extra>"
    data = build_docx(Package(document=document_xml(para(CLAUSE) + smuggled, decl=IGNORABLE_DECL)))

    assert code(data) == SUSPICIOUS


def test_unknown_ignorable_element_without_text_skipped() -> None:
    marker = '<xu:marker xu:val="1"/>'
    data = build_docx(Package(document=document_xml(p(marker, r(CLAUSE)), decl=IGNORABLE_DECL)))

    assert texts(extract(data)) == [CLAUSE]


# --- 3. Content controls ----------------------------------------------------------------------


def test_data_binding_text_kept_and_warned() -> None:
    sdt = (
        '<w:sdt><w:sdtPr><w:dataBinding w:xpath="/root/price" '
        'w:storeItemID="{00000000-0000-0000-0000-000000000001}"/></w:sdtPr>'
        "<w:sdtContent>" + r("100 EUR") + "</w:sdtContent></w:sdt>"
    )
    result = extract(body_docx(p(r("Price: "), sdt)))

    assert texts(result) == ["Price: 100 EUR"]
    assert "not_read_data_binding" in warning_codes(result)


def _checkbox(content: str, checked: str = "1") -> str:
    return (
        f'<w:sdt><w:sdtPr><w14:checkbox><w14:checked w14:val="{checked}"/></w14:checkbox>'
        f"</w:sdtPr><w:sdtContent>{content}</w:sdtContent></w:sdt>"
    )


def test_checkbox_control_keeps_its_other_runs() -> None:
    sdt = _checkbox(r("☐") + r(" Option A insured"))

    assert texts(extract(body_docx(p(sdt)))) == ["☒ Option A insured"]


def test_hidden_checkbox_control_has_no_symbol() -> None:
    sdt = _checkbox(r("☐", "<w:vanish/>"))
    result = extract(body_docx(p(sdt, r("Option A"))))

    assert texts(result) == ["Option A"]


# --- 4. Hidden objects --------------------------------------------------------------------------

BOX = "Text box clause inside a hidden object (synthetic)."


def _drawing(box: str, doc_pr: str = '<wp:docPr id="1" name="Box"/>') -> str:
    return (
        f"<w:drawing><wp:anchor>{doc_pr}<a:graphic><a:graphicData><wps:wsp><wps:txbx>"
        f"<w:txbxContent>{para(box)}</w:txbxContent></wps:txbx></wps:wsp></a:graphicData>"
        "</a:graphic></wp:anchor></w:drawing>"
    )


def _vml(box: str, style: str = "") -> str:
    attr = f' style="{style}"' if style else ""
    return (
        f"<w:pict><v:shape{attr}><v:textbox><w:txbxContent>{para(box)}</w:txbxContent>"
        "</v:textbox></v:shape></w:pict>"
    )


def _object(box: str) -> str:
    return (
        "<w:object><v:shape><v:textbox><w:txbxContent>"
        f"{para(box)}</w:txbxContent></v:textbox></v:shape></w:object>"
    )


@pytest.mark.parametrize(
    "inner", [_drawing(BOX), _vml(BOX), _object(BOX)], ids=["drawing", "pict", "object"]
)
def test_object_in_hidden_run_removed_with_run_reason(inner: str) -> None:
    hidden_run = f"<w:r><w:rPr><w:vanish/></w:rPr>{inner}</w:r>"
    result = extract(body_docx(para(CLAUSE), p(hidden_run)))

    assert BOX not in joined(result)
    assert "hidden_formatting" in reasons(result)


@pytest.mark.parametrize("style", ["visibility:hidden", "position:absolute; visibility: hidden"])
def test_vml_visibility_hidden_removed(style: str) -> None:
    result = extract(body_docx(para(CLAUSE), p(r(inner=_vml(BOX, style)))))

    assert BOX not in joined(result)
    assert "hidden_object" in reasons(result)


def test_drawing_docpr_hidden_removed() -> None:
    inner = _drawing(BOX, '<wp:docPr id="1" name="Box" hidden="1"/>')
    result = extract(body_docx(para(CLAUSE), p(r(inner=inner))))

    assert BOX not in joined(result)
    assert "hidden_object" in reasons(result)


def test_drawing_docpr_not_hidden_read() -> None:
    inner = _drawing(BOX, '<wp:docPr id="1" name="Box" hidden="0"/>')

    assert texts(extract(body_docx(para(CLAUSE), p(r(inner=inner)))), "textbox") == [BOX]


def test_tracked_deleted_table_row_excluded() -> None:
    deleted_row = (
        '<w:tr><w:trPr><w:del w:id="1" w:author="A" w:date="2026-01-01T00:00:00Z"/></w:trPr>'
        f"<w:tc>{para(HIDDEN)}</w:tc></w:tr>"
    )
    kept_row = f"<w:tr><w:tc>{para('Kept row.')}</w:tc></w:tr>"
    table = (
        '<w:tbl><w:tblPr/><w:tblGrid><w:gridCol w:w="5000"/></w:tblGrid>'
        f"{deleted_row}{kept_row}</w:tbl>"
    )
    result = extract(body_docx(para(CLAUSE), table))

    assert HIDDEN not in joined(result)
    assert "Kept row." in joined(result)


def test_duplicate_footnote_ids_suspicious() -> None:
    notes = (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<w:footnotes {NS_DECL}>'
        f'<w:footnote w:id="1">{para("Shown note.")}</w:footnote>'
        f'<w:footnote w:id="1">{para("Shadow note.")}</w:footnote></w:footnotes>'
    ).encode()
    pkg = Package(
        body=p(r(CLAUSE), '<w:r><w:footnoteReference w:id="1"/></w:r>'),
        doc_rels=[Rel("rIdFn", REL_FOOTNOTES, "footnotes.xml")],
        extra=[("word/footnotes.xml", notes)],
    )

    assert code(build_docx(pkg)) == SUSPICIOUS


def test_duplicate_relationship_ids_in_main_part_rels_suspicious() -> None:
    sections = ['<w:headerReference w:type="default" r:id="rIdX"/>']
    pkg = Package(
        body=para(CLAUSE),
        sections=sections,
        doc_rels_xml=rels_xml(
            [Rel("rIdX", REL_HEADER, "header1.xml"), Rel("rIdX", REL_HEADER, "header2.xml")]
        ),
        extra=[
            ("word/header1.xml", hdr_xml(para("Header one."))),
            ("word/header2.xml", hdr_xml(para("Header two."))),
        ],
    )

    assert code(build_docx(pkg)) == SUSPICIOUS


def test_duplicate_relationship_ids_in_root_rels_suspicious() -> None:
    root = rels_xml(
        [
            Rel(
                "rId1",
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
                "officeDocument",
                "word/document.xml",
            ),
            Rel(
                "rId1",
                "http://schemas.openxmlformats.org/package/2006/relationships/metadata/"
                "core-properties",
                "docProps/core.xml",
            ),
        ]
    )

    assert code(build_docx(Package(body=para(CLAUSE), root_rels=root))) == SUSPICIOUS
