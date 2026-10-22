# ruff: noqa: RUF001 - Cyrillic contract samples are the point of these tests
"""S3-T3 PDF extraction: unit tests of ``extract_pdf`` in the test process.

AC2 (encryption), AC3 (page cap), AC5 (provably invisible text), AC6 (borderline),
AC7 (overlap), AC8 (blocks, running headers and footers), AC9 (scans), AC10
(annotations and forms), AC11 (damage and revisions), AC13 (caps, pages,
normalization). AC4 (the device) is covered through AC5-AC7. AC1 (logging) is in
``test_pdf_api.py``. All fixtures are built by ``tests/pdfbuild.py``.

Must fail before the implementation exists (``ModuleNotFoundError`` for
``app.extraction.pdf``), except the builder self-checks in ``test_pdfbuild.py``.
"""

from __future__ import annotations

import unicodedata

import pytest

from tests.pdfbuild import (
    CATALOG,
    PAGE_AREA,
    XFA_PACKET,
    Encryption,
    Page,
    build_pdf,
    free_text_annot,
    full_page_image,
    image,
    incremental_update,
    inline_image,
    last_startxref,
    lines,
    link_annot,
    paragraphs,
    pattern_rect,
    rect,
    replace_content,
    text,
    text_annot,
    text_pdf,
    widget_annot,
)
from tests.pdfrun import (
    code,
    extract,
    joined,
    reasons,
    samples,
    squashed,
    texts,
    warning_codes,
    warnings_of,
)

CLAUSE = "Clause 1. The Insurer pays the insured sum within ten days (synthetic)."
CLAUSE_2 = "Clause 2. The Client pays the premium every month (synthetic)."
CLAUSE_UK = "Страховик сплачує страхову суму протягом десяти днів після заяви."
CLAUSE_RU = "Страховщик выплачивает страховую сумму в течение десяти дней."
HIDDEN = "Hidden clause: the Client waives every claim (synthetic)."
HIDDEN_KEY = "Hiddenclause"


def visible_plus(hidden_ops: str) -> bytes:
    """A one-page PDF: the visible CLAUSE at the top and ``hidden_ops`` further down."""
    return build_pdf(text(CLAUSE, 72, 720) + hidden_ops)


def assert_removed(data: bytes, reason: str) -> None:
    result = extract(data)
    assert texts(result) == [CLAUSE]
    assert reason in reasons(result)
    assert HIDDEN[:30] in samples(result, reason)


def assert_kept(data: bytes) -> None:
    result = extract(data)
    assert HIDDEN_KEY in squashed(result)
    assert not any(item.reason != "page_number" for item in result.removed)


# --- Basic result shape (AC8, AC13) -------------------------------------------------------------


def test_latin_pdf_one_block_per_paragraph() -> None:
    result = extract(build_pdf(paragraphs([CLAUSE, CLAUSE_2])))

    assert result.kind == "pdf"
    assert texts(result) == [CLAUSE, CLAUSE_2]
    assert {(b.part, b.page) for b in result.blocks} == {("body", 1)}


def test_result_bytes_and_pages_match_input() -> None:
    data = text_pdf(CLAUSE, CLAUSE_2, CLAUSE)

    result = extract(data)

    assert (result.bytes, result.pages) == (len(data), 3)


def test_block_page_is_one_based_page_number() -> None:
    result = extract(text_pdf(CLAUSE, CLAUSE_2))

    assert [(b.text, b.page) for b in result.blocks] == [(CLAUSE, 1), (CLAUSE_2, 2)]


def test_lines_of_one_paragraph_form_one_block() -> None:
    rows = ["Clause 3. The Insurer may refuse payment", "only in the cases listed in Annex 1."]

    result = extract(build_pdf(lines(rows, leading=14)))

    assert len(result.blocks) == 1
    assert squashed(result) == "".join("".join(rows).split())


def test_cyrillic_type0_font_extracted_uk() -> None:
    result = extract(build_pdf(paragraphs([CLAUSE_UK, CLAUSE_UK])))

    assert texts(result) == [CLAUSE_UK, CLAUSE_UK]
    assert result.language == "uk"


