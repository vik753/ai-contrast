"""S3-T2 AC4, AC6, AC7, AC9: the DOCX walker (ADR 0009 Layer 0 and Layer 1).

Unit tests of ``extract_docx``. Must fail before the implementation exists.

Assumptions (see the test report): one block per non-empty paragraph; text-box
paragraphs are their own blocks with ``part == "textbox"``; header and footer
lines that are dropped are reported in ``removed`` (any reason); the Wingdings
mapping is F0FE -> ☑, F0FD -> ☒, F0A8 -> ☐, F06F -> ☐, F078 -> ☒.
"""

from __future__ import annotations

import pytest

from tests.docxbuild import (
    CLAUSE,
    CLAUSE_UK,
    REL_ALT_CHUNK,
    REL_HYPERLINK,
    REL_OLE,
    REL_SUBDOCUMENT,
    Package,
    Rel,
    body_docx,
    build_docx,
    p,
    para,
    r,
    t,
)
from tests.docxrun import code, extract, joined, texts, warning_codes

SUSPICIOUS = "suspicious_package"


def _one(*paragraphs: str) -> str:
    """The text of the only block of a body made of ``paragraphs``."""
    blocks = texts(extract(body_docx(*paragraphs)))
    assert len(blocks) == 1, blocks
    return blocks[0]


# --- AC4: runs, tabs, breaks, paragraphs ---------------------------------------------------------


def test_walker_runs_joined_in_one_block() -> None:
    assert _one(p(r("The Client "), r("pays "), r("in 30 days."))) == "The Client pays in 30 days."


def test_walker_one_block_per_paragraph() -> None:
    result = extract(body_docx(para("Clause one."), para("Clause two."), para("Clause three.")))

    assert texts(result) == ["Clause one.", "Clause two.", "Clause three."]


def test_walker_empty_paragraphs_give_no_block() -> None:
    result = extract(body_docx(para("Clause one."), "<w:p/>", p(), para("Clause two.")))

    assert texts(result) == ["Clause one.", "Clause two."]


def test_walker_tab_becomes_tab_character() -> None:
    assert _one(p(r(inner=t("Price") + "<w:tab/>" + t("100 EUR")))) == "Price\t100 EUR"


@pytest.mark.parametrize("element", ["<w:br/>", '<w:br w:type="page"/>', "<w:cr/>"])
def test_walker_breaks_become_line_feed(element: str) -> None:
    assert _one(p(r(inner=t("Line A") + element + t("Line B")))) == "Line A\nLine B"


def test_walker_no_break_hyphen_becomes_hyphen() -> None:
    assert _one(p(r(inner=t("e") + "<w:noBreakHyphen/>" + t("mail")))) == "e-mail"


def test_walker_soft_hyphen_dropped() -> None:
    assert _one(p(r(inner=t("pre") + "<w:softHyphen/>" + t("payment")))) == "prepayment"


def test_walker_paragraph_properties_text_not_read() -> None:
    # Run properties of the paragraph mark hold no text.
    ppr = '<w:pStyle w:val="Normal"/><w:rPr><w:b/></w:rPr>'

    assert _one(para(CLAUSE, ppr=ppr)) == CLAUSE


# --- AC4: revisions -----------------------------------------------------------------------------


def test_walker_insertion_included() -> None:
    ins = '<w:ins w:id="1" w:author="A" w:date="2026-01-01T00:00:00Z">' + r("not ") + "</w:ins>"

    assert _one(p(r("The fee is "), ins, r("refundable."))) == "The fee is not refundable."


def test_walker_deletion_excluded() -> None:
    deleted = '<w:del w:id="1" w:author="A"><w:r><w:delText>not </w:delText></w:r></w:del>'

    assert _one(p(r("The fee is "), deleted, r("refundable."))) == "The fee is refundable."


def test_walker_deletion_with_plain_text_element_excluded() -> None:
    # A crafted deletion that holds w:t instead of w:delText is still deleted.
    deleted = '<w:del w:id="1" w:author="A">' + r("not ") + "</w:del>"

    assert _one(p(r("The fee is "), deleted, r("refundable."))) == "The fee is refundable."


def test_walker_move_to_included_move_from_excluded() -> None:
    move_from = '<w:moveFrom w:id="1" w:author="A">' + r("Old place. ") + "</w:moveFrom>"
    move_to = '<w:moveTo w:id="2" w:author="A">' + r("New place.") + "</w:moveTo>"

    assert _one(p(move_from, move_to)) == "New place."


