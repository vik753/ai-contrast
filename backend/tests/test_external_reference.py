# ruff: noqa: RUF001 - Cyrillic contract samples are the point of these tests
"""S3-T3 AC12: references to documents that were not provided, for every kind
(shared post-processing). Warning ``external_reference`` with the page for PDF and
``null`` for text and DOCX.

The text and DOCX tests fail before the implementation with an assertion (no
warning); the PDF tests fail with ``ModuleNotFoundError``.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.extraction.model import ExtractionResult
from app.extraction.text import extract_text_file
from tests.docxbuild import body_docx, para
from tests.docxrun import extract as extract_docx
from tests.pdfbuild import Page, build_pdf, paragraphs, text
from tests.pdfrun import extract as extract_pdf

REFERENCES = [
    "Страхування здійснюється згідно з Правилами страхування № 5 цього страховика.",
    "Сторони діють відповідно до Правил надання послуг цього банку.",
    "Выплата производится согласно Правилам страхования этой компании.",
    "The General Terms and Conditions of the Insurer apply to this policy.",
    "Annex A of the Insurer is incorporated by reference into this policy.",
    "Додаток 1 є невід'ємною частиною цього договору страхування.",
    "Приложение 1 является неотъемлемой частью этого договора страхования.",
]
IDS = ["uk-rules", "uk-vidpovidno", "ru-rules", "en-gtc", "en-incorporated", "uk-part", "ru-part"]
CLEAN = [
    "Clause 4. The Client pays the premium within thirty days of the invoice.",
    "Страховик сплачує страхову суму протягом десяти днів після заяви.",
    "Страховщик выплачивает страховую сумму в течение десяти дней.",
]


def _refs(result: ExtractionResult) -> list[int | None]:
    return [w.page for w in result.warnings if w.code == "external_reference"]


@pytest.mark.parametrize("sentence", REFERENCES, ids=IDS)
def test_text_reference_external_reference(sentence: str) -> None:
    result = extract_text_file(f"{CLEAN[0]}\n\n{sentence}\n".encode())

    assert _refs(result) == [None]


@pytest.mark.parametrize("sentence", CLEAN)
def test_text_without_reference_no_warning(sentence: str) -> None:
    assert _refs(extract_text_file(sentence.encode())) == []


def test_text_typographic_apostrophe_external_reference() -> None:
    sentence = "Додаток 1 є невід’ємною частиною цього договору."

    assert _refs(extract_text_file(sentence.encode())) == [None]


def test_text_reference_text_unchanged() -> None:
    result = extract_text_file(REFERENCES[0].encode())

    assert [b.text for b in result.blocks] == [REFERENCES[0]]


@pytest.mark.parametrize("sentence", REFERENCES, ids=IDS)
def test_docx_reference_external_reference(sentence: str) -> None:
    result = extract_docx(body_docx(para(CLEAN[1]), para(sentence)))

    assert _refs(result) == [None]


def test_docx_without_reference_no_warning() -> None:
    assert _refs(extract_docx(body_docx(para(CLEAN[1]), para(CLEAN[2])))) == []


@pytest.mark.parametrize("sentence", REFERENCES, ids=IDS)
def test_pdf_reference_external_reference_with_page(sentence: str) -> None:
    data = build_pdf([Page(text(CLEAN[0])), Page(paragraphs([CLEAN[0], sentence]))])

    assert _refs(extract_pdf(data)) == [2]


def test_pdf_references_one_warning_per_page() -> None:
    data = build_pdf(
        [
            Page(paragraphs([REFERENCES[0], REFERENCES[3]])),
            Page(text(CLEAN[0])),
            Page(text(REFERENCES[6])),
        ]
    )

    assert _refs(extract_pdf(data)) == [1, 3]


def test_api_text_reference_external_reference(make_client: Callable[..., TestClient]) -> None:
    body = make_client().post(
        "/api/extract",
        content=REFERENCES[3].encode(),
        headers={"Content-Type": "application/octet-stream"},
    )

    assert body.status_code == 200
    assert body.json()["warnings"] == [{"code": "external_reference", "page": None}]
