# ruff: noqa: RUF001 - Cyrillic sample text
"""S5b-T4 AC 1: text outside the content never reaches blocks, masked text, logs or replies.

File name (headers, query string, Google ``Content-Disposition``), DOCX ``docProps``
(core, app, custom), PDF Info dictionary and XMP stream. The canary is an ASCII token,
so a match cannot be a false positive of the identifier detector.
"""

from __future__ import annotations

import io
import secrets
import zipfile
from typing import Any

import pytest

from tests.canary import builders
from tests.canary.harness import CellRun, extract, find_leaks, pipeline, tap_logs
from tests.pdfbuild import text_pdf


def _token() -> str:
    return "canary" + secrets.token_hex(10)


def _run(path: str, data: bytes, **kwargs: Any) -> tuple[CellRun, Any, str]:
    run = CellRun(path, "outside", [])
    with tap_logs() as tap:
        reply = extract(path, data, **kwargs)
        assert reply.status_code == 200, reply.text[:200]
        run.blocks = reply.json()["blocks"]
        pipeline(run.blocks, run)
    return run, reply, tap.text


def _assert_nothing_outside(token: str, run: CellRun, reply: Any, logs: str) -> None:
    headers = "\n".join(f"{k}: {v}" for k, v in reply.headers.items())
    assert run.blocks, "the file has body text: the extraction must not be empty"
    assert find_leaks([token], run.block_text) == [], "reached the blocks"
    assert find_leaks([token], reply.text, headers) == [], "reached the extract reply"
    assert find_leaks([token], str(run.segment), run.masked_text) == [], (
        "reached segment or masked text"
    )
    assert find_leaks([token], run.safety_text, str(run.safety_headers)) == [], (
        "reached safety reply"
    )
    assert find_leaks([token], logs) == [], "reached the logs"
    assert run.safety_status == 200


@pytest.mark.parametrize("path", ["txt", "docx", "pdf"])
def test_file_name_in_headers_and_query_never_reaches_text_or_logs(path: str) -> None:
    token = _token()
    body = {
        "txt": "Загальні положення договору.\n\nСтрахувальник сплачує внесок вчасно.".encode(),
        "docx": builders.docx_with_properties("plain"),  # any valid file with body text
        "pdf": text_pdf(builders.FILLER),
    }[path]
    run, reply, logs = _run(
        path,
        body,
        headers={
            "Content-Disposition": f'attachment; filename="{token}.{path}"',
            "X-File-Name": f"{token}.{path}",
            "Referer": f"https://example.invalid/{token}",
        },
        url=f"?filename={token}&name={token}",
    )
    _assert_nothing_outside(token, run, reply, logs)


def test_google_file_name_header_never_reaches_text_or_logs() -> None:
    token = _token()
    run, reply, logs = _run(
        "gdoc",
        builders.docx_with_properties("plain"),
        google_headers={"Content-Disposition": f'attachment; filename="{token}.docx"'},
    )
    _assert_nothing_outside(token, run, reply, logs)


@pytest.mark.parametrize("path", ["docx", "gdoc"])
def test_docx_doc_props_never_reach_text_or_logs(path: str) -> None:
    token = _token()
    run, reply, logs = _run(path, builders.docx_with_properties(token))
    _assert_nothing_outside(token, run, reply, logs)


def test_pdf_info_and_xmp_never_reach_text_or_logs() -> None:
    token = _token()
    data = builders.pdf_with_metadata(token)
    assert token.encode() in data  # the fixture really carries the canary (Info and XMP)
    assert b"/Info 5000 0 R" in data
    run, reply, logs = _run("pdf", data)
    _assert_nothing_outside(token, run, reply, logs)


def test_docx_doc_props_fixture_really_carries_the_canary_in_three_parts() -> None:
    token = _token()
    with zipfile.ZipFile(io.BytesIO(builders.docx_with_properties(token))) as archive:
        carrying = [n for n in archive.namelist() if token.encode() in archive.read(n)]
    assert sorted(carrying) == ["docProps/app.xml", "docProps/core.xml", "docProps/custom.xml"]