def test_walker_deleted_paragraph_excluded() -> None:
    deleted = (
        '<w:p><w:del w:id="1" w:author="A"><w:r><w:delText>Deleted clause.</w:delText>'
        "</w:r></w:del></w:p>"
    )

    assert texts(extract(body_docx(deleted, para(CLAUSE)))) == [CLAUSE]


# --- AC4: content controls, smart tags, custom XML ------------------------------------------------


def test_walker_inline_sdt_content_included() -> None:
    sdt = '<w:sdt><w:sdtPr><w:alias w:val="Amount"/></w:sdtPr><w:sdtContent>'
    sdt += r("500 EUR") + "</w:sdtContent></w:sdt>"

    assert _one(p(r("Amount: "), sdt)) == "Amount: 500 EUR"


def test_walker_block_sdt_content_included() -> None:
    sdt = (
        "<w:sdt><w:sdtPr/><w:sdtContent>"
        + para("Clause inside a control.")
        + ("</w:sdtContent></w:sdt>")
    )

    assert texts(extract(body_docx(para(CLAUSE), sdt))) == [CLAUSE, "Clause inside a control."]


def test_walker_sdt_placeholder_properties_not_read() -> None:
    sdt = (
        '<w:sdt><w:sdtPr><w:alias w:val="Hidden alias text"/><w:tag w:val="tag text"/>'
        "</w:sdtPr><w:sdtContent>" + r("Visible value") + "</w:sdtContent></w:sdt>"
    )

    assert _one(p(sdt)) == "Visible value"


def test_walker_smart_tag_included() -> None:
    tag = '<w:smartTag w:uri="urn:example" w:element="date">' + r("1 March 2026") + "</w:smartTag>"

    assert _one(p(r("Start: "), tag)) == "Start: 1 March 2026"


def test_walker_inline_custom_xml_included() -> None:
    tag = '<w:customXml w:element="party">' + r("Party A") + "</w:customXml>"

    assert _one(p(r("Seller: "), tag)) == "Seller: Party A"


def test_walker_block_custom_xml_included() -> None:
    tag = '<w:customXml w:element="clause">' + para("Clause in custom XML.") + "</w:customXml>"

    assert texts(extract(body_docx(tag))) == ["Clause in custom XML."]


def test_walker_hyperlink_text_included() -> None:
    link = '<w:hyperlink r:id="rIdLink">' + r("the price list") + "</w:hyperlink>"
    data = body_docx(
        p(r("See "), link, r(".")),
        doc_rels=[Rel("rIdLink", REL_HYPERLINK, "https://example.invalid/", external=True)],
    )

    assert texts(extract(data)) == ["See the price list."]


# --- AC4: fields -------------------------------------------------------------------------------


def test_walker_simple_field_result_included_code_excluded() -> None:
    field = '<w:fldSimple w:instr=" DOCPROPERTY Price \\* MERGEFORMAT ">' + r("100 EUR")
    field += "</w:fldSimple>"

    assert _one(p(r("Price: "), field)) == "Price: 100 EUR"


