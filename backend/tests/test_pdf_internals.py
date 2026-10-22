"""Unit tests of the PDF internals added in review round 1 (colour spaces, optional
content, tiling patterns, reference joins, free-entry checks). Synthetic data only."""

from __future__ import annotations

import pytest
from pdfminer.psparser import LIT

from app.extraction.model import Block
from app.extraction.pdf_colour import is_white, luminance, parse_colour_space
from app.extraction.pdf_content import tiling_runs_text
from app.extraction.pdf_document import CheckedDocument, PdfDamagedError, _TrackedXRef
from app.extraction.references import external_reference_warnings, straddles
from tests.pdfbuild import EXTRA, Page, build_pdf, text, type3_objects
from tests.pdfrun import extract, reasons, squashed, warnings_of

SPOT_FN = {"FunctionType": 2, "Domain": [0, 1], "C0": [0, 0, 0, 0], "C1": [0, 0, 0, 1], "N": 1}


def lit(name: str) -> object:
    return LIT(name)


def test_lab_with_chroma_is_never_exact_white() -> None:
    space = parse_colour_space([lit("Lab"), {}])
    assert space is not None

    white = space.resolve((100, 0, 0))
    tinted = space.resolve((100, 5, 0))

    assert white is not None
    assert is_white(white)
    assert tinted is not None
    assert not is_white(tinted)


def test_indexed_lookup_and_out_of_range_index() -> None:
    space = parse_colour_space([lit("Indexed"), lit("DeviceRGB"), 1, b"\x00\x00\x00\xff\xff\xff"])
    assert space is not None

    assert space.resolve((1,)) == ("DeviceRGB", (1.0, 1.0, 1.0))
    assert space.resolve((7,)) == ("DeviceRGB", (1.0, 1.0, 1.0))  # clamped to hival
    assert space.resolve((0,)) == ("DeviceRGB", (0.0, 0.0, 0.0))


def test_indexed_short_lookup_is_unresolved() -> None:
    space = parse_colour_space([lit("Indexed"), lit("DeviceRGB"), 1, b"\x00\x00\x00"])
    assert space is not None

    assert space.resolve((1,)) is None


def test_separation_zero_tint_is_white_and_full_tint_is_not() -> None:
    space = parse_colour_space([lit("Separation"), lit("Spot"), lit("DeviceCMYK"), SPOT_FN])
    assert space is not None

    zero, full = space.resolve((0,)), space.resolve((1,))

    assert zero is not None
    assert is_white(zero)
    assert full == ("DeviceCMYK", (0.0, 0.0, 0.0, 1.0))
    assert luminance(full) == 0.0


def test_separation_none_colorant_is_unresolved() -> None:
    space = parse_colour_space([lit("Separation"), lit("None"), lit("DeviceGray"), SPOT_FN])
    assert space is not None

    assert space.resolve((1,)) is None


def test_devicen_tint_functions_not_evaluated_beyond_zero() -> None:
    space = parse_colour_space(
        [lit("DeviceN"), [lit("A"), lit("B")], lit("DeviceCMYK"), {"FunctionType": 4}]
    )
    assert space is not None

    assert space.resolve((0, 0)) == ("DeviceGray", (1.0,))
    assert space.resolve((0, 1)) is None


@pytest.mark.parametrize("spec", [[lit("ICCBased")], [lit("Unknown")], [], 5, [lit("Indexed")]])
def test_malformed_colour_space_is_unknown(spec: object) -> None:
    assert parse_colour_space(spec) is None


def test_non_finite_component_is_unresolved() -> None:
    space = parse_colour_space(lit("DeviceGray"))
    assert space is not None

    assert space.resolve((float("nan"),)) is None


def test_tiling_pattern_detection_needs_text_or_form() -> None:
    assert tiling_runs_text(None) is False


def test_straddle_needs_the_phrase_to_cross_the_boundary() -> None:
    assert straddles("The General Terms", "and Conditions apply.")
    assert not straddles("Clean text.", "The General Terms and Conditions apply.")
    assert not straddles("The General Terms and Conditions apply.", "Clean text.")


def test_reference_join_uses_only_adjacent_blocks() -> None:
    blocks = [
        Block(text="Payment is made", part="body", page=1),
        Block(text="Unrelated block.", part="body", page=1),
        Block(text="according to the General Terms and", part="body", page=1),
        Block(text="Conditions of the Insurer.", part="body", page=2),
    ]

    warnings = external_reference_warnings(blocks, per_page=True)

    assert [w.page for w in warnings] == [1]


def test_type3_matrix_scales_the_size() -> None:
    # FontMatrix 0.0001 and font size 6: a 1000-unit glyph is 0.6 pt high.
    ops = f"BT /F3 6 Tf 72 600 Td {'(Tiny type three words)'} Tj ET\n"
    res = "<< /Font << /F1 3 0 R /F3 5000 0 R >> /ProcSet [/PDF /Text] >>"
    data = build_pdf(
        Page(text("Visible clause here.", 72, 720) + ops, resources=res),
        extra=type3_objects(EXTRA, font_matrix=0.0001, to_unicode=True),
    )

    result = extract(data)

    assert "Visibleclausehere." in squashed(result)
    assert "Tinytype" not in squashed(result)
    assert reasons(result).get("tiny_text")


def test_type3_without_to_unicode_warns_on_every_page_that_shows_it() -> None:
    res = "<< /Font << /F1 3 0 R /F3 5000 0 R >> /ProcSet [/PDF /Text] >>"
    ops = "BT /F3 12 Tf 72 600 Td (Abc def) Tj ET\n"
    pages = [
        Page(ops, resources=res),
        Page(text("Plain page."), resources=None),
        Page(ops, resources=res),
    ]

    result = extract(build_pdf(pages, extra=type3_objects(EXTRA)))

    assert warnings_of(result, "not_read_type3") == [1, 3]


def _table(used: dict[int, int], free: set[int]) -> _TrackedXRef:
    xref = _TrackedXRef()
    xref.offsets = {n: (None, 10 * n, g) for n, g in used.items()}
    xref.free = set(free)
    return xref


def test_hybrid_revision_may_free_what_its_stream_lists() -> None:
    freed: set[int] = set()
    gens: dict[int, int] = {}

    CheckedDocument._check_revision([_table({}, {7}), _table({7: 0}, set())], freed, gens)

    assert freed == set()


def test_older_revision_listing_a_freed_object_is_damaged() -> None:
    freed: set[int] = set()
    gens: dict[int, int] = {}
    CheckedDocument._check_revision([_table({}, {7})], freed, gens)

    with pytest.raises(PdfDamagedError):
        CheckedDocument._check_revision([_table({7: 0}, set())], freed, gens)


def test_generation_change_between_revisions_is_damaged() -> None:
    freed: set[int] = set()
    gens: dict[int, int] = {}
    CheckedDocument._check_revision([_table({7: 1}, set())], freed, gens)

    with pytest.raises(PdfDamagedError):
        CheckedDocument._check_revision([_table({7: 0}, set())], freed, gens)


def test_object_zero_is_ignored() -> None:
    freed: set[int] = set()
    gens: dict[int, int] = {}
    CheckedDocument._check_revision([_table({}, {0})], freed, gens)

    CheckedDocument._check_revision([_table({0: 0}, set())], freed, gens)
