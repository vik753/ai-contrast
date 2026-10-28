# ruff: noqa: RUF001
"""S5-T1b (AC 1, 6): the same Layer 1 cleaning on every input path.

``POST /api/extract`` (text upload, DOCX, PDF) and ``POST /api/segment`` must give
the same cleaned text for the same input, and report what they removed.
Public interface only: HTTP endpoints plus the test builders in ``tests/``.

Expected to fail before the implementation exists (the text and PDF paths keep
format characters today; the segment path reports different reasons).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests import pdfbuild
from tests.docxbuild import body_docx, para
from tests.segment_helpers import block, post_blocks

EXTRACT = "/api/extract"
OCTET = {"Content-Type": "application/octet-stream"}
REASONS = {
    "default_ignorable",
    "format_character",
    "private_use",
    "unassigned",
    "surrogate",
    "control_character",
}

PAD = "Synthetic clause text that is plain and harmless. " * 4
DIRTY = (
    PAD + "1. Pay\u200bment\u202e is\u2800 due\U000e0041\ufe0f in 30\u00ad days \uf0fe done\x07."
)
CLEAN = PAD + "1. Payment is due in 30 days ☑ done."
REMOVED_IN_DIRTY = 7  # 200B, 202E, 2800, E0041, FE0F, 00AD, 0007

Client = Callable[..., TestClient]


def _removed_total(data: dict[str, Any]) -> int:
    return int(sum(item["count"] for item in data["removed"]))


def _check_report(data: dict[str, Any]) -> None:
    for item in data["removed"]:
        assert item["reason"] in REASONS
        assert item["count"] >= 1
        assert len(item["sample"]) <= 200
        assert all(unicodedata.category(ch)[0] != "C" for ch in item["sample"])


def _extract(client: TestClient, body: bytes) -> dict[str, Any]:
    response = client.post(EXTRACT, content=body, headers=OCTET)
    assert response.status_code == 200, response.text[:200]
    data: dict[str, Any] = response.json()
    return data


def _joined(data: dict[str, Any]) -> str:
    return "\n".join(b["text"] for b in data["blocks"])


def test_text_upload_is_cleaned_and_reported(make_client: Client) -> None:
    data = _extract(make_client(), DIRTY.encode("utf-8"))

    assert _joined(data) == CLEAN
    assert _removed_total(data) == REMOVED_IN_DIRTY
    _check_report(data)


def test_segment_cleans_the_same_text_and_reports_the_same_count(make_client: Client) -> None:
    response = post_blocks(make_client(), [block(DIRTY)])

    assert response.status_code == 200, response.text[:200]
    data = response.json()
    assert [b["text"] for b in data["blocks"]] == [CLEAN]
    assert _removed_total(data) == REMOVED_IN_DIRTY
    _check_report(data)


def test_extract_text_upload_and_segment_give_identical_blocks(make_client: Client) -> None:
    client = make_client()
    paragraphs = [DIRTY, PAD + "2. Рах\u200bуноќ сплачується\u2060 щомісяця.", "e\u200b́ end"]
    uploaded = _extract(client, "\n\n".join(paragraphs).encode("utf-8"))
    segmented = post_blocks(client, [block(p) for p in paragraphs]).json()

    assert [b["text"] for b in uploaded["blocks"]] == [b["text"] for b in segmented["blocks"]]
    assert _removed_total(uploaded) == _removed_total(segmented)
    assert {(r["reason"], r["count"], r["sample"]) for r in uploaded["removed"]} == {
        (r["reason"], r["count"], r["sample"]) for r in segmented["removed"]
    }


def test_segment_is_idempotent_on_its_own_output(make_client: Client) -> None:
    client = make_client()
    first = post_blocks(client, [block(DIRTY)]).json()
    second = post_blocks(client, [block(b["text"]) for b in first["blocks"]]).json()

    assert [b["text"] for b in second["blocks"]] == [b["text"] for b in first["blocks"]]
    assert second["removed"] == []


def test_segment_checkbox_glyphs_are_mapped_like_in_text_upload(make_client: Client) -> None:
    text = "\uf0a8 not covered \uf0fd excluded \uf078 excluded too \uf06f open"
    expected = "☐ not covered ☒ excluded ☒ excluded too ☐ open"
    client = make_client()

    assert _joined(_extract(client, text.encode())) == expected
    assert post_blocks(client, [block(text)]).json()["blocks"][0]["text"] == expected


# --- DOCX -------------------------------------------------------------------------------------


def test_docx_with_invisible_characters_is_cleaned_and_reported(make_client: Client) -> None:
    docx = body_docx(para(DIRTY.replace("\x07", "")))

    data = _extract(make_client(), docx)

    assert "Payment is due in 30 days" in _joined(data).replace("\n", " ")
    for char in "\u200b\u202e\u2800\U000e0041\ufe0f\u00ad":
        assert char not in _joined(data)
    assert _removed_total(data) >= REMOVED_IN_DIRTY - 1
    _check_report(data)


def test_docx_text_equals_segment_cleaning_of_the_raw_text(make_client: Client) -> None:
    raw = "Pay\u200bment\u202e due\U000e0041 \u2800now\u180e."
    client = make_client()
    from_docx = _joined(_extract(client, body_docx(para(raw)))).strip()
    from_segment = post_blocks(client, [block(raw)]).json()["blocks"][0]["text"]

    assert from_docx == from_segment == "Payment due now."


# --- PDF --------------------------------------------------------------------------------------

PDF_INVISIBLE = "\u200b\u202e\u2800\u2060\ufeff\u3164"


@pytest.fixture
def pdf_with_invisible_chars(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], bytes]:
    """The PDF builder's /F2 font shows these extra characters (ToUnicode maps them)."""
    monkeypatch.setattr(pdfbuild, "CYR_CHARS", pdfbuild.CYR_CHARS + PDF_INVISIBLE)

    def build(text: str) -> bytes:
        return pdfbuild.build_pdf(pdfbuild.text(text, cyr=True))

    return build


def test_pdf_with_invisible_characters_is_cleaned_and_reported(
    make_client: Client, pdf_with_invisible_chars: Callable[[str], bytes]
) -> None:
    pdf = pdf_with_invisible_chars("Pay\u200bment\u202e is\u2800 due\u2060 now\ufeff\u3164 ok.")

    data = _extract(make_client(), pdf)

    text = _joined(data)
    for char in PDF_INVISIBLE:
        assert char not in text
    assert "Payment" in text.replace(" ", "")
    assert _removed_total(data) >= 6
    _check_report(data)


def test_pdf_checkbox_glyph_is_mapped_not_removed(
    make_client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pdfbuild, "CYR_CHARS", pdfbuild.CYR_CHARS + "\uf0fe")
    pdf = pdfbuild.build_pdf(pdfbuild.text("\uf0fe covered", cyr=True))

    data = _extract(make_client(), pdf)

    assert "☑" in _joined(data)
    assert "\uf0fe" not in _joined(data)
    assert not any(r["reason"] == "private_use" for r in data["removed"])