def _complex(code_text: str, result_runs: str) -> str:
    return (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        f'<w:r><w:instrText xml:space="preserve">{code_text}</w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        f"{result_runs}"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )


def test_walker_complex_field_result_included_code_excluded() -> None:
    field = _complex(" MERGEFIELD Amount ", r("500 EUR"))

    assert _one(p(r("Amount: "), field, r(" net."))) == "Amount: 500 EUR net."


def test_walker_complex_field_without_separate_has_no_text() -> None:
    field = (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> SECRET CODE </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )

    assert _one(p(r("Before "), field, r("after."))) == "Before after."


def test_walker_nested_complex_field_result_once() -> None:
    inner = _complex(" PAGE ", r("3"))
    outer = (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> IF </w:instrText></w:r>'
        + inner
        + '<w:r><w:instrText xml:space="preserve"> = 3 "yes" "no" </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        + r("Outcome")
        + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )

    assert _one(p(r("Field: "), outer)) == "Field: Outcome"


def test_walker_form_field_value_included() -> None:
    field = (
        '<w:r><w:fldChar w:fldCharType="begin"><w:ffData><w:name w:val="Text1"/>'
        "<w:textInput/></w:ffData></w:fldChar></w:r>"
        '<w:r><w:instrText xml:space="preserve"> FORMTEXT </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        + r("Party B (synthetic)")
        + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )

    assert _one(p(r("Buyer: "), field)) == "Buyer: Party B (synthetic)"


# --- AC4: text boxes and mc:AlternateContent ---------------------------------------------------


def _textbox(choice_text: str, fallback_text: str, requires: str = "wps") -> str:
    choice = (
        f'<mc:Choice Requires="{requires}"><w:drawing><wp:anchor><a:graphic><a:graphicData>'
        f"<wps:wsp><wps:txbx><w:txbxContent>{para(choice_text)}</w:txbxContent></wps:txbx>"
        "</wps:wsp></a:graphicData></a:graphic></wp:anchor></w:drawing></mc:Choice>"
    )
    fallback = (
        "<mc:Fallback><w:pict><v:shape><v:textbox><w:txbxContent>"
        f"{para(fallback_text)}</w:txbxContent></v:textbox></v:shape></w:pict></mc:Fallback>"
    )
    return p(r(inner=f"<mc:AlternateContent>{choice}{fallback}</mc:AlternateContent>"))


def test_walker_textbox_alternate_content_read_once() -> None:
    box = "Text box clause (synthetic)."
    result = extract(body_docx(para(CLAUSE), _textbox(box, box)))

    assert texts(result, "textbox") == [box]
    assert joined(result).count(box) == 1


def test_walker_textbox_known_choice_used() -> None:
    result = extract(body_docx(para(CLAUSE), _textbox("Choice copy.", "Fallback copy.")))

    assert texts(result, "textbox") == ["Choice copy."]


def test_walker_textbox_unknown_requires_uses_fallback() -> None:
    result = extract(body_docx(para(CLAUSE), _textbox("Choice copy.", "Fallback copy.", "xu")))

    assert texts(result, "textbox") == ["Fallback copy."]


def test_walker_body_text_part_is_body() -> None:
    result = extract(body_docx(para(CLAUSE), _textbox("Box.", "Box.")))

    assert [b.part for b in result.blocks if b.text == CLAUSE] == ["body"]


def test_walker_vml_only_textbox_read() -> None:
    vml = (
        "<w:pict><v:shape><v:textbox><w:txbxContent>"
        + para("VML text box clause.")
        + "</w:txbxContent></v:textbox></v:shape></w:pict>"
    )
    result = extract(body_docx(para(CLAUSE), p(r(inner=vml))))

    assert texts(result, "textbox") == ["VML text box clause."]


# --- AC4: parts and part labels ----------------------------------------------------------------


def test_walker_footnote_part_label() -> None:
    pkg = Package(body=para(CLAUSE), footnotes=[para("Footnote clause (synthetic).")])

    assert texts(extract(build_docx(pkg)), "footnote") == ["Footnote clause (synthetic)."]


def test_walker_endnote_part_label() -> None:
    pkg = Package(body=para(CLAUSE), endnotes=[para("Endnote clause (synthetic).")])

    assert texts(extract(build_docx(pkg)), "endnote") == ["Endnote clause (synthetic)."]


def test_walker_header_clause_kept_with_part_label() -> None:
    line = "Confidential: the Client shall not disclose this agreement."
    pkg = Package(body=para(CLAUSE), headers=[para(line)])

    assert texts(extract(build_docx(pkg)), "header") == [line]


def test_walker_footer_clause_kept_with_part_label() -> None:
    line = "Governing law: the law of the synthetic test country applies."
    pkg = Package(body=para(CLAUSE), footers=[para(line)])

    assert texts(extract(build_docx(pkg)), "footer") == [line]


def test_walker_footnote_separators_give_no_block() -> None:
    pkg = Package(body=para(CLAUSE), footnotes=[para("Note.")])

    assert sorted(texts(extract(build_docx(pkg)))) == sorted([CLAUSE, "Note."])


# --- AC4: header and footer page numbers and repeated lines -----------------------------------


@pytest.mark.parametrize(
    "line",
    [
        p('<w:fldSimple w:instr=" PAGE ">' + r("1") + "</w:fldSimple>"),
        p(
            '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
            + r("2")
            + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        ),
        para("7"),
        para("- 3 -"),
    ],
    ids=["simple-field", "complex-field", "digit", "dashes"],
)
def test_walker_footer_page_number_only_dropped(line: str) -> None:
    result = extract(build_docx(Package(body=para(CLAUSE), footers=[line])))

    assert texts(result, "footer") == []
    assert texts(result) == [CLAUSE]


def test_walker_footer_page_number_drop_counted() -> None:
    result = extract(build_docx(Package(body=para(CLAUSE), footers=[para("7")])))

    assert sum(item.count for item in result.removed) >= 1


def test_walker_header_page_number_only_dropped() -> None:
    result = extract(build_docx(Package(body=para(CLAUSE), headers=[para("12")])))

    assert texts(result, "header") == []


def test_walker_header_line_repeated_across_header_parts_not_duplicated() -> None:
    line = "Synthetic Holdings Ltd, agreement No. 0000/TEST"
    pkg = Package(body=para(CLAUSE), headers=[para(line), para(line), para(line)])
    result = extract(build_docx(pkg))

    assert texts(result, "header").count(line) <= 1
    assert sum(item.count for item in result.removed) >= 1


def test_walker_body_digit_paragraph_kept() -> None:
    # Only header and footer page numbers are dropped.
    result = extract(body_docx(para(CLAUSE), para("7")))

    assert texts(result) == [CLAUSE, "7"]


# --- AC6: symbols and checkboxes ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("char", "glyph"),
    [("F0FE", "☑"), ("F0FD", "☒"), ("F0A8", "☐"), ("F06F", "☐"), ("F078", "☒")],
)
def test_symbol_wingdings_checkbox_mapped(char: str, glyph: str) -> None:
    sym = f'<w:sym w:font="Wingdings" w:char="{char}"/>'

    assert _one(p(r(inner=sym), r(" insured"))) == f"{glyph} insured"


