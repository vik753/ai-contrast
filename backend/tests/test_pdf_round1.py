# ruff: noqa: RUF001 - Cyrillic contract samples are the point of these tests
"""S3-T3 review round 1 (PR #29), items 1-7 of docs/agent/TASKS.md.

Principle: remove only when invisibility is exact; otherwise keep the text and add
``borderline_text``; content that pdfminer does not run is a material
``not_read_*`` warning. Fixtures: ``tests/pdfbuild.py`` (synthetic text only).

Written before the round-1 fixes: tests of new behaviour fail with an assertion
(or with no ``ExtractionError``) until the implementation follows.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.extraction.model import Block, ExtractionResult
from app.extraction.text import extract_text_file
from tests.pdfbuild import (
    EXTRA,
    SHADING,
    Encryption,
    Obj,
    Page,
    annot_with_ap,
    appearance,
    build_pdf,
    content_obj,
    drop_trailer,
    form_xobject,
    free_text_annot,
    full_page_image,
    incremental_update,
    latin_string,
    linearized_pdf,
    lines,
    paragraphs,
    rect,
    replace_content,
    resources,
    stream_obj,
    text,
    text_pdf,
    tiling_pattern,
    type3_objects,
    xrefstm_loop,
)
from tests.pdfrun import code, extract, reasons, squashed, texts, warning_codes, warnings_of

CLAUSE = "Clause 1. The Insurer pays the insured sum within ten days (synthetic)."
CLAUSE_2 = "Clause 2. The Client pays the premium every month (synthetic)."
HIDDEN = "Hidden clause: the Client waives every claim (synthetic)."
HIDDEN_KEY = "Hiddenclause"
WHITE_POINT = "/WhitePoint [0.9505 1 1.089]"


def hidden_ops(fill: str = "", prefix: str = "") -> str:
    """``HIDDEN`` at y = 600 with raw colour/state operators before the text."""
    return f"q {prefix} {fill}\nBT /F1 12 Tf 72 600 Td {latin_string(HIDDEN)} Tj ET\nQ\n"


def page_pdf(ops: str, *, res: str | None = None, extra: dict[int, Obj] | None = None) -> bytes:
    return build_pdf(Page(text(CLAUSE, 72, 720) + ops, resources=res), extra=extra)


def assert_removed(data: bytes, reason: str) -> None:
    result = extract(data)
    assert texts(result) == [CLAUSE]
    assert reason in reasons(result)


def assert_borderline(data: bytes) -> None:
    result = extract(data)
    assert HIDDEN_KEY in squashed(result)
    assert not set(reasons(result)) - {"page_number"}
    assert warnings_of(result, "borderline_text") == [1]


def assert_clean(data: bytes) -> None:
    result = extract(data)
    assert HIDDEN_KEY in squashed(result)
    assert not reasons(result)
    assert warning_codes(result) == []


# --- Item 1: content pdfminer does not run -------------------------------------------------------

AP = EXTRA


def annotated(*annots: str) -> bytes:
    return build_pdf(
        Page(text(CLAUSE), annots=annots), extra={AP: appearance("Stamp: paid (synthetic)")}
    )


def test_stamp_annotation_with_appearance_not_read_annotation() -> None:
    assert warnings_of(extract(annotated(annot_with_ap("Stamp", AP))), "not_read_annotation") == [1]


def test_free_text_empty_contents_with_appearance_not_read_annotation() -> None:
    annot = annot_with_ap("FreeText", AP, extra=" /Contents () /DA (/Helv 12 Tf 0 g)")

    assert warnings_of(extract(annotated(annot)), "not_read_annotation") == [1]


@pytest.mark.parametrize("flags", [2, 32, 34], ids=["hidden", "noview", "both"])
def test_hidden_or_noview_annotation_with_appearance_ignored(flags: int) -> None:
    result = extract(annotated(annot_with_ap("Stamp", AP, flags=flags)))

    assert "not_read_annotation" not in warning_codes(result)


@pytest.mark.parametrize("flags", [2, 32])
def test_hidden_or_noview_free_text_with_value_ignored(flags: int) -> None:
    annot = free_text_annot("Synthetic note").replace("/Type /Annot", f"/Type /Annot /F {flags}")

    assert "not_read_annotation" not in warning_codes(extract(annotated(annot)))


def test_print_flag_annotation_with_appearance_not_read_annotation() -> None:
    result = extract(annotated(annot_with_ap("Stamp", AP, flags=4)))

    assert warnings_of(result, "not_read_annotation") == [1]


@pytest.mark.parametrize("subtype", ["Link", "Popup"])
def test_link_or_popup_with_appearance_ignored(subtype: str) -> None:
    result = extract(annotated(annot_with_ap(subtype, AP)))

    assert "not_read_annotation" not in warning_codes(result)


def test_widget_value_from_parent_field_not_read_annotation() -> None:
    parent = EXTRA + 1
    widget = (
        f"<< /Type /Annot /Subtype /Widget /Rect [72 500 300 520] /Parent {parent} 0 R "
        "/DA (/Helv 12 Tf 0 g) >>"
    )
    extra = {parent: Obj("<< /FT /Tx /T (field1) /V (Synthetic parent value) >>")}
    data = build_pdf(Page(text(CLAUSE), annots=[widget]), extra=extra)

    assert warnings_of(extract(data), "not_read_annotation") == [1]


def test_annotations_above_cap_not_read_annotation() -> None:
    # MAX_ANNOTATIONS is 1000; the cap fails closed with the material warning.
    empty = "<< /Type /Annot /Subtype /Text /Rect [500 700 520 720] >>"
    data = build_pdf(Page(text(CLAUSE), annots=[empty] * 1001))

    assert warnings_of(extract(data), "not_read_annotation") == [1]


def test_annotations_at_cap_without_value_no_warning() -> None:
    empty = "<< /Type /Annot /Subtype /Text /Rect [500 700 520 720] >>"
    data = build_pdf(Page(text(CLAUSE), annots=[empty] * 1000))

    assert "not_read_annotation" not in warning_codes(extract(data))


def test_tiling_pattern_with_text_not_read_pattern() -> None:
    cell = f"BT /F1 12 Tf 72 600 Td {latin_string(HIDDEN)} Tj ET\n"
    res = resources(pattern=f"/P1 {EXTRA} 0 R")
    data = page_pdf(
        "q /Pattern cs /P1 scn 0 0 612 792 re f Q\n", res=res, extra={EXTRA: tiling_pattern(cell)}
    )

    assert warnings_of(extract(data), "not_read_pattern") == [1]


def test_tiling_pattern_without_text_no_warning() -> None:
    res = resources(pattern=f"/P1 {EXTRA} 0 R")
    cell = "0 0 1 rg 0 0 10 10 re f\n"
    data = page_pdf(
        "q /Pattern cs /P1 scn 0 0 612 100 re f Q\n", res=res, extra={EXTRA: tiling_pattern(cell)}
    )

    assert "not_read_pattern" not in warning_codes(extract(data))


def type3_page(ops: str, **font: float | bool) -> bytes:
    res = resources(font=f"/F3 {EXTRA} 0 R")
    return page_pdf(ops, res=res, extra=type3_objects(EXTRA, **font))  # type: ignore[arg-type]


def test_type3_font_without_to_unicode_not_read_type3() -> None:
    data = type3_page("BT /F3 12 Tf 72 600 Td (Synthetic Type3 words) Tj ET\n")

    assert warnings_of(extract(data), "not_read_type3") == [1]


def test_type3_font_with_to_unicode_read_without_warning() -> None:
    data = type3_page("BT /F3 12 Tf 72 600 Td (Synthetic Type3 words) Tj ET\n", to_unicode=True)

    result = extract(data)

    assert "SyntheticType3words" in squashed(result)
    assert "not_read_type3" not in warning_codes(result)


def test_form_xobject_without_bbox_text_read() -> None:
    form = form_xobject(f"BT /F1 12 Tf 72 600 Td {latin_string(HIDDEN)} Tj ET\n", bbox=None)
    data = page_pdf(
        "q /Fm0 Do Q\n", res=resources(xobject=f"/Fm0 {EXTRA} 0 R"), extra={EXTRA: form}
    )

    assert_clean(data)


def test_font_set_through_extgstate_text_read() -> None:
    res = resources(extgstate="/GSF << /Type /ExtGState /Font [3 0 R 12] >>")
    data = page_pdf(f"BT /GSF gs 72 600 Td {latin_string(HIDDEN)} Tj ET\n", res=res)

    assert_clean(data)


def test_tiny_font_set_through_extgstate_removed() -> None:
    res = resources(extgstate="/GSF << /Type /ExtGState /Font [3 0 R 0.5] >>")
    data = page_pdf(f"BT /GSF gs 72 600 Td {latin_string(HIDDEN)} Tj ET\n", res=res)

    assert_removed(data, "tiny_text")


# --- Item 2: colour spaces, alpha, render modes --------------------------------------------------


def colour_page(colorspace: str, fill: str, extra: dict[int, Obj] | None = None) -> bytes:
    res = resources(colorspace=colorspace)
    return page_pdf(hidden_ops(fill), res=res, extra=extra)


ICC = {EXTRA + n: stream_obj("synthetic-profile", f"<< /N {n} >>") for n in (1, 3, 4)}
DEVICE_N_FN = EXTRA + 10
SEPARATION_FN = "<< /FunctionType 2 /Domain [0 1] /C0 [0 0 0 0] /C1 [0 0 0 1] /N 1 >>"

WHITE_SPACES = {
    "calgray": (f"/Cs0 [/CalGray << {WHITE_POINT} >>]", "/Cs0 cs 1 sc"),
    "calrgb": (f"/Cs0 [/CalRGB << {WHITE_POINT} >>]", "/Cs0 cs 1 1 1 sc"),
    "lab": (f"/Cs0 [/Lab << {WHITE_POINT} /Range [-100 100 -100 100] >>]", "/Cs0 cs 100 0 0 sc"),
    "icc1": (f"/Cs0 [/ICCBased {EXTRA + 1} 0 R]", "/Cs0 cs 1 sc"),
    "icc3": (f"/Cs0 [/ICCBased {EXTRA + 3} 0 R]", "/Cs0 cs 1 1 1 sc"),
    "icc4": (f"/Cs0 [/ICCBased {EXTRA + 4} 0 R]", "/Cs0 cs 0 0 0 0 sc"),
    "indexed": ("/Cs0 [/Indexed /DeviceRGB 1 <000000FFFFFF>]", "/Cs0 cs 1 sc"),
    "separation": (f"/Cs0 [/Separation /Spot1 /DeviceCMYK {SEPARATION_FN}]", "/Cs0 cs 0 scn"),
    "devicen": (
        f"/Cs0 [/DeviceN [/Spot1 /Spot2] /DeviceCMYK {DEVICE_N_FN} 0 R]",
        "/Cs0 cs 0 0 scn",
    ),
}
COLOUR_EXTRA = {
    **ICC,
    DEVICE_N_FN: stream_obj(
        "{ pop pop 0 0 0 1 }",
        "<< /FunctionType 4 /Domain [0 1 0 1] /Range [0 1 0 1 0 1 0 1] >>",
    ),
}


@pytest.mark.parametrize("space", list(WHITE_SPACES))
def test_white_in_resolvable_colour_space_removed(space: str) -> None:
    colorspace, fill = WHITE_SPACES[space]

    assert_removed(colour_page(colorspace, fill, COLOUR_EXTRA), "same_color")


def test_indexed_black_entry_kept_without_flags() -> None:
    assert_clean(colour_page("/Cs0 [/Indexed /DeviceRGB 1 <000000FFFFFF>]", "/Cs0 cs 0 sc"))


def test_separation_full_tint_kept_without_flags() -> None:
    colorspace = f"/Cs0 [/Separation /Spot1 /DeviceCMYK {SEPARATION_FN}]"

    assert_clean(colour_page(colorspace, "/Cs0 cs 1 scn"))


def test_pattern_colour_text_kept_borderline() -> None:
    assert_borderline(page_pdf(hidden_ops("/Pattern cs /P0 scn")))


def test_alpha_one_hundredth_kept_borderline() -> None:
    res = resources(extgstate="/GSA << /Type /ExtGState /ca 0.01 >>")

    assert_borderline(page_pdf(hidden_ops(prefix="/GSA gs"), res=res))


@pytest.mark.parametrize("mode", [11, -1])
def test_render_mode_outside_range_kept_borderline(mode: int) -> None:
    assert_borderline(page_pdf(text(HIDDEN, 72, 600, render=mode)))


# --- Tech-lead decisions: graphics state of Form XObjects, blend modes, soft masks ---------------


def form_page(prefix: str, *, bbox: str | None = "0 0 612 792", res_extra: str = "") -> bytes:
    form = form_xobject(f"BT /F1 12 Tf 72 600 Td {latin_string(HIDDEN)} Tj ET\n", bbox=bbox)
    res = resources(xobject=f"/Fm0 {EXTRA} 0 R", extgstate=res_extra)
    return page_pdf(f"q {prefix} /Fm0 Do Q\n", res=res, extra={EXTRA: form})


def test_form_xobject_inherits_white_fill_removed() -> None:
    assert_removed(form_page("1 g"), "same_color")


def test_form_xobject_inherits_alpha_zero_removed() -> None:
    assert_removed(form_page("/GS0 gs"), "transparent")


def test_white_text_with_blend_mode_kept_borderline() -> None:
    res = resources(extgstate="/GSB << /Type /ExtGState /BM /Multiply >>")

    assert_borderline(page_pdf(hidden_ops("1 g", "/GSB gs"), res=res))


def test_white_text_with_soft_mask_kept_borderline() -> None:
    mask = form_xobject("1 g 0 0 612 792 re f\n")
    smask = f"/GSM << /Type /ExtGState /SMask << /Type /Mask /S /Luminosity /G {EXTRA} 0 R >> >>"
    data = page_pdf(
        hidden_ops("1 g", "/GSM gs"), res=resources(extgstate=smask), extra={EXTRA: mask}
    )

    assert_borderline(data)


# --- Item 5: backgrounds and sizes ---------------------------------------------------------------


def test_white_text_on_stroked_path_kept_borderline() -> None:
    stroke = "q 0 0 0 RG 24 w 60 604 m 560 604 l S Q\n"

    assert_borderline(page_pdf(stroke + hidden_ops("1 g")))


def test_white_text_on_sh_shading_kept_borderline() -> None:
    res = resources(shading=f"/Sh0 {SHADING}")

    assert_borderline(page_pdf("q /Sh0 sh Q\n" + hidden_ops("1 g"), res=res))


def test_white_text_on_light_grey_fill_kept_borderline() -> None:
    assert_borderline(page_pdf(rect(60, 590, 500, 30, "0.95 g") + hidden_ops("1 g")))


def test_light_text_with_small_difference_on_known_fill_kept_borderline() -> None:
    assert_borderline(page_pdf(rect(60, 590, 500, 30, "0.8 g") + hidden_ops("0.85 g")))


def test_black_text_on_light_grey_fill_kept_without_flags() -> None:
    assert_clean(page_pdf(rect(60, 590, 500, 30, "0.95 g") + hidden_ops("0 g")))


def test_type3_tiny_font_matrix_removed() -> None:
    # Font size 12, FontMatrix 0.00005: a 1000-unit glyph is 0.6 pt high.
    ops = f"BT /F3 12 Tf 72 600 Td {latin_string(HIDDEN)} Tj ET\n"

    assert_removed(type3_page(ops, font_matrix=0.00005, to_unicode=True), "tiny_text")


def test_type3_large_font_matrix_not_tiny() -> None:
    # Font size 0.5, FontMatrix 0.05: a 1000-unit glyph is 25 pt high.
    ops = f"BT /F3 0.5 Tf 72 600 Td {latin_string(HIDDEN)} Tj ET\n"

    result = extract(type3_page(ops, font_matrix=0.05, to_unicode=True))

    assert HIDDEN_KEY in squashed(result)
    assert "tiny_text" not in reasons(result)


# --- Item 6: clips, form BBox, optional content --------------------------------------------------


def test_text_behind_zero_area_clip_kept_borderline() -> None:
    assert_borderline(page_pdf(hidden_ops(prefix="0 0 0 0 re W n")))


def test_text_outside_form_bbox_kept_borderline() -> None:
    assert_borderline(form_page("", bbox="0 0 10 10"))


def ocg_pdf(state: str) -> bytes:
    ocg = EXTRA
    res = resources(properties=f"/OC0 {ocg} 0 R")
    ops = f"/OC /OC0 BDC\n{hidden_ops()}EMC\n"
    catalog = f" /OCProperties << /OCGs [{ocg} 0 R] /D << /{state} [{ocg} 0 R] >> >>"
    page = Page(text(CLAUSE, 72, 720) + ops, resources=res)
    return build_pdf(
        page, extra={ocg: Obj("<< /Type /OCG /Name (Synthetic layer) >>")}, catalog_extra=catalog
    )


def test_optional_content_off_kept_borderline() -> None:
    assert_borderline(ocg_pdf("OFF"))


def test_optional_content_on_kept_without_flags() -> None:
    assert_clean(ocg_pdf("ON"))


# --- Item 3: revisions ---------------------------------------------------------------------------


def test_object_freed_in_newer_section_pdf_damaged() -> None:
    # The update frees the page content; pdfminer would resurrect it from the old section.
    data = incremental_update(text_pdf(CLAUSE), {}, free=[content_obj(0)])

    assert code(data) == "pdf_damaged"


def test_generation_mismatch_pdf_damaged() -> None:
    data = incremental_update(
        text_pdf(CLAUSE), replace_content(0, text(CLAUSE_2)), generations={content_obj(0): 1}
    )

    assert code(data) == "pdf_damaged"


def test_xrefstm_loop_pdf_damaged() -> None:
    assert code(xrefstm_loop(text_pdf(CLAUSE))) == "pdf_damaged"


def test_linearized_file_counts_one_revision() -> None:
    result = extract(linearized_pdf(CLAUSE))

    assert texts(result) == [CLAUSE]
    assert "pdf_edited" not in warning_codes(result)
    assert "damaged_pdf" not in warning_codes(result)


def test_lost_trailer_repaired_damaged_pdf() -> None:
    result = extract(drop_trailer(text_pdf(CLAUSE)))

    assert texts(result) == [CLAUSE]
    assert "damaged_pdf" in warning_codes(result)


# --- Item 4: encryption --------------------------------------------------------------------------


@pytest.mark.parametrize("revision", [2, 3, 4])
def test_user_password_with_empty_owner_password_encrypted_unsupported(revision: int) -> None:
    enc = Encryption(user_password=b"synthetic-secret", owner_password=b"", revision=revision)

    assert code(build_pdf(paragraphs([CLAUSE]), encryption=enc)) == "encrypted_unsupported"


# --- Item 7: caps --------------------------------------------------------------------------------


def corner_fills(count: int) -> str:
    return "q 0 0 0 rg\n" + "0 0 1 1 re f\n" * count + "Q\n"


def test_fills_above_cap_white_text_kept_borderline() -> None:
    # MAX_FILLS is 20 000; more fills leave the colour rules of the page unresolved.
    assert_borderline(page_pdf(corner_fills(20_001) + hidden_ops("1 g")))


def test_fills_at_cap_white_text_removed() -> None:
    assert_removed(page_pdf(corner_fills(20_000) + hidden_ops("1 g")), "same_color")


def test_glyphs_above_cell_cap_overlapping_text() -> None:
    # MAX_CELL_GLYPHS is 256: 300 identical copies are not merged without checks.
    data = build_pdf(text(CLAUSE, 72, 720) * 300)

    assert warnings_of(extract(data), "overlapping_text") == [1]


def test_flow_boxes_above_cap_all_text_kept() -> None:
    # MAX_FLOW_BOXES is 200: 250 separate small boxes on one page.
    words = [f"W{n:03d}" for n in range(250)]
    ops = "".join(
        text(word, 40 + (n % 10) * 56, 760 - (n // 10) * 30, size=8) for n, word in enumerate(words)
    )

    result = extract(build_pdf(ops))

    assert all(word in squashed(result) for word in words)


# --- Item 7: OCR decision after header/footer removal --------------------------------------------

HEADER = "ACME Synthetic Insurance Ltd"


def test_scanned_page_with_running_header_listed_for_ocr() -> None:
    pages = [
        Page(text(HEADER, 72, 770) + text(CLAUSE, 72, 600)),
        Page(full_page_image() + text(HEADER, 72, 770)),
        Page(text(HEADER, 72, 770) + text(CLAUSE_2, 72, 600)),
    ]

    assert extract(build_pdf(pages)).ocr_pages == [2]


def test_scanned_page_with_stamped_page_number_listed_for_ocr() -> None:
    pages = [Page(text(CLAUSE, 72, 600)), Page(full_page_image() + text("2", 300, 20))]

    assert extract(build_pdf(pages)).ocr_pages == [2]


def test_scanned_document_with_page_numbers_all_pages_for_ocr() -> None:
    pages = [Page(full_page_image() + text(str(n), 300, 20)) for n in (1, 2, 3)]

    result = extract(build_pdf(pages))

    assert result.ocr_pages == [1, 2, 3]


# --- Item 7: result model ------------------------------------------------------------------------


def result_model(pages: int | None, blocks: list[Block]) -> ExtractionResult:
    return ExtractionResult(
        kind="pdf",
        bytes=10,
        language="unknown",
        pages=pages,
        blocks=blocks,
        ocr_pages=[],
        removed=[],
        warnings=[],
    )


def test_model_pages_above_100_rejected() -> None:
    with pytest.raises(ValidationError):
        result_model(101, [])


def test_model_pages_at_100_accepted() -> None:
    assert result_model(100, []).pages == 100


def test_model_block_page_above_pages_rejected() -> None:
    with pytest.raises(ValidationError):
        result_model(2, [Block(text="Synthetic.", part="body", page=3)])


def test_model_block_page_at_pages_accepted() -> None:
    assert result_model(2, [Block(text="Synthetic.", part="body", page=2)]).pages == 2


# --- Item 7: references --------------------------------------------------------------------------

UPPER_REFERENCES = [
    "СТРАХУВАННЯ ЗДІЙСНЮЄТЬСЯ ЗГІДНО З ПРАВИЛАМИ СТРАХУВАННЯ № 5.",
    "СТОРОНИ ДІЮТЬ ВІДПОВІДНО ДО ПРАВИЛ НАДАННЯ ПОСЛУГ.",
    "ВЫПЛАТА ПРОИЗВОДИТСЯ СОГЛАСНО ПРАВИЛАМ СТРАХОВАНИЯ.",
    "THE GENERAL TERMS AND CONDITIONS OF THE INSURER APPLY.",
    "ANNEX A IS INCORPORATED BY REFERENCE INTO THIS POLICY.",
    "ДОДАТОК 1 Є НЕВІД'ЄМНОЮ ЧАСТИНОЮ ЦЬОГО ДОГОВОРУ.",
    "ПРИЛОЖЕНИЕ 1 ЯВЛЯЕТСЯ НЕОТЪЕМЛЕМОЙ ЧАСТЬЮ ЭТОГО ДОГОВОРА.",
]
SPLIT_REFERENCES = [
    ("Страхування здійснюється згідно з", "Правилами страхування № 5."),
    ("Сторони діють відповідно до", "Правил надання послуг."),
    ("Выплата производится согласно", "Правилам страхования."),
    ("The General Terms", "and Conditions of the Insurer apply."),
    ("Annex A is incorporated", "by reference into this policy."),
    ("Додаток 1 є невід'ємною", "частиною цього договору."),
    ("Приложение 1 является неотъемлемой", "частью этого договора."),
]
IDS = ["uk-rules", "uk-vidpovidno", "ru-rules", "en-gtc", "en-incorporated", "uk-part", "ru-part"]


def _refs(result: ExtractionResult) -> list[int | None]:
    return warnings_of(result, "external_reference")


@pytest.mark.parametrize("sentence", UPPER_REFERENCES, ids=IDS)
def test_upper_case_reference_external_reference(sentence: str) -> None:
    assert _refs(extract_text_file(sentence.encode())) == [None]


@pytest.mark.parametrize(("first", "second"), SPLIT_REFERENCES, ids=IDS)
def test_text_reference_across_two_blocks_external_reference(first: str, second: str) -> None:
    assert _refs(extract_text_file(f"{first}\n\n{second}\n".encode())) == [None]


@pytest.mark.parametrize(("first", "second"), SPLIT_REFERENCES, ids=IDS)
def test_pdf_reference_across_two_blocks_external_reference(first: str, second: str) -> None:
    result = extract(build_pdf(paragraphs([first, second])))

    assert len(result.blocks) == 2
    assert _refs(result) == [1]


@pytest.mark.parametrize(("first", "second"), SPLIT_REFERENCES, ids=IDS)
def test_pdf_reference_across_lines_of_one_block_external_reference(
    first: str, second: str
) -> None:
    assert _refs(extract(build_pdf(lines([first, second])))) == [1]


def test_pdf_reference_across_page_break_one_warning() -> None:
    first, second = SPLIT_REFERENCES[0]
    pages = [Page(text(CLAUSE, 72, 720) + text(first, 72, 100)), Page(text(second, 72, 720))]

    assert len(_refs(extract(build_pdf(pages)))) == 1


def test_unrelated_adjacent_blocks_no_reference() -> None:
    data = build_pdf(paragraphs(["The Client pays according to", "the invoice of this month."]))

    assert _refs(extract(data)) == []
