"""S3-T2 developer tests: edge cases of the DOCX reader beyond the AC tests.

ZIP stream checks, OPC names, package guards, field balance, backgrounds, symbol
fonts, header and footer lines, the style-chain cache and the settings.
"""

from __future__ import annotations

import zlib

import pytest

from app.extraction.docx_styles import StyleDef, Styles
from app.extraction.docx_zip import check_part_name, part_key
from app.extraction.model import ExtractionError
from app.extraction.sandbox import SandboxLimits
from app.settings import Settings
from tests.docxbuild import (
    CLAUSE,
    REL_HEADER,
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
    stored_entries,
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


def test_white_text_on_dark_page_background_kept() -> None:
    xml = document_xml(para(CLAUSE) + para(HIDDEN, '<w:color w:val="FFFFFF"/>'))
    xml = xml.replace(b"<w:body>", b'<w:background w:color="000000"/><w:body>')

    assert HIDDEN in texts(extract(build_docx(Package(document=xml))))


def test_solid_shading_uses_pattern_colour() -> None:
    rpr = '<w:color w:val="FFFFFF"/><w:shd w:val="solid" w:color="000000" w:fill="FFFFFF"/>'

    assert HIDDEN in texts(extract(body_docx(para(CLAUSE), para(HIDDEN, rpr))))


def test_auto_colour_never_same_color() -> None:
    rpr = '<w:color w:val="auto"/><w:shd w:val="clear" w:fill="auto"/>'

    assert HIDDEN in texts(extract(body_docx(para(CLAUSE), para(HIDDEN, rpr))))


# --- Symbols ------------------------------------------------------------------------------------


def test_symbol_other_font_not_mapped() -> None:
    sym = '<w:sym w:font="Symbol" w:char="F06F"/>'

    assert texts(extract(body_docx(p(r(inner=sym), r(" omicron"))))) == ["omicron"]


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


def test_repeated_line_across_header_and_footer_kept_once() -> None:
    line = "Agreement No. 0000/TEST (synthetic)"
    result = extract(
        build_docx(Package(body=para(CLAUSE), headers=[para(line)], footers=[para(line)]))
    )

    assert texts(result, "header") == [line]
    assert texts(result, "footer") == []
    assert "repeated_header_footer" in reasons(result)


def test_not_read_warnings_deduplicated() -> None:
    obj = '<w:object><o:OLEObject Type="Embed" ProgID="Excel.Sheet.12"/></w:object>'

    assert warning_codes(extract(body_docx(para(CLAUSE), p(r(inner=obj)), p(r(inner=obj))))) == [
        "not_read_object"
    ]


# --- Style chains -------------------------------------------------------------------------------


def test_style_chain_cached_and_merged_root_first() -> None:
    styles = Styles(
        styles={
            "A": StyleDef(kind="character", rpr={"sz": 10, "color": "000000"}),
            "B": StyleDef(kind="character", based_on="A", rpr={"sz": 20}),
        }
    )

    assert styles.character("B") == {"sz": 20, "color": "000000"}
    assert styles.character("A") == {"sz": 10, "color": "000000"}


def test_style_chain_cycle_stops() -> None:
    styles = Styles(
        styles={
            "A": StyleDef(kind="character", based_on="B", rpr={"sz": 10}),
            "B": StyleDef(kind="character", based_on="A", rpr={"sz": 20}),
        }
    )

    assert styles.character("B") == {"sz": 20}


def test_style_chain_kind_mismatch_stops() -> None:
    styles = Styles(
        styles={
            "P": StyleDef(kind="paragraph", rpr={"vanish": True}),
            "C": StyleDef(kind="character", based_on="P", rpr={"sz": 20}),
        }
    )

    assert styles.character("C") == {"sz": 20}


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