def test_cyrillic_type0_font_extracted_ru() -> None:
    result = extract(build_pdf(paragraphs([CLAUSE_RU, CLAUSE_RU])))

    assert texts(result) == [CLAUSE_RU, CLAUSE_RU]
    assert result.language == "ru"


@pytest.mark.parametrize("clause", [CLAUSE_UK, CLAUSE_RU, CLAUSE])
def test_clean_contract_has_no_flags(clause: str) -> None:
    result = extract(build_pdf(paragraphs([clause, clause, clause])))

    assert (result.removed, result.warnings, result.ocr_pages) == ([], [], [])


def test_text_is_nfc() -> None:
    result = extract(build_pdf(paragraphs([CLAUSE_UK])))

    assert all(unicodedata.is_normalized("NFC", b.text) for b in result.blocks)


def test_control_character_removed_and_counted() -> None:
    result = extract(build_pdf(text("Сторона\u0007 погоджується з умовами договору.")))

    assert "\u0007" not in joined(result)
    assert squashed(result) == "Сторонапогоджуєтьсязумовамидоговору."
    assert "control_characters" in reasons(result)


# --- AC2: encryption ----------------------------------------------------------------------------


@pytest.mark.parametrize("revision", [2, 3])
def test_encrypted_rc4_empty_user_password_text_read(revision: int) -> None:
    data = build_pdf(paragraphs([CLAUSE]), encryption=Encryption(revision=revision))

    assert texts(extract(data)) == [CLAUSE]


def test_encrypted_aes_empty_user_password_text_read() -> None:
    pytest.importorskip("cryptography")
    data = build_pdf(paragraphs([CLAUSE]), encryption=Encryption(revision=4))

    assert texts(extract(data)) == [CLAUSE]


@pytest.mark.parametrize("revision", [2, 3])
def test_encrypted_rc4_user_password_encrypted_unsupported(revision: int) -> None:
    enc = Encryption(user_password=b"synthetic-secret", revision=revision)

    assert code(build_pdf(paragraphs([CLAUSE]), encryption=enc)) == "encrypted_unsupported"


def test_encrypted_aes_user_password_encrypted_unsupported() -> None:
    pytest.importorskip("cryptography")
    enc = Encryption(user_password=b"synthetic-secret", revision=4)

    assert code(build_pdf(paragraphs([CLAUSE]), encryption=enc)) == "encrypted_unsupported"


# --- AC3: page cap ------------------------------------------------------------------------------


def test_pages_above_default_cap_too_many_pages() -> None:
    data = build_pdf([Page(text(f"Page body {i}.")) for i in range(101)])

    assert code(data) == "too_many_pages"


def test_pages_at_default_cap_accepted() -> None:
    data = build_pdf([Page(text(f"Clause {i}. Synthetic body text.")) for i in range(100)])

    assert extract(data).pages == 100


def test_pages_above_configured_cap_too_many_pages() -> None:
    assert code(text_pdf(CLAUSE, CLAUSE, CLAUSE, CLAUSE), max_pages=3) == "too_many_pages"


# --- AC5: provably invisible text removed --------------------------------------------------------


@pytest.mark.parametrize("mode", [3, 7])
def test_render_mode_invisible_removed(mode: int) -> None:
    assert_removed(visible_plus(text(HIDDEN, 72, 600, render=mode)), "invisible_render_mode")


def test_render_mode_stroke_kept() -> None:
    assert_kept(visible_plus(text(HIDDEN, 72, 600, render=1)))


def test_text_outside_media_and_crop_box_removed() -> None:
    assert_removed(visible_plus(text(HIDDEN, 700, 600)), "outside_page")


def test_text_below_page_removed() -> None:
    assert_removed(visible_plus(text(HIDDEN, 72, -100)), "outside_page")


def test_text_outside_crop_box_inside_media_box_removed() -> None:
    page = Page(text(CLAUSE, 72, 720) + text(HIDDEN, 10, 20), crop_box=(50, 50, 562, 742))

    assert_removed(build_pdf(page), "outside_page")


