"""S3-T3 through ``POST /api/extract``: the full path (detection, sandbox child,
``extract_pdf``, contract validation in the parent). AC1 (logging), AC2, AC3, AC9,
AC11, AC14 (worst case at the caps) and the settings ``MAX_PDF_PAGES`` /
``MAX_PDF_PREV_CHAIN``. Must fail before the implementation exists (today PDF
returns ``501 not_implemented``).

Assumed beyond the public interface (see the test report): PDF extraction errors
are ``422 {"error": <code>}``; the settings fields are ``max_pdf_pages`` and
``max_pdf_prev_chain``; the ``pdfminer`` logger level is set by ``app.extraction.pdf``
(on import or in ``extract_pdf``), so it also holds in the test process.
"""

from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.settings import Settings
from tests.helpers import all_log_text, new_canary
from tests.pdfbuild import (
    Encryption,
    Page,
    build_pdf,
    full_page_image,
    incremental_update,
    paragraphs,
    replace_content,
    text,
    text_pdf,
)
from tests.pdfrun import extract

EXTRACT = "/api/extract"
OCTET = {"Content-Type": "application/octet-stream"}
CONTRACT_KEYS = {"kind", "bytes", "language", "pages", "blocks", "ocr_pages", "removed", "warnings"}
CLAUSE = "Clause 1. The Insurer pays the insured sum within ten days of the claim."
CLAUSE_2 = "Clause 2. The Client pays the premium every month by bank transfer."
HIDDEN = "Hidden clause: the Client waives every claim (synthetic)."


def _post(client: TestClient, body: bytes) -> Any:
    return client.post(EXTRACT, content=body, headers=OCTET)


def _looped() -> bytes:
    return incremental_update(text_pdf(CLAUSE), replace_content(0, text(CLAUSE_2)), self_loop=True)


# --- Settings -----------------------------------------------------------------------------------


def test_settings_pdf_defaults() -> None:
    settings = Settings()

    assert (settings.max_pdf_pages, settings.max_pdf_prev_chain) == (100, 32)


def test_settings_pdf_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_PDF_PAGES", "7")
    monkeypatch.setenv("MAX_PDF_PREV_CHAIN", "4")

    settings = Settings()

    assert (settings.max_pdf_pages, settings.max_pdf_prev_chain) == (7, 4)


# --- API ----------------------------------------------------------------------------------------


def test_api_valid_pdf_200_with_blocks(make_client: Callable[..., TestClient]) -> None:
    data = build_pdf([Page(paragraphs([CLAUSE, CLAUSE_2])), Page(paragraphs([CLAUSE]))])

    response = _post(make_client(), data)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == CONTRACT_KEYS
    assert (body["kind"], body["bytes"], body["language"], body["pages"]) == (
        "pdf",
        len(data),
        "en",
        2,
    )
    assert body["blocks"] == [
        {"text": CLAUSE, "part": "body", "page": 1},
        {"text": CLAUSE_2, "part": "body", "page": 1},
        {"text": CLAUSE, "part": "body", "page": 2},
    ]
    assert (body["ocr_pages"], body["removed"], body["warnings"]) == ([], [], [])


def test_api_encrypted_with_user_password_422(make_client: Callable[..., TestClient]) -> None:
    data = build_pdf(text(CLAUSE), encryption=Encryption(user_password=b"synthetic-secret"))

    response = _post(make_client(), data)

    assert response.status_code == 422
    assert response.json() == {"error": "encrypted_unsupported"}


def test_api_prev_loop_422_pdf_damaged(make_client: Callable[..., TestClient]) -> None:
    response = _post(make_client(), _looped())

    assert response.status_code == 422
    assert response.json() == {"error": "pdf_damaged"}


def test_api_scanned_only_200_all_pages_for_ocr(make_client: Callable[..., TestClient]) -> None:
    data = build_pdf([Page(full_page_image()), Page(full_page_image())])

    response = _post(make_client(), data)

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["pages"], body["ocr_pages"], body["blocks"]) == (2, [1, 2], [])


def test_api_invisible_text_removed_and_reported(make_client: Callable[..., TestClient]) -> None:
    data = build_pdf(text(CLAUSE, 72, 720) + text(HIDDEN, 72, 600, render=3))

    body = _post(make_client(), data).json()

    assert [b["text"] for b in body["blocks"]] == [CLAUSE]
    assert [x["reason"] for x in body["removed"]] == ["invisible_render_mode"]
    assert HIDDEN[:30] in body["removed"][0]["sample"]