def test_symbol_lower_case_code_mapped() -> None:
    sym = '<w:sym w:font="Wingdings" w:char="f0fd"/>'

    assert _one(p(r(inner=sym), r(" insured"))) == "☒ insured"


def test_symbol_private_use_text_mapped() -> None:
    # The same glyph as a private-use character in w:t (Wingdings font).
    rpr = '<w:rFonts w:ascii="Wingdings" w:hAnsi="Wingdings"/>'

    assert _one(p(r("\uf0fe", rpr), r(" insured"))) == "☑ insured"


@pytest.mark.parametrize(("checked", "glyph"), [("1", "☒"), ("0", "☐"), ("true", "☒")])
def test_checkbox_content_control_by_checked_state(checked: str, glyph: str) -> None:
    sdt = (
        f'<w:sdt><w:sdtPr><w14:checkbox><w14:checked w14:val="{checked}"/>'
        '<w14:checkedState w14:val="2612" w14:font="MS Gothic"/>'
        '<w14:uncheckedState w14:val="2610" w14:font="MS Gothic"/></w14:checkbox></w:sdtPr>'
        "<w:sdtContent>" + r("☐" if glyph == "☒" else "☒") + "</w:sdtContent></w:sdt>"
    )

    assert _one(p(sdt, r(" Option A"))) == f"{glyph} Option A"


# --- AC7: material "Not read" warnings -------------------------------------------------------


def test_not_read_alt_chunk_warned() -> None:
    data = body_docx(
        para(CLAUSE),
        '<w:altChunk r:id="rIdAlt"/>',
        doc_rels=[Rel("rIdAlt", REL_ALT_CHUNK, "afchunk.htm")],
        extra=[("word/afchunk.htm", b"<html><body>Imported clause.</body></html>")],
    )
    result = extract(data)

    assert warning_codes(result) == ["not_read_altchunk"]
    assert all(w.page is None for w in result.warnings)


def test_not_read_alt_chunk_text_not_extracted() -> None:
    data = body_docx(
        para(CLAUSE),
        '<w:altChunk r:id="rIdAlt"/>',
        doc_rels=[Rel("rIdAlt", REL_ALT_CHUNK, "afchunk.htm")],
        extra=[("word/afchunk.htm", b"<html><body>Imported clause.</body></html>")],
    )

    assert "Imported clause." not in joined(extract(data))


@pytest.mark.parametrize(
    "inner",
    [
        '<w:object><v:shape id="s1"/><o:OLEObject Type="Embed" ProgID="Excel.Sheet.12" '
        'ShapeID="s1" r:id="rIdOle"/></w:object>',
        '<w:pict><o:OLEObject Type="Embed" ProgID="Word.Document.12" r:id="rIdOle"/></w:pict>',
    ],
    ids=["w-object", "o-oleobject"],
)
def test_not_read_ole_object_warned(inner: str) -> None:
    data = body_docx(
        para(CLAUSE),
        p(r(inner=inner)),
        doc_rels=[Rel("rIdOle", REL_OLE, "embeddings/oleObject1.bin")],
        extra=[("word/embeddings/oleObject1.bin", b"synthetic ole bytes")],
    )

    assert warning_codes(extract(data)) == ["not_read_object"]