def test_text_partly_inside_crop_box_kept() -> None:
    page = Page(text(CLAUSE, 72, 720) + text(HIDDEN, 400, 600))  # runs off the right edge

    assert "Hidden" in squashed(extract(build_pdf(page)))


def test_tiny_font_size_removed() -> None:
    assert_removed(visible_plus(text(HIDDEN, 72, 600, size=0.5)), "tiny_text")


def test_tiny_glyph_width_removed() -> None:
    assert_removed(visible_plus(text(HIDDEN, 72, 600, scale=5)), "tiny_text")


@pytest.mark.parametrize("fill", ["1 g", "1 1 1 rg", "0 0 0 0 k"])
def test_exact_white_on_white_page_removed(fill: str) -> None:
    assert_removed(visible_plus(text(HIDDEN, 72, 600, fill=fill)), "same_color")


def test_white_cyrillic_type0_removed() -> None:
    data = build_pdf(text(CLAUSE_UK, 72, 720) + text(CLAUSE_RU, 72, 600, fill="1 g"))

    result = extract(data)

    assert texts(result) == [CLAUSE_UK]
    assert "same_color" in reasons(result)


def test_white_text_over_filled_shape_not_removed() -> None:
    data = visible_plus(rect(60, 590, 480, 30) + text(HIDDEN, 72, 600, fill="1 g"))

    assert_kept(data)


def test_alpha_zero_removed() -> None:
    assert_removed(visible_plus(text(HIDDEN, 72, 600, gs="GS0")), "transparent")


def test_alpha_half_kept() -> None:
    assert_kept(visible_plus(text(HIDDEN, 72, 600, gs="GS1")))


def test_removed_count_counts_characters_and_sample_bounded() -> None:
    rows = [f"{HIDDEN} Synthetic filler line {n} for the sample cap." for n in range(4)]
    hidden = "".join(text(row, 72, 600 - 10 * i, size=6, render=3) for i, row in enumerate(rows))

    result = extract(visible_plus(hidden))

    item = next(i for i in result.removed if i.reason == "invisible_render_mode")
    assert item.count >= len("".join("".join(rows).split()))
    assert 0 < len(item.sample) <= 200


def test_removed_text_counted_per_reason() -> None:
    data = visible_plus(text(HIDDEN, 72, 600, render=3) + text(HIDDEN, 72, 500, fill="1 g"))

    assert {"invisible_render_mode", "same_color"} <= set(reasons(extract(data)))


# --- AC6: borderline kept and flagged ------------------------------------------------------------


@pytest.mark.parametrize("fill", ["0.95 g", "0.95 0.95 0.95 rg"])
def test_near_white_kept_borderline(fill: str) -> None:
    result = extract(visible_plus(text(HIDDEN, 72, 600, fill=fill)))

    assert HIDDEN_KEY in squashed(result)
    assert warnings_of(result, "borderline_text") == [1]


def test_small_text_kept_borderline() -> None:
    small = "ДОДАТКОВА УМОВА ДРІБНИМ ШРИФТОМ"
    result = extract(build_pdf(text(CLAUSE_UK, 72, 720) + text(small, 72, 600, size=3)))

    assert "".join(small.split()) in squashed(result)
    assert warnings_of(result, "borderline_text") == [1]


def test_white_text_over_uncomparable_fill_kept_borderline() -> None:
    data = visible_plus(pattern_rect(60, 590, 480, 30) + text(HIDDEN, 72, 600, fill="1 g"))

    result = extract(data)

    assert HIDDEN_KEY in squashed(result)
    assert warnings_of(result, "borderline_text") == [1]


def test_borderline_warning_has_page_number() -> None:
    data = build_pdf(
        [Page(text(CLAUSE)), Page(text(CLAUSE_2) + text(HIDDEN, 72, 600, fill="0.95 g"))]
    )

    assert warnings_of(extract(data), "borderline_text") == [2]