def test_api_pages_above_setting_422(make_client: Callable[..., TestClient]) -> None:
    response = _post(make_client(max_pdf_pages=2), text_pdf(CLAUSE, CLAUSE, CLAUSE))

    assert response.status_code == 422
    assert response.json() == {"error": "too_many_pages"}


def test_api_prev_chain_above_setting_422(make_client: Callable[..., TestClient]) -> None:
    data = text_pdf(CLAUSE)
    for n in range(4):
        data = incremental_update(data, replace_content(0, text(f"Revision {n}.")))

    response = _post(make_client(max_pdf_prev_chain=2), data)

    assert response.json() == {"error": "pdf_damaged"}


def test_api_pdf_slot_released(
    make_app: Callable[..., Any], make_client: Callable[..., TestClient]
) -> None:
    app = make_app(max_concurrent_extractions=1)

    _post(make_client(app), text_pdf(CLAUSE))

    limiter = app.state.extraction_limiter
    assert limiter.try_acquire()
    limiter.release()


# --- AC1: logs never contain PDF content ----------------------------------------------------------


def test_api_pdf_canary_absent_from_logs(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    canary = new_canary()
    data = build_pdf(text(f"Party {canary}.", 72, 720) + text(canary, 72, 600, render=3))
    client = make_client()
    log_capture.clear()

    response = _post(client, data)

    assert response.status_code == 200
    assert canary not in all_log_text(log_capture)


def test_api_damaged_pdf_canary_absent_from_logs_and_response(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    canary = new_canary()
    data = build_pdf(text(CLAUSE), startxref=99_999_999)
    data = data.replace(b"trailer", f"{canary} trailer".encode(), 1) + canary.encode()
    client = make_client()
    log_capture.clear()

    response = _post(client, data)

    assert canary not in all_log_text(log_capture)
    assert canary not in response.text


def test_in_process_pdfminer_messages_not_logged(log_capture: pytest.LogCaptureFixture) -> None:
    # pdfminer warns about a damaged xref and quotes the bytes it saw.
    canary = new_canary()
    data = build_pdf(text(CLAUSE), startxref=99_999_999)
    data = data.replace(b"trailer", f"{canary} trailer".encode(), 1)
    log_capture.clear()

    extract(data)

    assert canary not in all_log_text(log_capture)
    assert logging.getLogger("pdfminer").getEffectiveLevel() >= logging.ERROR


# --- AC14: worst case at the caps -----------------------------------------------------------------

WORST_PAGES = 100
WORST_LINES = 60
WORST_LINE_CHARS = 90


def _noise_line(seed: bytes) -> str:
    out = ""
    while len(out) < WORST_LINE_CHARS:
        seed = hashlib.sha256(seed).digest()
        out += " ".join(seed.hex()[i : i + 8] for i in range(0, 64, 8)) + " "
    return out[:WORST_LINE_CHARS].strip()


def worst_case_pdf() -> bytes:
    pages = []
    for page in range(WORST_PAGES):
        rows = [
            text(_noise_line(f"{page}-{row}".encode()), 40, 770 - 12 * row, size=8)
            for row in range(WORST_LINES)
        ]
        pages.append(Page("".join(rows)))
    return build_pdf(pages)


@pytest.fixture(scope="module")
def worst_case() -> bytes:
    return worst_case_pdf()


def test_fixture_worst_case_within_upload_limit(worst_case: bytes) -> None:
    assert len(worst_case) < 10 * 1024 * 1024


def test_api_pdf_worst_case_at_caps_within_child_limits(
    make_client: Callable[..., TestClient], worst_case: bytes
) -> None:
    client = make_client()

    started = time.monotonic()
    response = _post(client, worst_case)
    elapsed = time.monotonic() - started

    assert response.status_code == 200, response.text
    assert elapsed < 30  # EXTRACT_WORKER_WALL_SECONDS
    body = response.json()
    assert body["pages"] == WORST_PAGES
    chars = sum(len("".join(b["text"].split())) for b in body["blocks"])
    assert chars >= WORST_PAGES * WORST_LINES * (WORST_LINE_CHARS - 12)
