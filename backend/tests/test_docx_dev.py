# ruff: noqa: RUF001 - Greek and symbol glyphs are the point of the symbol tests
"""S3-T2 developer tests: edge cases of the DOCX reader beyond the AC tests.

ZIP stream checks, OPC names, package guards, field balance, backgrounds, symbol
fonts, header and footer lines, the style-chain cache and the settings.
"""

from __future__ import annotations

import zlib
from collections.abc import Iterator

import pytest

from app.extraction.docx_zip import check_part_name, part_key
from app.extraction.model import ExtractionError
from app.extraction.sandbox import SandboxLimits
from app.settings import Settings
from tests.docxbuild import (
    CLAUSE,
    REL_HEADER,
    STANDARD_MAPPING,
    Package,
    Rel,
    body_docx,
    build_docx,
    deflate_raw,
    document_xml,
    layout,
    p,
    para,
    r,
    settings_xml,
    stored_entries,
    style,
    styles_xml,
    theme_xml,
)
from tests.docxrun import code, extract, reasons, texts, warning_codes
from tests.zipbuild import RawEntry, zipfile_archive

ARCHIVE = "archive_rejected"
SUSPICIOUS = "suspicious_package"
DOC_INDEX = 2


def _with_doc(entry: RawEntry) -> bytes:
    entries = stored_entries()
    entries[DOC_INDEX] = entry
    return layout(entries)


def _deflated(name: str, packed: bytes, data: bytes) -> RawEntry:
    return RawEntry(
        name=name,
        data=packed,
        method=8,
        compressed_size=len(packed),
        uncompressed_size=len(data),
        crc=zlib.crc32(data),
    )


# --- ZIP ------------------------------------------------------------------------------------


def test_zip_bytes_after_deflate_end_rejected() -> None:
    data = document_xml(para(CLAUSE))
    entry = _deflated("word/document.xml", deflate_raw(data) + b"tail", data)

    assert code(_with_doc(entry)) == ARCHIVE


def test_zip_truncated_deflate_stream_rejected() -> None:
    data = document_xml(para(CLAUSE))
    entry = _deflated("word/document.xml", deflate_raw(data)[:-8], data)

    assert code(_with_doc(entry)) == ARCHIVE


def test_zip_garbage_deflate_stream_rejected() -> None:
    data = document_xml(para(CLAUSE))
    entry = _deflated("word/document.xml", b"\xff" * 64, data)

    assert code(_with_doc(entry)) == ARCHIVE


def test_zip_encrypted_entry_rejected() -> None:
    entries = stored_entries()
    doc = entries[DOC_INDEX]
    entries[DOC_INDEX] = RawEntry(name=doc.name, data=doc.data, flags=0x0001)

    assert code(layout(entries)) == ARCHIVE


def test_zip_not_a_zip_rejected() -> None:
    assert code(b"PK\x03\x04 not an archive") == ARCHIVE


# --- OPC names ------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["word/a%2", "word/a%zz.xml", "word/%"])
def test_opc_malformed_percent_rejected(name: str) -> None:
    with pytest.raises(ExtractionError) as info:
        check_part_name(name)

    assert info.value.code == ARCHIVE


def test_opc_non_utf8_percent_sequence_rejected() -> None:
    with pytest.raises(ExtractionError) as info:
        part_key("word/%FF.xml")

    assert info.value.code == ARCHIVE


def test_opc_key_decodes_and_casefolds() -> None:
    assert part_key("Word/Stra%C3%9Fe.XML") == "word/strasse.xml"


# --- Package guards ---------------------------------------------------------------------------


def test_header_relationship_to_main_part_rejected() -> None:
    data = body_docx(para(CLAUSE), doc_rels=[Rel("rIdH", REL_HEADER, "document.xml")])

    assert code(data) == SUSPICIOUS