# --- AC7: overlap -------------------------------------------------------------------------------


def test_fake_bold_identical_glyphs_merged() -> None:
    data = build_pdf(text(CLAUSE, 72, 720) + text(CLAUSE, 72, 720))

    result = extract(data)

    assert texts(result) == [CLAUSE]
    assert "overlapping_text" not in warning_codes(result)


def test_different_overlapping_text_kept_and_flagged() -> None:
    data = build_pdf(text(CLAUSE, 72, 720) + text("XXXXXXXX", 72, 600) + text("OOOOOOOO", 72, 600))

    result = extract(data)

    flat = squashed(result)
    assert (flat.count("X"), flat.count("O")) == (8, 8)
    assert warnings_of(result, "overlapping_text") == [1]


BREVE = chr(0x0306)
DIAERESIS = chr(0x0308)


def test_combining_breve_composed_and_not_flagged() -> None:
    # The last letter of the first word is stored as a base letter plus U+0306.
    decomposed = "Страхови" + chr(0x0438) + BREVE + " договір укладено на один рік."

    result = extract(build_pdf(text(decomposed)))

    assert texts(result) == ["Страхови" + chr(0x0439) + " договір укладено на один рік."]
    assert "overlapping_text" not in warning_codes(result)


def test_combining_diaeresis_composed_ru() -> None:
    # The second letter is stored as a base letter plus U+0308.
    decomposed = "Е" + chr(0x0435) + DIAERESIS + " права определены договором."

    result = extract(build_pdf(text(decomposed)))

    assert texts(result) == ["Е" + chr(0x0451) + " права определены договором."]
    assert result.warnings == []


# --- AC8: running headers, footers and page numbers -----------------------------------------------

HEADER = "SYNTHETIC INSURANCE LLC - POLICY TERMS"


def _with_header(bodies: list[str], header_pages: set[int]) -> bytes:
    pages = []
    for i, body in enumerate(bodies):
        head = text(HEADER, 72, 770) if i in header_pages else ""
        pages.append(Page(head + text(body, 72, 600)))
    return build_pdf(pages)


def test_running_header_kept_once() -> None:
    bodies = [f"Clause {n}. Synthetic body of page {n}." for n in range(1, 5)]

    result = extract(_with_header(bodies, {0, 1, 2, 3}))

    assert joined(result).count(HEADER) == 1
    assert "repeated_header_footer" in reasons(result)


def test_header_on_less_than_half_of_pages_kept_everywhere() -> None:
    bodies = [f"Clause {n}. Synthetic body of page {n}." for n in range(1, 6)]

    result = extract(_with_header(bodies, {0, 3}))

    assert joined(result).count(HEADER) == 2
    assert "repeated_header_footer" not in reasons(result)


def test_running_footer_kept_once() -> None:
    footer = "Synthetic Insurance LLC, policy wording v1"
    pages = [
        Page(text(f"Clause {n}. Body text.", 72, 600) + text(footer, 72, 30)) for n in range(4)
    ]

    result = extract(build_pdf(pages))

    assert joined(result).count(footer) == 1
    assert "repeated_header_footer" in reasons(result)


def test_page_number_lines_dropped() -> None:
    pages = [
        Page(text(f"Clause {n}. Body text.", 72, 600) + text(str(n), 300, 30)) for n in range(1, 4)
    ]

    result = extract(build_pdf(pages))

    assert all(not b.text.strip().isdigit() for b in result.blocks)
    assert len(result.blocks) == 3
    assert "page_number" in reasons(result)


# --- AC9: scans ---------------------------------------------------------------------------------


def test_scanned_only_document_lists_all_pages_for_ocr() -> None:
    result = extract(build_pdf([Page(full_page_image()), Page(full_page_image())]))

    assert (result.pages, result.ocr_pages, result.blocks) == (2, [1, 2], [])


def test_mixed_document_lists_only_scanned_page() -> None:
    data = build_pdf([Page(text(CLAUSE)), Page(full_page_image()), Page(text(CLAUSE_2))])

    result = extract(data)

    assert result.ocr_pages == [2]
    assert texts(result) == [CLAUSE, CLAUSE_2]


