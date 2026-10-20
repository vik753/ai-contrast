"""AC4: one access log line per request with method, path (no query
string), status and duration in ms (T1, T3)."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from tests.helpers import ai_contrast_records, all_log_text, new_marker

# "12 ms", "12.3ms", or a "duration_ms=12.3" / "duration_ms: 12" style field.
DURATION_RE = re.compile(r"(\d+(?:\.\d+)?\s?ms\b)|(duration_ms\s*[=:]\s*\d)")


def _single_record(caplog: pytest.LogCaptureFixture) -> logging.LogRecord:
    records = ai_contrast_records(caplog)
    assert len(records) == 1, [r.getMessage() for r in records]
    return records[0]


def test_access_log_health_request_logs_exactly_one_record(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    client = make_client()
    log_capture.clear()

    client.get("/api/health")

    assert len(ai_contrast_records(log_capture)) == 1


def test_access_log_two_requests_log_two_records(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    client = make_client()
    log_capture.clear()

    client.get("/api/health")
    client.get("/api/health")

    assert len(ai_contrast_records(log_capture)) == 2


def test_access_log_record_contains_method(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    client = make_client()
    log_capture.clear()

    client.get("/api/health")

    assert "GET" in _single_record(log_capture).getMessage()


def test_access_log_record_contains_path(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    client = make_client()
    log_capture.clear()

    client.get("/api/health")

    assert "/api/health" in _single_record(log_capture).getMessage()


def test_access_log_record_contains_status(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    client = make_client()
    log_capture.clear()

    client.get("/api/health")

    assert re.search(r"\b200\b", _single_record(log_capture).getMessage())


def test_access_log_record_contains_duration_in_ms(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    client = make_client()
    log_capture.clear()

    client.get("/api/health")

    assert DURATION_RE.search(_single_record(log_capture).getMessage())


def test_access_log_not_found_request_logs_method_path_and_404(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    client = make_client()
    log_capture.clear()

    client.post("/api/does-not-exist")

    message = _single_record(log_capture).getMessage()
    assert "POST" in message
    assert "/api/does-not-exist" in message
    assert re.search(r"\b404\b", message)


def test_access_log_query_string_never_logged(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    client = make_client()
    secret_value = new_marker("qsvalue")
    log_capture.clear()

    response = client.get(f"/api/health?secret={secret_value}")

    assert response.status_code == 200
    text = all_log_text(log_capture)
    assert secret_value not in text
    assert "secret=" not in text


def test_access_log_query_string_request_still_logs_path(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    client = make_client()
    log_capture.clear()

    client.get(f"/api/health?secret={new_marker('qsvalue')}")

    message = _single_record(log_capture).getMessage()
    assert "/api/health" in message
    assert "?" not in message


def test_access_log_request_headers_never_logged(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    client = make_client()
    header_value = new_marker("hdrvalue")
    log_capture.clear()

    client.get(
        "/api/health",
        headers={"User-Agent": header_value, "X-Custom": header_value},
    )

    assert header_value not in all_log_text(log_capture)


def test_access_log_request_body_never_logged(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    client = make_client()
    body_value = new_marker("bodyvalue")
    log_capture.clear()

    client.post("/api/health", content=f'{{"contract": "{body_value}"}}')

    assert body_value not in all_log_text(log_capture)