def test_header_relationship_to_missing_part_rejected() -> None:
    data = body_docx(para(CLAUSE), doc_rels=[Rel("rIdH", REL_HEADER, "missing.xml")])

    assert code(data) == SUSPICIOUS


def test_header_relationship_outside_package_rejected() -> None:
    data = body_docx(para(CLAUSE), doc_rels=[Rel("rIdH", REL_HEADER, "../../header.xml")])

    assert code(data) == SUSPICIOUS


def test_main_part_root_not_document_rejected() -> None:
    xml = b'<?xml version="1.0"?><w:glossaryDocument xmlns:w="urn:x"/>'

    assert code(build_docx(Package(document=xml))) == SUSPICIOUS


def test_malformed_xml_rejected() -> None:
    assert code(build_docx(Package(document=b"<w:document><w:body>"))) == SUSPICIOUS


def test_missing_content_types_rejected() -> None:
    parts = [(n, d) for n, d in Package(body=para(CLAUSE)).parts() if n != "[Content_Types].xml"]

    assert code(zipfile_archive(parts)) == SUSPICIOUS


# --- Fields -----------------------------------------------------------------------------------


def test_field_without_end_rejected() -> None:
    field = (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> QUOTE </w:instrText></w:r>'
    )

    assert code(body_docx(p(r("Start "), field), para(CLAUSE))) == SUSPICIOUS


def test_field_end_without_begin_ignored() -> None:
    end = '<w:r><w:fldChar w:fldCharType="end"/></w:r>'

    assert texts(extract(body_docx(p(end, r(CLAUSE))))) == [CLAUSE]


def test_math_text_read() -> None:
    math = (
        '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
        "<m:r><m:t>x+1</m:t></m:r></m:oMath>"
    )

    assert texts(extract(body_docx(p(r("Value: "), math)))) == ["Value: x+1"]


# --- Backgrounds and colours --------------------------------------------------------------------

HIDDEN = "White clause (synthetic)."


@pytest.mark.parametrize("highlight", ["black", "darkBlue"])
def test_white_text_on_dark_highlight_kept(highlight: str) -> None:
    rpr = f'<w:color w:val="FFFFFF"/><w:highlight w:val="{highlight}"/>'

    assert HIDDEN in texts(extract(body_docx(para(CLAUSE), para(HIDDEN, rpr))))


def test_white_text_on_white_highlight_removed() -> None:
    rpr = '<w:color w:val="FFFFFF"/><w:highlight w:val="white"/>'

    assert reasons(extract(body_docx(para(CLAUSE), para(HIDDEN, rpr)))) == {"same_color": 25}


def test_white_text_on_dark_page_background_with_theme_colour_kept() -> None:
    xml = document_xml(
        para(CLAUSE) + para(HIDDEN, '<w:color w:val="FFFFFF"/>'),
        before_body='<w:background w:color="FFFFFF" w:themeColor="text1"/>',
    )
    pkg = Package(
        document=xml,
        theme=theme_xml(),
        settings=settings_xml(STANDARD_MAPPING + "<w:displayBackgroundShape/>"),
    )

    assert HIDDEN in texts(extract(build_docx(pkg)))


def test_solid_shading_uses_pattern_colour() -> None:
    rpr = '<w:color w:val="FFFFFF"/><w:shd w:val="solid" w:color="000000" w:fill="FFFFFF"/>'

    assert HIDDEN in texts(extract(body_docx(para(CLAUSE), para(HIDDEN, rpr))))


def test_auto_colour_never_same_color() -> None:
    rpr = '<w:color w:val="auto"/><w:shd w:val="clear" w:fill="auto"/>'

    assert HIDDEN in texts(extract(body_docx(para(CLAUSE), para(HIDDEN, rpr))))


