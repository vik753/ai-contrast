"""S3-T2 through ``POST /api/extract``: the full path (detection, sandbox child,
``extract_docx``, contract validation in the parent). AC3, AC5, AC9, AC10 and the
log rules of threat model T1/T4. Must fail before the implementation exists
(today DOCX returns ``501 not_implemented``).

Assumption (see the test report): DOCX extraction errors are
``422 {"error": <code>}``, including ``archive_rejected`` from the child.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.docxbuild import (
    CLAUSE,
    CLAUSE_UK,
    Package,
    body_docx,
    build_docx,
    document_xml,
    layout,
    p,
    para,
    r,
    stored_entries,
    style,
    styles_xml,
    zip_info_ratio,
)
from tests.helpers import all_log_text, new_canary
from tests.zipbuild import RawEntry

EXTRACT = "/api/extract"
OCTET = {"Content-Type": "application/octet-stream"}
CONTRACT_KEYS = {"kind", "bytes", "language", "pages", "blocks", "ocr_pages", "removed", "warnings"}
HIDDEN = "Hidden clause: the Client waives every claim (synthetic)."


def _post(client: TestClient, body: bytes) -> Any:
    return client.post(EXTRACT, content=body, headers=OCTET)


def test_api_valid_docx_200_with_blocks(make_client: Callable[..., TestClient]) -> None:
    data = build_docx(
        Package(body=para(CLAUSE_UK) + para(CLAUSE_UK), footnotes=[para("Примітка до договору.")])
    )

    response = _post(make_client(), data)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == CONTRACT_KEYS
    assert (body["kind"], body["bytes"], body["language"], body["pages"]) == (
        "docx",
        len(data),
        "uk",
        None,
    )
    assert body["blocks"] == [
        {"text": CLAUSE_UK, "part": "body", "page": None},
        {"text": CLAUSE_UK, "part": "body", "page": None},
        {"text": "Примітка до договору.", "part": "footnote", "page": None},
    ]
    assert (body["ocr_pages"], body["removed"], body["warnings"]) == ([], [], [])


def test_api_docx_dtd_422_suspicious_package(make_client: Callable[..., TestClient]) -> None:
    prolog = '<?xml version="1.0"?>\n<!DOCTYPE x [<!ENTITY e "synthetic">]>\n'
    data = build_docx(Package(document=document_xml(para(CLAUSE), prolog=prolog)))

    response = _post(make_client(), data)

    assert response.status_code == 422
    assert response.json() == {"error": "suspicious_package"}


def test_api_docx_bad_crc_422_archive_rejected(make_client: Callable[..., TestClient]) -> None:
    # Detection never decompresses, so only the child can find this.
    entries = stored_entries()
    doc = entries[2]
    entries[2] = RawEntry(name=doc.name, data=doc.data, crc=0x0BADC0DE)

    response = _post(make_client(), layout(entries))

    assert response.status_code == 422
    assert response.json() == {"error": "archive_rejected"}


def test_api_docx_hidden_text_removed_and_reported(make_client: Callable[..., TestClient]) -> None:
    data = body_docx(para(CLAUSE), p(r(HIDDEN, "<w:vanish/>")))

    body = _post(make_client(), data).json()

    assert [b["text"] for b in body["blocks"]] == [CLAUSE]
    assert [x["reason"] for x in body["removed"]] == ["hidden_formatting"]
    assert HIDDEN[:40] in body["removed"][0]["sample"]


def test_api_docx_slot_released(
    make_app: Callable[..., Any], make_client: Callable[..., TestClient]
) -> None:
    app = make_app(max_concurrent_extractions=1)

    _post(make_client(app), body_docx(para(CLAUSE)))

    limiter = app.state.extraction_limiter
    assert limiter.try_acquire()
    limiter.release()


def test_api_docx_canary_absent_from_logs(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    canary = new_canary()
    client = make_client()
    log_capture.clear()

    response = _post(client, body_docx(para(f"Party: {canary}."), p(r(canary, "<w:vanish/>"))))

    assert response.status_code == 200
    assert canary not in all_log_text(log_capture)


def test_api_docx_failure_canary_absent_from_logs_and_response(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    canary = new_canary()
    prolog = f'<?xml version="1.0"?>\n<!DOCTYPE x [<!ENTITY e "{canary}">]>\n'
    data = build_docx(Package(document=document_xml(para(canary), prolog=prolog)))
    client = make_client()
    log_capture.clear()

    response = _post(client, data)

    assert response.json() == {"error": "suspicious_package"}
    assert canary not in all_log_text(log_capture)
    assert canary not in response.text


# --- AC10: a worst-case DOCX at the caps finishes inside the child limits ------------------------

WORST_PARAGRAPHS = 19_000  # EXTRACT_MAX_BLOCKS is 20,000
RUNS_PER_PARAGRAPH = 24  # 4 elements per run: about 1.88 million elements (cap 2,000,000)
NESTING = 120  # 120 w:sdt/w:sdtContent pairs: depth about 246 (cap 256)


def _noise(chars: int) -> str:
    """Deterministic incompressible words, so that the deflate ratio stays under the
    detection cap of 200."""
    out: list[str] = []
    seed = b"synthetic"
    while sum(len(w) + 1 for w in out) < chars:
        seed = hashlib.sha256(seed).digest()
        out.extend(seed.hex()[i : i + 8] for i in range(0, 64, 8))
    return " ".join(out)[:chars]


def worst_case_docx() -> bytes:
    # About 29 MB of XML in the main part (MAX_DOCX_PART_BYTES is 32 MiB).
    run = '<w:r><w:rPr><w:rStyle w:val="C9"/></w:rPr><w:t>a</w:t></w:r>'
    paragraph = '<w:p><w:pPr><w:pStyle w:val="P9"/></w:pPr>' + run * RUNS_PER_PARAGRAPH + "</w:p>"
    nested = (
        "<w:sdt><w:sdtContent>" * NESTING
        + para("Deep clause.")
        + ("</w:sdtContent></w:sdt>" * NESTING)
    )
    body = paragraph * WORST_PARAGRAPHS + nested + para(_noise(300_000))
    # basedOn chains ten styles deep, for paragraph and character styles.
    chain = [style("P0", rpr='<w:color w:val="000000"/>')]
    chain += [style(f"P{i}", based_on=f"P{i - 1}") for i in range(1, 10)]
    chain += [style("C0", kind="character", rpr='<w:sz w:val="22"/>')]
    chain += [style(f"C{i}", kind="character", based_on=f"C{i - 1}") for i in range(1, 10)]
    return build_docx(Package(body=body, styles=styles_xml(*chain)))


@pytest.fixture(scope="module")
def worst_case() -> bytes:
    return worst_case_docx()


def test_fixture_worst_case_passes_detection_limits(worst_case: bytes) -> None:
    assert len(worst_case) < 10 * 1024 * 1024
    assert zip_info_ratio(worst_case) <= 200


def test_api_docx_worst_case_at_caps_within_child_limits(
    make_client: Callable[..., TestClient], worst_case: bytes
) -> None:
    client = make_client()

    started = time.monotonic()
    response = _post(client, worst_case)
    elapsed = time.monotonic() - started

    assert response.status_code == 200, response.text
    assert elapsed < 30  # EXTRACT_WORKER_WALL_SECONDS
    blocks = response.json()["blocks"]
    assert len(blocks) == WORST_PARAGRAPHS + 2
    assert blocks[0]["text"] == "a" * RUNS_PER_PARAGRAPH