def test_inline_image_page_listed_for_ocr() -> None:
    data = build_pdf([Page(text(CLAUSE)), Page(inline_image(0, 0, 612, 792))])

    assert extract(data).ocr_pages == [2]


def test_empty_page_without_image_not_listed_for_ocr() -> None:
    data = build_pdf([Page(text(CLAUSE)), Page(""), Page(text(CLAUSE_2))])

    assert extract(data).ocr_pages == []


def test_no_text_and_no_images_no_text_extracted() -> None:
    assert code(build_pdf([Page(""), Page(rect(10, 10, 50, 50))])) == "no_text_extracted"


def test_little_text_and_large_image_not_read_image_page() -> None:
    page = Page(text("Annex 2.", 72, 760) + image(36, 36, 540, 700))

    result = extract(build_pdf([Page(text(CLAUSE)), page]))

    assert warnings_of(result, "not_read_image_page") == [2]
    assert result.ocr_pages == []


def test_signature_page_small_images_no_warning() -> None:
    # Two stamps of 10 % of the page each (20 % together).
    side = (0.10 * PAGE_AREA) ** 0.5
    page = Page(
        text("Signed: Party A ____  Party B ____", 72, 760)
        + image(40, 100, side, side)
        + image(330, 100, side, side)
    )

    result = extract(build_pdf(page))

    assert "not_read_image_page" not in warning_codes(result)


def test_text_page_with_small_logo_no_warning() -> None:
    body = paragraphs([CLAUSE, CLAUSE_2, CLAUSE, CLAUSE_2, CLAUSE], top=650)

    result = extract(build_pdf(image(500, 740, 60, 30) + body))

    assert "not_read_image_page" not in warning_codes(result)


# --- AC10: annotations and forms ------------------------------------------------------------------


@pytest.mark.parametrize(
    "annot",
    [
        free_text_annot("Synthetic note: the limit is 100 EUR."),
        text_annot("Synthetic sticky note."),
        widget_annot("Synthetic form value"),
    ],
    ids=["freetext", "text", "widget"],
)
def test_annotation_with_value_not_read_annotation(annot: str) -> None:
    data = build_pdf([Page(text(CLAUSE)), Page(text(CLAUSE_2), annots=[annot])], acroform=True)

    assert warnings_of(extract(data), "not_read_annotation") == [2]


def test_widget_without_value_no_warning() -> None:
    data = build_pdf(Page(text(CLAUSE), annots=[widget_annot("")]), acroform=True)

    assert "not_read_annotation" not in warning_codes(extract(data))


def test_link_annotation_ignored() -> None:
    data = build_pdf(Page(text(CLAUSE), annots=[link_annot()]))

    assert extract(data).warnings == []


def test_xfa_form_not_read_xfa() -> None:
    data = build_pdf(Page(text(CLAUSE)), xfa=XFA_PACKET)

    assert "not_read_xfa" in warning_codes(extract(data))


def test_acroform_without_xfa_no_warning() -> None:
    assert extract(build_pdf(Page(text(CLAUSE)), acroform=True)).warnings == []


# --- AC11: damage and revisions -------------------------------------------------------------------


def test_broken_startxref_reconstructed_damaged_pdf() -> None:
    data = build_pdf(paragraphs([CLAUSE]), startxref=99_999_999)

    result = extract(data)

    assert texts(result) == [CLAUSE]
    assert "damaged_pdf" in warning_codes(result)


def test_single_revision_not_edited() -> None:
    assert "pdf_edited" not in warning_codes(extract(text_pdf(CLAUSE)))


def test_incremental_update_latest_revision_read_and_pdf_edited() -> None:
    data = incremental_update(text_pdf(CLAUSE), replace_content(0, text(CLAUSE_2)))

    result = extract(data)

    assert texts(result) == [CLAUSE_2]
    assert "pdf_edited" in warning_codes(result)
    assert "damaged_pdf" not in warning_codes(result)


