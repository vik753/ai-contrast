"""S3-T2b (developer tests): sequences shared between ``w:num`` instances."""

from __future__ import annotations

from tests.docxbuild import Package, abstract_num, build_docx, lvl, num, num_pr, numbering_xml, para
from tests.docxrun import extract, texts


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