# --- Symbols ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("char", "glyph"), [("F06F", "ο"), ("F0B3", "≥"), ("F0D3", "©"), ("F031", "1")]
)
def test_symbol_font_mapped(char: str, glyph: str) -> None:
    sym = f'<w:sym w:font="Symbol" w:char="{char}"/>'
    result = extract(body_docx(p(r(inner=sym), r(" value"))))

    assert texts(result) == [f"{glyph} value"]
    assert result.warnings == []


@pytest.mark.parametrize(
    "sym",
    [
        '<w:sym w:font="Wingdings" w:char="F04A"/>',
        '<w:sym w:font="Webdings" w:char="F061"/>',
        '<w:sym w:font="Symbol" w:char="F0FF"/>',
    ],
    ids=["wingdings-smiley", "other-font", "symbol-unmapped"],
)
def test_symbol_unmapped_warned(sym: str) -> None:
    result = extract(body_docx(p(r(inner=sym), r(" value"))))

    assert texts(result) == ["value"]
    assert warning_codes(result) == ["not_read_symbol"]


def test_symbol_unmapped_in_hidden_run_not_warned() -> None:
    sym = '<w:sym w:font="Webdings" w:char="F061"/>'
    hidden = f"<w:r><w:rPr><w:vanish/></w:rPr>{sym}</w:r>"

    assert extract(body_docx(para(CLAUSE), p(hidden))).warnings == []


def test_symbol_font_private_use_text_mapped() -> None:
    rpr = '<w:rFonts w:ascii="Symbol" w:hAnsi="Symbol"/>'

    assert texts(extract(body_docx(p(r("\uf0b3", rpr), r(" 18"))))) == ["≥ 18"]


def test_symbol_short_code_mapped() -> None:
    sym = '<w:sym w:font="Wingdings" w:char="FE"/>'

    assert texts(extract(body_docx(p(r(inner=sym), r(" insured"))))) == ["☑ insured"]


def test_private_use_text_without_wingdings_kept() -> None:
    assert texts(extract(body_docx(p(r(" x"))))) == [" x"]


def test_checkbox_without_checked_state_unchecked() -> None:
    sdt = (
        "<w:sdt><w:sdtPr><w14:checkbox/></w:sdtPr><w:sdtContent>"
        + r("☒")
        + "</w:sdtContent></w:sdt>"
    )

    assert texts(extract(body_docx(p(sdt, r(" Option"))))) == ["☐ Option"]


def test_sdt_properties_run_formatting_ignored() -> None:
    sdt = (
        "<w:sdt><w:sdtPr><w:rPr><w:vanish/></w:rPr></w:sdtPr><w:sdtContent>"
        + r(CLAUSE)
        + "</w:sdtContent></w:sdt>"
    )

    assert texts(extract(body_docx(p(sdt)))) == [CLAUSE]


# --- Header and footer lines ------------------------------------------------------------------


@pytest.mark.parametrize(
    "line", ["Page 2 of 5", "Сторінка 3 з 10", "Страница 4", "3 / 9", "— 12 —"]
)
def test_footer_page_number_variants_dropped(line: str) -> None:
    result = extract(build_docx(Package(body=para(CLAUSE), footers=[para(line)])))

    assert texts(result, "footer") == []
    assert reasons(result) == {"page_number": len(line)}


def test_same_line_in_header_and_footer_kept_in_both() -> None:
    # The repeat filter works per kind: headers with headers, footers with footers.
    line = "Agreement No. 0000/TEST (synthetic)"
    result = extract(
        build_docx(Package(body=para(CLAUSE), headers=[para(line)], footers=[para(line)]))
    )

    assert texts(result, "header") == [line]
    assert texts(result, "footer") == [line]
    assert result.removed == []


def test_line_repeated_across_footer_parts_kept_once() -> None:
    line = "Agreement No. 0000/TEST (synthetic)"
    result = extract(build_docx(Package(body=para(CLAUSE), footers=[para(line), para(line)])))

    assert texts(result, "footer") == [line]
    assert [(x.reason, x.count) for x in result.removed] == [("repeated_header_footer", len(line))]


