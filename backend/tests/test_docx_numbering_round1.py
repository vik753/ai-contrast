"""S3-T2b review round 1, items 1-4 (visibility of labels, counting by paragraph mark,
level from a style link, caps). Assumed: cap breaches raise ``suspicious_package``.
Must fail before the fix."""

from __future__ import annotations

import pytest

from app.extraction.model import ExtractionError
from tests.docxbuild import abstract_num, lvl, num, num_pr, numbering_xml, p, para, r, styles_xml
from tests.docxrun import joined, texts
from tests.test_docx_numbering import _numbered_style, _run

INJECTED = "SYNTHETIC-INJECTED-LABEL"
VANISH = "<w:vanish/>"


def _hidden_label_numbering(rpr: str = "") -> bytes:
    return numbering_xml(abstract_num(0, lvl(0, INJECTED + " %1.", rpr=rpr)), num(1, 0))


def _removed_text(result: object) -> str:
    return " ".join(item.sample for item in result.removed)  # type: ignore[attr-defined]


# --- 1. Label visibility ----------------------


def test_hidden_level_label_is_not_emitted_and_is_reported() -> None:
    result = _run(_hidden_label_numbering(VANISH), para("Item", ppr=num_pr(1)))

    assert texts(result) == ["Item"]
    assert INJECTED in _removed_text(result)


def test_hidden_paragraph_mark_hides_the_label() -> None:
    numbering = _hidden_label_numbering()
    result = _run(numbering, para("Item", ppr=num_pr(1) + f"<w:rPr>{VANISH}</w:rPr>"))

    assert INJECTED not in joined(result)


def test_hidden_paragraph_style_hides_the_label() -> None:
    style = _numbered_style("Clause", 1).replace("</w:style>", f"<w:rPr>{VANISH}</w:rPr></w:style>")
    visible_run = r("Item", '<w:vanish w:val="0"/>')
    result = _run(
        _hidden_label_numbering(),
        p(visible_run, ppr='<w:pStyle w:val="Clause"/>'),
        styles=styles_xml(style),
    )

    assert INJECTED not in joined(result)


# --- 2. Counting follows the paragraph mark ----------------------


def _count_numbering() -> bytes:
    return numbering_xml(abstract_num(0, lvl(0, "%1.")), num(1, 0))


def test_hidden_run_with_visible_mark_still_counts() -> None:
    hidden_runs = p(r("Gone", VANISH), ppr=num_pr(1))
    result = _run(
        _count_numbering(), para("One", ppr=num_pr(1)), hidden_runs, para("Three", ppr=num_pr(1))
    )

    assert "Gone" not in joined(result)
    assert texts(result)[-1] == "3. Three"


def test_hidden_paragraph_mark_does_not_count() -> None:
    marked = p(r("Gone"), ppr=num_pr(1) + f"<w:rPr>{VANISH}</w:rPr>")
    result = _run(
        _count_numbering(), para("One", ppr=num_pr(1)), marked, para("Two", ppr=num_pr(1))
    )

    assert texts(result)[-1] == "2. Two"


def test_deleted_paragraph_mark_does_not_count() -> None:
    marked = p(r("Gone"), ppr=num_pr(1) + '<w:rPr><w:del w:id="1" w:author="A"/></w:rPr>')
    result = _run(
        _count_numbering(), para("One", ppr=num_pr(1)), marked, para("Two", ppr=num_pr(1))
    )

    assert texts(result)[-1] == "2. Two"


# --- 3. Level from the style link ----------------------


def test_style_without_ilvl_takes_the_level_linked_by_lvl_pstyle() -> None:
    numbering = numbering_xml(
        abstract_num(0, lvl(0, "%1.", pstyle="Heading1"), lvl(1, "%1.%2.", pstyle="Heading2")),
        num(1, 0),
    )
    styles = styles_xml(_numbered_style("Heading1", 1), _numbered_style("Heading2", 1))
    result = _run(
        numbering,
        para("Top", ppr='<w:pStyle w:val="Heading1"/>'),
        para("Sub", ppr='<w:pStyle w:val="Heading2"/>'),
        styles=styles,
    )

    assert texts(result) == ["1. Top", "1.1. Sub"]


# --- 4. Caps ----------------------


def _fails(numbering: bytes) -> str:
    with pytest.raises(ExtractionError) as info:
        _run(numbering, para("Item", ppr=num_pr(1)))
    return info.value.code


def test_lvl_text_of_256_characters_fails_closed() -> None:
    assert _fails(numbering_xml(abstract_num(0, lvl(0, "x" * 256)), num(1, 0))) == (
        "suspicious_package"
    )


def test_lvl_text_of_255_characters_is_accepted() -> None:
    numbering = numbering_xml(abstract_num(0, lvl(0, "x" * 255)), num(1, 0))

    assert texts(_run(numbering, para("Item", ppr=num_pr(1))))[0].startswith("x" * 255)


def test_expanded_label_above_256_characters_fails_closed() -> None:
    # lvlText is 200 characters; the expansion is 600.
    levels = [lvl(0, "%1" * 100, start=999_999)]
    assert _fails(numbering_xml(abstract_num(0, *levels), num(1, 0))) == "suspicious_package"


def test_duplicate_abstract_num_id_fails_closed() -> None:
    numbering = numbering_xml(
        abstract_num(0, lvl(0, "%1.")), abstract_num(0, lvl(0, "(%1)")), num(1, 0)
    )

    assert _fails(numbering) == "suspicious_package"


def test_duplicate_num_id_fails_closed() -> None:
    numbering = numbering_xml(abstract_num(0, lvl(0, "%1.")), num(1, 0), num(1, 0))

    assert _fails(numbering) == "suspicious_package"
