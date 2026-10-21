"""S2-T1 AC7: upload privacy. No file content, file name or key in logs or
responses (T1, T3, T11 control 8, ADR 0010).

Every request carries a canary in the body, in
``Content-Disposition: attachment; filename="<canary>"``, in
``X-File-Name: <canary>`` and in ``X-Provider-Key``. The canary must not show
up in any captured log record (all loggers, DEBUG) or in the response.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.asgi_stream import endless, post_scope, run_driven
from tests.helpers import access_lines, all_log_text, new_canary
from tests.zipbuild import build_zip, docx_entries, stored

EXTRACT = "/api/extract"
MIB = 1024 * 1024


def _headers(canary: str, content_type: str = "application/octet-stream") -> dict[str, str]:
    return {
        "Content-Type": content_type,
        "Content-Disposition": f'attachment; filename="{canary}.docx"',
        "X-File-Name": f"{canary}.docx",
        "X-Provider-Key": canary,
    }


def _assert_absent_from_response(response: httpx.Response, canary: str) -> None:
    assert canary not in response.text
    for name, value in response.headers.items():
        assert canary not in name
        assert canary not in value


def _bodies(canary: str) -> dict[str, tuple[bytes, int]]:
    """Request bodies that contain the canary, with the expected status."""
    marker = canary.encode()
    return {
        "text": (b"Synthetic contract. Party: " + marker + b". Pay in 30 days.\n", 200),
        # S3-T1: PDF and DOCX return 501 until S3-T2/S3-T3.
        "pdf": (b"%PDF-1.7\n% " + marker + b"\n%%EOF\n", 501),
        # S3-T2: DOCX is extracted; the canary sits in an unrelated part and its name.
        "docx": (build_zip(docx_entries(stored(f"word/{canary}.xml", marker))), 200),
        "binary": (b"synthetic\x00" + marker, 422),
        "controls": (b"\x01" * 100 + marker, 422),
        "duplicate-name": (
            build_zip(docx_entries(stored(f"word/{canary}.xml"), stored(f"WORD/{canary}.XML"))),
            422,
        ),
        "dotdot-name": (build_zip(docx_entries(stored(f"../{canary}.xml"))), 422),
        "pages": (build_zip([stored(f"Index/{canary}.iwa", marker)]), 422),
        "trailing": (build_zip(docx_entries(), comment=marker) + marker, 422),
    }


BODY_CASES = [
    "text",
    "pdf",
    "docx",
    "binary",
    "controls",
    "duplicate-name",
    "dotdot-name",
    "pages",
    "trailing",
]


@pytest.mark.parametrize("case", BODY_CASES)
def test_extract_canary_absent_from_logs(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture, case: str
) -> None:
    canary = new_canary()
    body, status = _bodies(canary)[case]
    client = make_client()
    log_capture.clear()

    response = client.post(EXTRACT, content=body, headers=_headers(canary))

    assert response.status_code == status
    assert canary not in all_log_text(log_capture)


@pytest.mark.parametrize("case", BODY_CASES)
def test_extract_canary_absent_from_response(
    make_client: Callable[..., TestClient], case: str
) -> None:
    canary = new_canary()
    header_canary = new_canary()
    body, status = _bodies(canary)[case]

    response = make_client().post(EXTRACT, content=body, headers=_headers(header_canary))

    assert response.status_code == status
    # File names and other header values never come back.
    _assert_absent_from_response(response, header_canary)
    if case != "text":
        # Stage 3 returns the extracted text of a text file by design; any other
        # body content never comes back.
        _assert_absent_from_response(response, canary)


def test_extract_too_large_canary_absent_from_logs_and_response(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    canary = new_canary()
    client = make_client(max_file_bytes=100)
    log_capture.clear()

    response = client.post(EXTRACT, content=canary.encode() * 10, headers=_headers(canary))

    assert response.status_code == 413
    assert canary not in all_log_text(log_capture)
    _assert_absent_from_response(response, canary)


def test_extract_wrong_content_type_canary_absent_from_logs_and_response(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    canary = new_canary()
    client = make_client()
    log_capture.clear()

    response = client.post(
        EXTRACT,
        content=canary.encode(),
        headers=_headers(canary, content_type=f'text/plain; name="{canary}"'),
    )

    assert response.status_code == 415
    assert canary not in all_log_text(log_capture)
    _assert_absent_from_response(response, canary)


def test_extract_multipart_with_file_name_canary_absent_from_logs_and_response(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    canary = new_canary()
    client = make_client()
    log_capture.clear()

    response = client.post(
        EXTRACT, files={"file": (f"{canary}.txt", canary.encode(), "text/plain")}
    )

    assert response.status_code == 415
    assert canary not in all_log_text(log_capture)
    _assert_absent_from_response(response, canary)


def test_extract_chunked_canary_absent_from_logs_and_response(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    canary = new_canary()
    client = make_client()
    log_capture.clear()

    response = client.post(EXTRACT, content=iter([canary.encode()]), headers=_headers(canary))

    assert response.status_code == 411
    assert canary not in all_log_text(log_capture)
    _assert_absent_from_response(response, canary)


def test_extract_busy_canary_absent_from_logs_and_response(
    make_app: Callable[..., FastAPI],
    make_client: Callable[..., TestClient],
    log_capture: pytest.LogCaptureFixture,
) -> None:
    canary = new_canary()
    app = make_app()
    client = make_client(app)
    while app.state.extraction_limiter.try_acquire():
        pass
    log_capture.clear()

    response = client.post(EXTRACT, content=canary.encode(), headers=_headers(canary))

    assert response.status_code == 503
    assert canary not in all_log_text(log_capture)
    _assert_absent_from_response(response, canary)


def test_extract_streamed_overflow_canary_absent_from_logs(
    make_app: Callable[..., FastAPI], log_capture: pytest.LogCaptureFixture
) -> None:
    canary = new_canary()
    app = make_app(max_file_bytes=4096)
    scope = post_scope(
        EXTRACT,
        content_length=4096,
        extra_headers=[
            ("content-disposition", f'attachment; filename="{canary}"'),
            ("x-file-name", canary),
        ],
    )
    log_capture.clear()

    run = run_driven(app, scope, endless(canary.encode() * 30, max_total=MIB))

    assert run.status == 413
    assert canary not in all_log_text(log_capture)
    assert canary.encode() not in run.body


# --- Access log line ---------------------------------------------------------------------

ACCESS_LINE = re.compile(r"^POST /api/extract (?P<status>\d{3}) duration_ms=\d+$")


@pytest.mark.parametrize(
    ("body", "status"),
    [
        pytest.param(b"synthetic text", 200, id="200"),
        pytest.param(b"synthetic\x00binary", 422, id="422"),
    ],
)
def test_extract_access_log_line_is_method_path_status_duration(
    make_client: Callable[..., TestClient],
    log_capture: pytest.LogCaptureFixture,
    body: bytes,
    status: int,
) -> None:
    client = make_client()
    log_capture.clear()

    client.post(EXTRACT, content=body, headers={"Content-Type": "application/octet-stream"})

    lines = access_lines(log_capture, "POST", EXTRACT)
    assert len(lines) == 1
    match = ACCESS_LINE.match(lines[0])
    assert match is not None, lines[0]
    assert match.group("status") == str(status)