def test_not_read_external_subdocument_warned() -> None:
    data = body_docx(
        para(CLAUSE),
        '<w:subDoc r:id="rIdSub"/>',
        doc_rels=[Rel("rIdSub", REL_SUBDOCUMENT, "file:///synthetic/annex.docx", external=True)],
    )

    assert warning_codes(extract(data)) == ["not_read_subdocument"]


def test_no_warnings_for_plain_document() -> None:
    assert extract(body_docx(para(CLAUSE))).warnings == []


def test_external_hyperlink_in_main_part_not_suspicious() -> None:
    data = body_docx(
        para(CLAUSE),
        doc_rels=[Rel("rIdLink", REL_HYPERLINK, "https://example.invalid/", external=True)],
    )

    assert texts(extract(data)) == [CLAUSE]


# --- AC4: depth and element caps fail closed -----------------------------------------------------


def _nested_sdt(depth: int) -> str:
    return "<w:sdt><w:sdtContent>" * depth + para(CLAUSE) + "</w:sdtContent></w:sdt>" * depth


def test_cap_xml_depth_exceeded_suspicious() -> None:
    assert code(body_docx(_nested_sdt(20)), max_xml_depth=16) == SUSPICIOUS


def test_cap_xml_depth_default_exceeded_suspicious() -> None:
    assert code(body_docx(_nested_sdt(200))) == SUSPICIOUS


def test_cap_xml_depth_below_default_extracted() -> None:
    assert texts(extract(body_docx(_nested_sdt(100)))) == [CLAUSE]


def test_cap_xml_depth_in_styles_suspicious() -> None:
    deep = "<w:x>" * 40 + "</w:x>" * 40
    styles = (
        '<?xml version="1.0"?>\n<w:styles xmlns:w="http://schemas.openxmlformats.org/'
        f'wordprocessingml/2006/main">{deep}</w:styles>'
    ).encode()

    assert code(build_docx(Package(body=para(CLAUSE), styles=styles)), max_xml_depth=16) == (
        SUSPICIOUS
    )


def test_cap_elements_exceeded_suspicious() -> None:
    assert code(body_docx(*[para("Clause.")] * 100), max_elements=200) == SUSPICIOUS


def test_cap_elements_counted_across_parts_suspicious() -> None:
    pkg = Package(body=para(CLAUSE) * 30, footnotes=[para("Note.")] * 30)

    assert code(build_docx(pkg), max_elements=150) == SUSPICIOUS


def test_cap_elements_in_ignored_markup_counted() -> None:
    # Elements the walker does not read still count.
    filler = "<w:bookmarkStart/>" * 500

    assert code(body_docx(p(filler, r(CLAUSE))), max_elements=300) == SUSPICIOUS


# --- AC9: result fields, language and text caps -------------------------------------------------


def test_result_pages_and_page_null() -> None:
    result = extract(body_docx(para(CLAUSE)))

    assert result.pages is None
    assert all(block.page is None for block in result.blocks)
    assert result.ocr_pages == []


def test_result_language_ukrainian() -> None:
    assert extract(body_docx(para(CLAUSE_UK), para(CLAUSE_UK))).language == "uk"


def test_result_language_english() -> None:
    assert extract(body_docx(para(CLAUSE), para(CLAUSE))).language == "en"


def test_result_empty_body_no_text_extracted() -> None:
    assert code(body_docx("<w:p/>", p(r("   ")))) == "no_text_extracted"


def test_result_only_deleted_text_no_text_extracted() -> None:
    deleted = (
        '<w:p><w:del w:id="1" w:author="A"><w:r><w:delText>Gone.</w:delText></w:r></w:del></w:p>'
    )

    assert code(body_docx(deleted)) == "no_text_extracted"


def test_result_too_many_characters_too_much_text() -> None:
    assert code(body_docx(para("a" * 101)), max_chars=100) == "too_much_text"


def test_result_too_many_blocks_too_much_text() -> None:
    assert code(body_docx(*[para("Clause.")] * 4), max_blocks=3) == "too_much_text"


def test_result_at_char_cap_extracted() -> None:
    assert texts(extract(body_docx(para("a" * 100)), max_chars=100)) == ["a" * 100]


def test_result_characters_counted_across_parts() -> None:
    pkg = Package(body=para("a" * 60), footnotes=[para("b" * 60)])

    assert code(build_docx(pkg), max_chars=100) == "too_much_text"