def test_not_read_warnings_deduplicated() -> None:
    obj = '<w:object><o:OLEObject Type="Embed" ProgID="Excel.Sheet.12"/></w:object>'

    assert warning_codes(extract(body_docx(para(CLAUSE), p(r(inner=obj)), p(r(inner=obj))))) == [
        "not_read_object"
    ]


# --- Style chains (document level) -------------------------------------------------------


def _style_run(rstyle: str, *styles: str) -> list[str]:
    data = build_docx(
        Package(
            body=para(CLAUSE) + p(r(HIDDEN, f'<w:rStyle w:val="{rstyle}"/>')),
            styles=styles_xml(*styles),
        )
    )
    return texts(extract(data))


def test_style_chain_root_property_inherited() -> None:
    styles = (
        style("A", kind="character", rpr='<w:color w:val="FFFFFF"/>'),
        style("B", kind="character", based_on="A", rpr='<w:sz w:val="24"/>'),
    )

    assert _style_run("B", *styles) == [CLAUSE]


def test_style_chain_leaf_overrides_root() -> None:
    styles = (
        style("A", kind="character", rpr='<w:color w:val="FFFFFF"/>'),
        style("B", kind="character", based_on="A", rpr='<w:color w:val="000000"/>'),
    )

    assert _style_run("B", *styles) == [CLAUSE, HIDDEN]


def test_style_chain_cycle_keeps_both_styles_once() -> None:
    styles = (
        style("A", kind="character", based_on="B", rpr='<w:sz w:val="2"/>'),
        style("B", kind="character", based_on="A", rpr='<w:sz w:val="24"/>'),
    )

    # B is the leaf: its size wins over A's in the chain B -> A.
    assert _style_run("B", *styles) == [CLAUSE, HIDDEN]


def test_style_chain_kind_mismatch_stops() -> None:
    styles = (
        style("P", rpr="<w:vanish/>"),
        style("C", kind="character", based_on="P", rpr='<w:sz w:val="24"/>'),
    )

    assert _style_run("C", *styles) == [CLAUSE, HIDDEN]


# --- Settings and sandbox limits --------------------------------------------------------------


def test_settings_docx_defaults() -> None:
    settings = Settings()

    assert (
        settings.max_docx_part_bytes,
        settings.max_docx_xml_depth,
        settings.max_docx_elements,
    ) == (32 * 1024 * 1024, 256, 2_000_000)


def test_sandbox_limits_docx_defaults_match_settings() -> None:
    limits = SandboxLimits(memory_bytes=1, cpu_seconds=1, wall_seconds=1, max_result_bytes=1)
    settings = Settings()

    assert (
        limits.docx_max_part_bytes,
        limits.docx_max_total_bytes,
        limits.docx_max_xml_depth,
        limits.docx_max_elements,
    ) == (
        settings.max_docx_part_bytes,
        settings.max_zip_uncompressed_bytes,
        settings.max_docx_xml_depth,
        settings.max_docx_elements,
    )


# --- Review round 0: displayed parts (developer tests) ---------------------------------------


def test_first_page_header_inherited_by_later_title_page_section() -> None:
    sections = [
        '<w:headerReference w:type="first" r:id="rIdH1"/>',
        "<w:titlePg/>",
    ]
    pkg = Package(body=para(CLAUSE), headers=[para("Inherited first.")], sections=sections)

    assert texts(extract(build_docx(pkg)), "header") == ["Inherited first."]


def test_footnote_referenced_only_from_hidden_run_not_displayed() -> None:
    ref = '<w:r><w:rPr><w:vanish/></w:rPr><w:footnoteReference w:id="1"/></w:r>'
    pkg = Package(body=para(CLAUSE) + p(ref), footnotes=[para("Hidden note.")], note_refs=False)
    result = extract(build_docx(pkg))

    assert texts(result, "footnote") == []
    assert [x.reason for x in result.removed] == ["not_displayed"]


