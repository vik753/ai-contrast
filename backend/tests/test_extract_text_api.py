"""S3-T1 AC2, AC6, AC7, AC10: ``POST /api/extract`` returns the stage 3
response contract for text files (DOCX: tests/test_docx_api.py, PDF:
tests/test_pdf_api.py).

Assumed contract (see the test report): ``app/api/extract.py`` imports
``run_extraction`` by name and calls it as
``run_extraction(data, kind, limits=SandboxLimits(...))`` (no ``test_hook``),
so the slot tests patch ``app.api.extract.run_extraction``. Extraction errors
are ``422 {"error": <code>}``.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.extraction.detect import FileKind
from app.extraction.model import ExtractionError, ExtractionResult
from app.extraction.text import extract_text_file
from tests.asgi_stream import AsgiRun, chunks, drive, drive_receive, post_scope
from tests.helpers import access_lines, all_log_text, new_canary
from tests.zipbuild import PDF_SAMPLE

EXTRACT = "/api/extract"
OCTET = {"Content-Type": "application/octet-stream"}
MIB = 1024 * 1024
CONTRACT_KEYS = {"kind", "bytes", "language", "pages", "blocks", "ocr_pages", "removed", "warnings"}
HOOK_ENV = "AI_CONTRAST_WORKER_TEST_HOOK"

EN = (
    "SERVICE AGREEMENT (synthetic test data)\r\n\r\n"
    "1. This Agreement is made between the Provider and the Client.\r\n"
    "2. The Client shall pay each invoice within thirty days of receipt.\r\n\r\n"
    "3. Either party may terminate this Agreement with sixty days written notice.\r\n"
)
EN_BLOCKS = [
    "SERVICE AGREEMENT (synthetic test data)",
    "1. This Agreement is made between the Provider and the Client.\n"
    "2. The Client shall pay each invoice within thirty days of receipt.",
    "3. Either party may terminate this Agreement with sixty days written notice.",
]
UK = (
    "ДОГОВІР ПРО НАДАННЯ ПОСЛУГ (тестові дані).\n\n"
    "Замовник сплачує кожен рахунок протягом тридцяти днів з дня його отримання. "
    "Будь-яка сторона може розірвати цей договір, повідомивши іншу сторону за шістдесят днів.\n"
)


def _post(client: TestClient, body: bytes) -> Any:
    return client.post(EXTRACT, content=body, headers=OCTET)


def _slot_free(app: FastAPI) -> bool:
    limiter = app.state.extraction_limiter
    if limiter.try_acquire():
        limiter.release()
        return True
    return False


# --- 200 for text: the full stage 3 contract (AC7) -----------------------------------------


def test_extract_text_returns_exactly_the_contract_keys(
    make_client: Callable[..., TestClient],
) -> None:
    response = _post(make_client(), EN.encode())

    assert response.status_code == 200
    assert set(response.json()) == CONTRACT_KEYS


def test_extract_text_returns_kind_bytes_and_language(
    make_client: Callable[..., TestClient],
) -> None:
    body = EN.encode()

    data = _post(make_client(), body).json()

    assert (data["kind"], data["bytes"], data["language"]) == ("text", len(body), "en")


def test_extract_text_returns_blocks_as_body_without_page(
    make_client: Callable[..., TestClient],
) -> None:
    data = _post(make_client(), EN.encode()).json()

    assert data["blocks"] == [{"text": t, "part": "body", "page": None} for t in EN_BLOCKS]


def test_extract_text_returns_null_pages_and_empty_lists(
    make_client: Callable[..., TestClient],
) -> None:
    data = _post(make_client(), EN.encode()).json()

    assert data["pages"] is None
    assert (data["ocr_pages"], data["removed"], data["warnings"]) == ([], [], [])


def test_extract_text_response_validates_against_the_model(
    make_client: Callable[..., TestClient],
) -> None:
    response = _post(make_client(), EN.encode())

    ExtractionResult.model_validate_json(response.content)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"\xff\xfe" + UK.encode("utf-16-le"), id="utf16le"),
        pytest.param(b"\xfe\xff" + UK.encode("utf-16-be"), id="utf16be"),
        pytest.param(UK.encode("cp1251"), id="cp1251"),
        pytest.param(b"\xef\xbb\xbf" + UK.encode("utf-8"), id="utf8-bom"),
    ],
)
def test_extract_text_encodings_decoded_to_ukrainian(
    make_client: Callable[..., TestClient], body: bytes
) -> None:
    data = _post(make_client(), body).json()

    assert "\n\n".join(block["text"] for block in data["blocks"]) == UK.strip()
    assert data["language"] == "uk"


# --- PDF and DOCX go through the sandbox since S3-T2/S3-T3 (AC7 501 removed) --------------


@pytest.mark.parametrize(
    # S3-T2: DOCX is extracted now (tests/test_docx_api.py); PDF until S3-T3.
    "body",
    [pytest.param(PDF_SAMPLE, id="pdf")],
)
def test_extract_pdf_and_docx_slot_released(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient], body: bytes
) -> None:
    app = make_app(max_concurrent_extractions=1)

    _post(make_client(app), body)

    assert _slot_free(app)


# --- Extraction errors through the API (AC6) -------------------------------------------------


@pytest.mark.parametrize(
    ("settings", "body", "code"),
    [
        pytest.param({"extract_max_text_chars": 50}, b"a" * 51, "too_much_text", id="chars"),
        pytest.param({"extract_max_blocks": 2}, b"A\n\nB\n\nC", "too_much_text", id="blocks"),
        pytest.param(
            {"extract_max_result_bytes": 1000},
            b"synthetic clause text " * 200,
            "extraction_failed",
            id="result-bytes",
        ),
        pytest.param({}, b"\n \n\t\n", "no_text_extracted", id="whitespace"),
        pytest.param(
            {},
            b"Synthetic clause text.\n" * 3000 + b"\x01" * 5000,
            "text_decoding_failed",
            id="controls-after-64k",
        ),
        pytest.param(
            {},
            b"\xff\xfe" + "Договір".encode("utf-16-le") + b"\x00\xd8A\x00",
            "text_decoding_failed",
            id="bad-utf16",
        ),
        pytest.param({}, b"a" * (10 * MIB), "too_much_text", id="10mib-default-cap"),
    ],
)
def test_extract_text_failure_returns_422_with_code(
    make_client: Callable[..., TestClient], settings: dict[str, int], body: bytes, code: str
) -> None:
    response = _post(make_client(**settings), body)

    assert response.status_code == 422
    assert response.json() == {"error": code}


def test_extract_text_at_configured_char_cap_accepted(
    make_client: Callable[..., TestClient],
) -> None:
    response = _post(make_client(extract_max_text_chars=50), b"a" * 50)

    assert response.status_code == 200


def test_extract_text_failure_releases_slot(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    app = make_app(max_concurrent_extractions=1, extract_max_text_chars=10)
    client = make_client(app)

    first = _post(client, b"a" * 11)
    second = _post(client, b"a" * 5)

    assert (first.status_code, second.status_code) == (422, 200)
    assert _slot_free(app)


def test_extract_hook_variable_in_server_environment_has_no_effect(
    monkeypatch: pytest.MonkeyPatch, make_client: Callable[..., TestClient]
) -> None:
    monkeypatch.setenv(HOOK_ENV, "exit_nonzero")

    assert _post(make_client(), EN.encode()).status_code == 200


# --- The sandbox call from the handler (AC2: slot held while the child runs) ---------------


class FakeSandbox:
    """Stands in for ``run_extraction``; blocks until released."""

    def __init__(self, *, error: BaseException | None = None) -> None:
        self.calls: list[tuple[bytes, Any, Any]] = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.error = error

    async def __call__(self, data: bytes, kind: Any, *, limits: Any) -> ExtractionResult:
        self.calls.append((data, kind, limits))
        self.entered.set()
        await self.release.wait()
        if self.error is not None:
            raise self.error
        return extract_text_file(data)


def _body_then_stay_connected(body: bytes) -> Callable[[], Any]:
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.Event().wait()  # the client stays connected
        raise AssertionError("unreachable")

    return receive


def _run_with_fake(app: FastAPI, fake: FakeSandbox, body: bytes) -> tuple[AsgiRun, bool, bool]:
    """Run one request; return (run, slot free while extracting, slot free after)."""

    async def scenario() -> tuple[AsgiRun, bool, bool]:
        task = asyncio.create_task(
            drive_receive(
                app,
                post_scope(EXTRACT, content_length=len(body)),
                _body_then_stay_connected(body),
            )
        )
        await asyncio.wait_for(fake.entered.wait(), 10)
        free_during = _slot_free(app)
        fake.release.set()
        run = await task
        return run, free_during, _slot_free(app)

    return asyncio.run(scenario())


@pytest.fixture
def patch_sandbox(monkeypatch: pytest.MonkeyPatch) -> Callable[[FakeSandbox], None]:
    def _patch(fake: FakeSandbox) -> None:
        monkeypatch.setattr("app.api.extract.run_extraction", fake)

    return _patch


def test_extract_slot_held_while_extracting(
    make_app: Callable[..., FastAPI], patch_sandbox: Callable[[FakeSandbox], None]
) -> None:
    app = make_app(max_concurrent_extractions=1)
    fake = FakeSandbox()
    patch_sandbox(fake)

    _, free_during, _ = _run_with_fake(app, fake, EN.encode())

    assert free_during is False


def test_extract_slot_free_after_extracting(
    make_app: Callable[..., FastAPI], patch_sandbox: Callable[[FakeSandbox], None]
) -> None:
    app = make_app(max_concurrent_extractions=1)
    fake = FakeSandbox()
    patch_sandbox(fake)

    run, _, free_after = _run_with_fake(app, fake, EN.encode())

    assert run.status == 200
    assert free_after is True


@pytest.mark.parametrize("code", ["extraction_timeout", "extraction_failed"])
def test_extract_sandbox_error_returns_422_and_frees_slot(
    make_app: Callable[..., FastAPI], patch_sandbox: Callable[[FakeSandbox], None], code: str
) -> None:
    app = make_app(max_concurrent_extractions=1)
    fake = FakeSandbox(error=ExtractionError(code))
    patch_sandbox(fake)

    run, _, free_after = _run_with_fake(app, fake, EN.encode())

    assert run.status == 422
    assert json.loads(run.body) == {"error": code}
    assert free_after is True


def test_extract_unexpected_sandbox_error_frees_slot(
    make_app: Callable[..., FastAPI], patch_sandbox: Callable[[FakeSandbox], None]
) -> None:
    app = make_app(max_concurrent_extractions=1)
    fake = FakeSandbox(error=RuntimeError("synthetic failure"))
    patch_sandbox(fake)

    run, _, free_after = _run_with_fake(app, fake, EN.encode())

    assert run.status == 500
    assert free_after is True


def test_extract_sandbox_gets_body_and_detected_text_kind(
    make_app: Callable[..., FastAPI], patch_sandbox: Callable[[FakeSandbox], None]
) -> None:
    app = make_app()
    fake = FakeSandbox()
    patch_sandbox(fake)
    body = EN.encode()

    _run_with_fake(app, fake, body)

    assert [(data, kind) for data, kind, _ in fake.calls] == [(body, FileKind.TEXT)]


def test_extract_sandbox_limits_follow_settings(
    make_app: Callable[..., FastAPI], patch_sandbox: Callable[[FakeSandbox], None]
) -> None:
    app = make_app(
        extract_worker_memory_mb=150,
        extract_worker_cpu_seconds=11,
        extract_worker_wall_seconds=13,
        extract_max_result_bytes=123_456,
    )
    fake = FakeSandbox()
    patch_sandbox(fake)

    _run_with_fake(app, fake, EN.encode())

    limits = fake.calls[0][2]
    assert (
        limits.memory_bytes,
        limits.cpu_seconds,
        limits.wall_seconds,
        limits.max_result_bytes,
    ) == (150 * MIB, 11, 13, 123_456)


@pytest.mark.parametrize(
    # S3-T2: DOCX is extracted now (tests/test_docx_api.py); PDF until S3-T3.
    "body",
    [pytest.param(PDF_SAMPLE, id="pdf")],
)
def test_extract_pdf_reaches_the_sandbox(
    make_client: Callable[..., TestClient],
    patch_sandbox: Callable[[FakeSandbox], None],
    body: bytes,
) -> None:
    fake = FakeSandbox()
    fake.release.set()
    patch_sandbox(fake)

    # S3-T3: PDF extraction exists, so the request reaches the sandbox.
    _post(make_client(), body)
    assert len(fake.calls) == 1


# --- Logs and privacy (AC10) -------------------------------------------------------------------


def test_extract_text_canary_in_file_absent_from_logs(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    canary = new_canary()
    client = make_client()
    log_capture.clear()

    response = _post(client, f"Party: {canary}.\n\nPay in 30 days.\n".encode())

    assert response.status_code == 200
    assert canary not in all_log_text(log_capture)


@pytest.mark.parametrize(
    ("settings", "tail", "code"),
    [
        pytest.param({"extract_max_text_chars": 60}, b"a" * 100, "too_much_text", id="chars"),
        pytest.param(
            {"extract_max_result_bytes": 300}, b" clause" * 100, "extraction_failed", id="result"
        ),
        pytest.param({}, b" \x98", "text_decoding_failed", id="decoding"),
    ],
)
def test_extract_text_failure_canary_absent_from_logs_and_response(
    make_client: Callable[..., TestClient],
    log_capture: pytest.LogCaptureFixture,
    settings: dict[str, int],
    tail: bytes,
    code: str,
) -> None:
    canary = new_canary()
    client = make_client(**settings)
    log_capture.clear()

    response = _post(client, canary.encode() + tail)

    assert response.json() == {"error": code}
    assert canary not in all_log_text(log_capture)
    assert canary not in response.text
    assert all(canary not in value for value in response.headers.values())


ACCESS_LINE = re.compile(r"^POST /api/extract (?P<status>\d{3}) duration_ms=\d+$")


@pytest.mark.parametrize(
    ("body", "status"),
    [
        pytest.param(EN.encode(), 200, id="200"),
        pytest.param(PDF_SAMPLE, 422, id="422-pdf"),
        pytest.param(b"\n \n", 422, id="422"),
    ],
)
def test_extract_access_log_line_unchanged(
    make_client: Callable[..., TestClient],
    log_capture: pytest.LogCaptureFixture,
    body: bytes,
    status: int,
) -> None:
    client = make_client()
    log_capture.clear()

    _post(client, body)

    lines = access_lines(log_capture, "POST", EXTRACT)
    assert len(lines) == 1
    match = ACCESS_LINE.match(lines[0])
    assert match is not None, lines[0]
    assert match.group("status") == str(status)


# --- Review round 1 (PR #20): slot held until the response is sent (T6) ---------------------


def _never_reading_client(
    body: bytes,
) -> tuple[Callable[[], Any], Callable[[dict[str, Any]], Any], asyncio.Event]:
    """receive/send of a client that uploads, stays connected and never reads:
    every ``send`` blocks, as a write to a full socket buffer does."""
    receive = _body_then_stay_connected(body)
    send_started = asyncio.Event()

    async def send(message: dict[str, Any]) -> None:
        send_started.set()
        await asyncio.Event().wait()

    return receive, send, send_started


def _stalled_send_scenario(
    app: FastAPI, *, wait_seconds: float
) -> tuple[int | None, bool, bool, float]:
    """First request: a client that never reads. While its response is pending, a
    second (normal) request. Returns (second status, first finished, slot free
    after, seconds from first send to its end)."""
    body = EN.encode()

    async def scenario() -> tuple[int | None, bool, bool, float]:
        receive, send, send_started = _never_reading_client(body)
        scope = post_scope(EXTRACT, content_length=len(body))
        first = asyncio.create_task(app(scope, receive, send))
        await asyncio.wait_for(send_started.wait(), 20)
        started = time.monotonic()
        second = await drive(app, post_scope(EXTRACT, content_length=len(body)), chunks(body))
        done, _ = await asyncio.wait({first}, timeout=wait_seconds)
        elapsed = time.monotonic() - started
        if first in done and not first.cancelled():
            first.exception()  # a cut-off may raise; only the outcome matters here
        else:
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
        return second.status, first in done, _slot_free(app), elapsed

    return asyncio.run(scenario())


def test_extract_slot_held_while_response_not_read(make_app: Callable[..., FastAPI]) -> None:
    app = make_app(max_concurrent_extractions=1, extract_send_timeout_seconds=2)

    second_status, _, _, _ = _stalled_send_scenario(app, wait_seconds=2 + 15)

    assert second_status == 503


def test_extract_client_not_reading_cut_off_after_send_timeout(
    make_app: Callable[..., FastAPI],
) -> None:
    app = make_app(max_concurrent_extractions=1, extract_send_timeout_seconds=2)

    _, finished, _, elapsed = _stalled_send_scenario(app, wait_seconds=2 + 15)

    assert finished, "the response to a client that does not read was never cut off"
    assert elapsed >= 2 - 0.5, f"cut off too early: {elapsed:.2f} s"


def test_extract_slot_free_after_send_timeout(make_app: Callable[..., FastAPI]) -> None:
    app = make_app(max_concurrent_extractions=1, extract_send_timeout_seconds=2)

    _, _, free_after, _ = _stalled_send_scenario(app, wait_seconds=2 + 15)

    assert free_after is True


def test_extract_server_answers_after_send_timeout(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    app = make_app(max_concurrent_extractions=1, extract_send_timeout_seconds=2)
    _stalled_send_scenario(app, wait_seconds=2 + 15)

    assert _post(make_client(app), EN.encode()).status_code == 200