def _updates(count: int) -> bytes:
    data = text_pdf(CLAUSE)
    for n in range(count):
        data = incremental_update(data, replace_content(0, text(f"Revision {n}. {CLAUSE_2}")))
    return data


def test_short_prev_chain_accepted() -> None:
    result = extract(_updates(5))

    assert texts(result) == [f"Revision 4. {CLAUSE_2}"]
    assert "pdf_edited" in warning_codes(result)


def test_prev_chain_above_default_cap_pdf_damaged() -> None:
    assert code(_updates(40)) == "pdf_damaged"


def test_prev_chain_above_configured_cap_pdf_damaged() -> None:
    assert code(_updates(5), max_prev_chain=3) == "pdf_damaged"


def test_prev_chain_below_configured_cap_accepted() -> None:
    assert extract(_updates(2), max_prev_chain=3).pages == 1


def test_prev_self_loop_pdf_damaged() -> None:
    data = incremental_update(text_pdf(CLAUSE), replace_content(0, text(CLAUSE_2)), self_loop=True)

    assert code(data) == "pdf_damaged"


def test_prev_two_revision_loop_pdf_damaged() -> None:
    base = text_pdf(CLAUSE)
    first = incremental_update(base, replace_content(0, text(CLAUSE_2)))
    # The second update points back at the first update's xref, which points at the base:
    # make the first update's /Prev point at the second update instead (same width).
    second = incremental_update(first, replace_content(0, text(CLAUSE)))
    first_xref = int(first.rsplit(b"startxref\n", 1)[1].split(b"\n", 1)[0])
    second_xref = int(second.rsplit(b"startxref\n", 1)[1].split(b"\n", 1)[0])
    base_xref = int(base.rsplit(b"startxref\n", 1)[1].split(b"\n", 1)[0])
    old = f"/Prev {base_xref} ".encode()
    new = f"/Prev {second_xref} ".encode()
    assert len(old) == len(new), "fixture: offsets must have the same number of digits"
    head, tail = second[:first_xref], second[first_xref:]
    looped = head + tail.replace(old, new, 1)
    assert looped != second

    assert code(looped) == "pdf_damaged"


def test_latest_revision_unreadable_pdf_damaged() -> None:
    # The latest xref section sends the catalog to bytes that are not an object.
    base = text_pdf(CLAUSE)
    junk_at = len(base)
    data = base + b"synthetic garbage that is not an object\n"
    data = incremental_update(data, {}, prev=last_startxref(base), raw_entries={CATALOG: junk_at})

    assert code(data) == "pdf_damaged"


def test_garbage_after_header_pdf_damaged() -> None:
    assert code(b"%PDF-1.7\n" + b"synthetic garbage without objects\n" * 20) == "pdf_damaged"


# --- AC13: caps -----------------------------------------------------------------------------------


def test_text_above_max_chars_too_much_text() -> None:
    assert code(text_pdf(CLAUSE, CLAUSE_2), max_chars=40) == "too_much_text"


def test_blocks_above_max_blocks_too_much_text() -> None:
    assert code(build_pdf(paragraphs([CLAUSE, CLAUSE_2, CLAUSE])), max_blocks=2) == "too_much_text"


def test_list_invariants_on_large_mixed_document() -> None:
    pages = []
    for n in range(1, 101):
        ops = text(f"Clause {n}. Synthetic body text.", 72, 700)
        ops += text(HIDDEN, 72, 600, render=3) + text(HIDDEN, 72, 500, fill="0.95 g")
        pages.append(Page(full_page_image() if n % 10 == 0 else ops))

    result = extract(build_pdf(pages))

    assert result.pages == 100
    assert result.ocr_pages == list(range(10, 101, 10))
    assert len(result.removed) <= 1000
    assert len(result.warnings) <= 1000
    by_code: dict[str, list[int]] = {}
    for warning in result.warnings:
        if warning.page is not None:
            by_code.setdefault(warning.code, []).append(warning.page)
    for pages_of_code in by_code.values():
        assert pages_of_code == sorted(set(pages_of_code))
