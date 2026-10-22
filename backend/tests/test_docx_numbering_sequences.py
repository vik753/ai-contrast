"""S3-T2b (developer tests): sequences shared between ``w:num`` instances."""

from __future__ import annotations

from tests.docxbuild import Package, abstract_num, build_docx, lvl, num, num_pr, numbering_xml, para
from tests.docxrun import extract, joined, texts, warning_codes


def _texts(numbering: bytes, *num_ids: int) -> list[str]:
    body = "".join(para("T", ppr=num_pr(n)) for n in num_ids)
    return texts(extract(build_docx(Package(body=body, numbering=numbering))))


def test_nums_of_one_abstract_continue_one_sequence() -> None:
    numbering = numbering_xml(abstract_num(0, lvl(0, "%1.")), num(1, 0), num(2, 0))

    assert _texts(numbering, 1, 2, 1) == ["1. T", "2. T", "3. T"]


def test_start_override_gives_the_num_its_own_sequence() -> None:
    override = '<w:lvlOverride w:ilvl="0"><w:startOverride w:val="1"/></w:lvlOverride>'
    numbering = numbering_xml(abstract_num(0, lvl(0, "%1.")), num(1, 0), num(2, 0, override))

    assert _texts(numbering, 1, 1, 2, 2, 1) == ["1. T", "2. T", "1. T", "2. T", "3. T"]


def test_own_lvl_override_begins_its_own_sequence() -> None:
    override = f'<w:lvlOverride w:ilvl="0">{lvl(0, "(%1)")}</w:lvlOverride>'
    numbering = numbering_xml(abstract_num(0, lvl(0, "%1.")), num(1, 0), num(2, 0, override))

    assert _texts(numbering, 1, 2, 1) == ["1. T", "(1) T", "2. T"]


def test_counters_are_per_story() -> None:
    numbering = numbering_xml(abstract_num(0, lvl(0, "%1.")), num(1, 0))
    data = build_docx(
        Package(
            body=para("Body", ppr=num_pr(1)),
            footnotes=[para("Note", ppr=num_pr(1))],
            numbering=numbering,
        )
    )

    assert "1. Note" in joined(extract(data))


def test_roman_above_3999_is_decimal_with_warning() -> None:
    numbering = numbering_xml(abstract_num(0, lvl(0, "%1.", "upperRoman", start=4000)), num(1, 0))
    result = extract(build_docx(Package(body=para("T", ppr=num_pr(1)), numbering=numbering)))

    assert texts(result) == ["4000. T"]
    assert "numbering_approximate" in warning_codes(result)


def test_bad_ilvl_uses_level_zero_with_warning() -> None:
    numbering = numbering_xml(abstract_num(0, lvl(0, "%1.")), num(1, 0))
    body = para("T", ppr=num_pr(1, 9))
    result = extract(build_docx(Package(body=body, numbering=numbering)))

    assert texts(result) == ["1. T"]
    assert "numbering_approximate" in warning_codes(result)


def test_unresolvable_num_style_link_is_decimal_with_warning() -> None:
    link = '<w:abstractNum w:abstractNumId="0"><w:numStyleLink w:val="Nope"/></w:abstractNum>'
    numbering = numbering_xml(link, num(1, 0))
    result = extract(build_docx(Package(body=para("T", ppr=num_pr(1)), numbering=numbering)))

    assert texts(result) == ["1. T"]
    assert "numbering_approximate" in warning_codes(result)


def test_moved_away_paragraph_mark_does_not_count() -> None:
    numbering = numbering_xml(abstract_num(0, lvl(0, "%1.")), num(1, 0))
    moved = (
        '<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'
        '<w:rPr><w:moveFrom w:id="1" w:author="A"/></w:rPr></w:pPr>'
        '<w:moveFrom w:id="2" w:author="A"><w:r><w:t>Moved</w:t></w:r></w:moveFrom></w:p>'
    )
    body = para("One", ppr=num_pr(1)) + moved + para("Two", ppr=num_pr(1))
    result = extract(build_docx(Package(body=body, numbering=numbering)))

    assert texts(result)[-1] == "2. Two"