def test_hidden_runs_in_one_paragraph_one_span() -> None:
    hidden = r("one ", "<w:vanish/>") + r("two", "<w:vanish/>")
    result = extract(body_docx(para(CLAUSE), p(r("Shown "), hidden)))

    assert [(x.reason, x.count, x.sample) for x in result.removed] == [
        ("hidden_formatting", 7, "one two")
    ]


# --- Review round 1, items 5 to 7 (developer tests) -------------------------------------------


def _form_field(ff_data: str, result: str = "") -> str:
    separate = '<w:r><w:fldChar w:fldCharType="separate"/></w:r>' + result if result else ""
    return (
        f'<w:r><w:fldChar w:fldCharType="begin"><w:ffData>{ff_data}</w:ffData></w:fldChar></w:r>'
        '<w:r><w:instrText xml:space="preserve"> FORMCHECKBOX </w:instrText></w:r>'
        f'{separate}<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )


@pytest.mark.parametrize(
    ("check_box", "glyph"),
    [
        ('<w:checkBox><w:sizeAuto/><w:default w:val="1"/></w:checkBox>', "☒"),
        ('<w:checkBox><w:sizeAuto/><w:default w:val="0"/></w:checkBox>', "☐"),
        ('<w:checkBox><w:default w:val="0"/><w:checked/></w:checkBox>', "☒"),
        ('<w:checkBox><w:default w:val="1"/><w:checked w:val="0"/></w:checkBox>', "☐"),
        ("<w:checkBox/>", "☐"),
    ],
    ids=["default-on", "default-off", "checked", "unchecked-over-default", "bare"],
)
def test_legacy_checkbox_form_field_state(check_box: str, glyph: str) -> None:
    field = _form_field(f'<w:name w:val="Check1"/><w:enabled/>{check_box}')

    assert texts(extract(body_docx(p(field, r(" Option A"))))) == [f"{glyph} Option A"]


def test_legacy_dropdown_form_field_selected_entry() -> None:
    ff_data = (
        '<w:ddList><w:result w:val="1"/><w:listEntry w:val="Monthly"/>'
        '<w:listEntry w:val="Quarterly"/></w:ddList>'
    )

    assert texts(extract(body_docx(p(r("Payment: "), _form_field(ff_data))))) == [
        "Payment: Quarterly"
    ]


def test_legacy_dropdown_without_result_first_entry() -> None:
    ff_data = '<w:ddList><w:listEntry w:val="Monthly"/><w:listEntry w:val="Yearly"/></w:ddList>'

    assert texts(extract(body_docx(p(r("Payment: "), _form_field(ff_data))))) == [
        "Payment: Monthly"
    ]


def test_legacy_text_form_field_reads_result() -> None:
    field = _form_field("<w:textInput/>", r("Party B (synthetic)"))

    assert texts(extract(body_docx(p(r("Buyer: "), field)))) == ["Buyer: Party B (synthetic)"]


@pytest.mark.parametrize(
    ("uri", "code_"),
    [
        ("http://schemas.openxmlformats.org/drawingml/2006/diagram", "not_read_diagram"),
        ("http://schemas.openxmlformats.org/drawingml/2006/chart", "not_read_chart"),
        ("http://schemas.microsoft.com/office/drawing/2014/chartex", "not_read_chart"),
    ],
)
def test_diagram_and_chart_warned(uri: str, code_: str) -> None:
    drawing = (
        '<w:drawing><wp:inline><wp:docPr id="1" name="Graphic"/><a:graphic>'
        f'<a:graphicData uri="{uri}"/></a:graphic></wp:inline></w:drawing>'
    )

    assert warning_codes(extract(body_docx(para(CLAUSE), p(r(inner=drawing))))) == [code_]


def test_picture_not_warned() -> None:
    uri = "http://schemas.openxmlformats.org/drawingml/2006/picture"
    drawing = (
        '<w:drawing><wp:inline><wp:docPr id="1" name="Picture"/><a:graphic>'
        f'<a:graphicData uri="{uri}"/></a:graphic></wp:inline></w:drawing>'
    )

    assert extract(body_docx(para(CLAUSE), p(r(inner=drawing)))).warnings == []


def test_wordart_warned() -> None:
    wordart = (
        '<w:pict><v:shape><v:textpath style="font-family:Arial" string="DRAFT"/></v:shape></w:pict>'
    )

    assert warning_codes(extract(body_docx(para(CLAUSE), p(r(inner=wordart))))) == [
        "not_read_wordart"
    ]


def test_wordart_in_hidden_object_not_warned() -> None:
    wordart = (
        '<w:pict><v:shape style="visibility:hidden"><v:textpath string="DRAFT"/></v:shape></w:pict>'
    )

    assert extract(body_docx(para(CLAUSE), p(r(inner=wordart)))).warnings == []


def test_web_hidden_text_kept() -> None:
    result = extract(body_docx(para(CLAUSE), para("Web hidden clause.", "<w:webHidden/>")))

    assert texts(result) == [CLAUSE, "Web hidden clause."]
    assert result.removed == []


def _complex_field(begin_attrs: str = "") -> str:
    return (
        f'<w:r><w:fldChar w:fldCharType="begin"{begin_attrs}/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> DATE </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        + r("1 March 2026")
        + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )


def test_dirty_complex_field_warned() -> None:
    result = extract(body_docx(p(r("Date: "), _complex_field(' w:dirty="true"'))))

    assert texts(result) == ["Date: 1 March 2026"]
    assert warning_codes(result) == ["field_may_update"]


def test_dirty_simple_field_warned() -> None:
    field = '<w:fldSimple w:instr=" DATE " w:dirty="1">' + r("1 March 2026") + "</w:fldSimple>"

    assert warning_codes(extract(body_docx(p(field)))) == ["field_may_update"]


def test_update_fields_setting_warns_once_for_fields() -> None:
    pkg = Package(
        body=p(_complex_field()) + p(_complex_field()),
        settings=settings_xml('<w:updateFields w:val="true"/>'),
    )

    assert warning_codes(extract(build_docx(pkg))) == ["field_may_update"]


def test_update_fields_setting_without_fields_not_warned() -> None:
    pkg = Package(body=para(CLAUSE), settings=settings_xml("<w:updateFields/>"))

    assert extract(build_docx(pkg)).warnings == []


def test_clean_field_not_warned() -> None:
    assert extract(body_docx(p(_complex_field()))).warnings == []


def test_hidden_text_count_full_and_sample_short() -> None:
    hidden = "hidden words " * 20_000
    result = extract(body_docx(para(CLAUSE), p(r(hidden, "<w:vanish/>"))))

    assert [x.count for x in result.removed] == [len(hidden.strip())]
    assert result.removed[0].sample.startswith("hidden words hidden words")
    assert len(result.removed[0].sample) <= 200


def test_not_displayed_header_count_full_and_sample_short() -> None:
    long_line = "header words " * 10_000
    result = extract(
        build_docx(Package(body=para(CLAUSE), headers=[para(long_line)], sections=[""]))
    )

    assert [(x.reason, x.count) for x in result.removed] == [
        ("not_displayed", len(long_line.strip()))
    ]
    assert len(result.removed[0].sample) <= 200


def test_span_keeps_only_the_head() -> None:
    from app.extraction.docx import HEAD_CHARS, _Span  # noqa: PLC0415 - internal detail

    span = _Span("hidden_formatting")
    for _ in range(1000):
        span.add("x" * 100)

    assert span.size() == 100_000
    assert sum(len(piece) for piece in span.head) == HEAD_CHARS


# --- Parsing memory and the part stream ------------------------------------------------------


def test_iter_xml_detaches_elements_peak_memory_flat() -> None:
    import tracemalloc  # noqa: PLC0415

    from app.extraction.docx_xml import XmlBudget, iter_xml  # noqa: PLC0415
    from app.extraction.docx_zip import PartStream  # noqa: PLC0415

    def chunks(paragraphs: int) -> Iterator[bytes]:
        # Produced lazily, so that the input does not count in the peak.
        yield b"<d>"
        for _ in range(paragraphs // 500):
            yield b"<p><r><t>clause</t></r></p>" * 500
        yield b"</d>"

    def peak(paragraphs: int) -> int:
        budget = XmlBudget(max_depth=64, max_elements=10**7)
        tracemalloc.start()
        try:
            for _ in iter_xml(PartStream(chunks(paragraphs)), budget):
                pass
            return tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()

    small, large = peak(2_000), peak(40_000)
    # 20 times more elements: detached elements are freed, so the peak stays flat
    # (without detaching it grows by about 3 MB here).
    assert large - small < 1_000_000


def test_part_stream_read_all() -> None:
    from app.extraction.docx_zip import PartStream  # noqa: PLC0415

    stream = PartStream(iter([b"abc", b"def", b"ghi"]))

    assert stream.read(2) == b"ab"
    assert stream.read() == b"cdefghi"
    assert stream.read() == b""
    assert stream.read(5) == b""


def test_docx_limits_defaults_match_settings() -> None:
    from app.extraction.docx import DocxLimits  # noqa: PLC0415

    settings = Settings()

    assert DocxLimits() == DocxLimits(
        max_part_bytes=settings.max_docx_part_bytes,
        max_total_bytes=settings.max_zip_uncompressed_bytes,
        max_xml_depth=settings.max_docx_xml_depth,
        max_elements=settings.max_docx_elements,
    )


# --- Round 1 item 1: unresolved inputs (developer tests) --------------------------------------


def test_theme_tint_that_needs_rounding_kept_borderline() -> None:
    # accent3 A5A5A5 with tint 40: about F2F2F2 on white, rounding unknown -> kept.
    rpr = '<w:color w:val="F2F2F2" w:themeColor="accent3" w:themeTint="1A"/>'
    pkg = Package(
        body=para(CLAUSE) + para(HIDDEN, rpr),
        theme=theme_xml(),
        settings=settings_xml(STANDARD_MAPPING),
    )
    result = extract(build_docx(pkg))

    assert HIDDEN in texts(result)
    assert "borderline_text" in warning_codes(result)


def test_black_text_with_black_conditional_fill_borderline() -> None:
    table_style = (
        '<w:style w:type="table" w:styleId="Banded"><w:name w:val="Banded"/>'
        '<w:tblStylePr w:type="firstRow"><w:tcPr><w:shd w:val="clear" w:fill="000000"/>'
        "</w:tcPr></w:tblStylePr></w:style>"
    )
    cell = para(HIDDEN, '<w:color w:val="000000"/>')
    table = (
        '<w:tbl><w:tblPr><w:tblStyle w:val="Banded"/></w:tblPr><w:tblGrid><w:gridCol/>'
        f"</w:tblGrid><w:tr><w:tc>{cell}</w:tc></w:tr></w:tbl>"
    )
    result = extract(build_docx(Package(body=para(CLAUSE) + table, styles=styles_xml(table_style))))

    assert HIDDEN in texts(result)
    assert "borderline_text" in warning_codes(result)


def test_shading_pattern_same_colour_kept_borderline() -> None:
    rpr = '<w:color w:val="FFFFFF"/><w:shd w:val="pct10" w:color="000000" w:fill="FFFFFF"/>'
    result = extract(body_docx(para(CLAUSE), para(HIDDEN, rpr)))

    assert HIDDEN in texts(result)
    assert "borderline_text" in warning_codes(result)
