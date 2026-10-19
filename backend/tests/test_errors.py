"""AC5: unhandled exceptions return a generic 500 and log only the
exception class name and the request path (T1, T3)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.helpers import BoomError, add_raising_route, all_log_text, new_marker

BOOM_PATH = "/api/test/boom"


def _boom_client(
    make_app: Callable[..., FastAPI],
    make_client: Callable[..., TestClient],
    message: str,
    *,
    raise_server_exceptions: bool = False,
) -> TestClient:
    app = make_app()
    add_raising_route(app, BOOM_PATH, message)
    return make_client(app, raise_server_exceptions=raise_server_exceptions)


def test_unhandled_exception_returns_500(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    client = _boom_client(make_app, make_client, new_marker("boom"))

    response = client.get(BOOM_PATH)

    assert response.status_code == 500


def test_unhandled_exception_body_is_exactly_internal_error(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    client = _boom_client(make_app, make_client, new_marker("boom"))

    response = client.get(BOOM_PATH)

    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"error": "internal_error"}


def test_unhandled_exception_body_omits_exception_message(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    marker = new_marker("boommsg")
    client = _boom_client(make_app, make_client, marker)

    response = client.get(BOOM_PATH)

    assert marker not in response.text
    assert BoomError.__name__ not in response.text


def test_unhandled_exception_does_not_propagate_to_server(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    # If the exception escapes the app, the ASGI server (uvicorn) logs the
    # full traceback including the exception message. The app must handle
    # it completely and return the 500 response itself.
    client = _boom_client(
        make_app, make_client, new_marker("boom"), raise_server_exceptions=True
    )

    response = client.get(BOOM_PATH)

    assert response.status_code == 500


def test_unhandled_exception_log_contains_class_name(
    make_app: Callable[..., FastAPI],
    make_client: Callable[..., TestClient],
    log_capture: pytest.LogCaptureFixture,
) -> None:
    client = _boom_client(make_app, make_client, new_marker("boom"))
    log_capture.clear()

    client.get(BOOM_PATH)

    assert BoomError.__name__ in log_capture.text


def test_unhandled_exception_log_contains_path(
    make_app: Callable[..., FastAPI],
    make_client: Callable[..., TestClient],
    log_capture: pytest.LogCaptureFixture,
) -> None:
    client = _boom_client(make_app, make_client, new_marker("boom"))
    log_capture.clear()

    client.get(BOOM_PATH)

    error_lines = [
        r.getMessage()
        for r in log_capture.records
        if BoomError.__name__ in r.getMessage()
    ]
    assert any(BOOM_PATH in line for line in error_lines), error_lines


def test_unhandled_exception_log_omits_exception_message(
    make_app: Callable[..., FastAPI],
    make_client: Callable[..., TestClient],
    log_capture: pytest.LogCaptureFixture,
) -> None:
    marker = new_marker("boommsg")
    client = _boom_client(make_app, make_client, marker)
    log_capture.clear()

    client.get(BOOM_PATH)

    assert marker not in all_log_text(log_capture)


def test_unhandled_exception_log_omits_query_string(
    make_app: Callable[..., FastAPI],
    make_client: Callable[..., TestClient],
    log_capture: pytest.LogCaptureFixture,
) -> None:
    query_value = new_marker("qsvalue")
    client = _boom_client(make_app, make_client, new_marker("boom"))
    log_capture.clear()

    client.get(f"{BOOM_PATH}?q={query_value}")

    assert query_value not in all_log_text(log_capture)


def test_unhandled_exception_log_omits_request_headers(
    make_app: Callable[..., FastAPI],
    make_client: Callable[..., TestClient],
    log_capture: pytest.LogCaptureFixture,
) -> None:
    header_value = new_marker("hdrvalue")
    client = _boom_client(make_app, make_client, new_marker("boom"))
    log_capture.clear()

    client.get(
        BOOM_PATH, headers={"X-Custom": header_value, "User-Agent": header_value}
    )

    assert header_value not in all_log_text(log_capture)


def test_unhandled_exception_is_access_logged_with_status_500(
    make_app: Callable[..., FastAPI],
    make_client: Callable[..., TestClient],
    log_capture: pytest.LogCaptureFixture,
) -> None:
    client = _boom_client(make_app, make_client, new_marker("boom"))
    log_capture.clear()

    client.get(BOOM_PATH)

    access_lines = [
        r.getMessage()
        for r in log_capture.records
        if r.name.startswith("ai_contrast")
        and "GET" in r.getMessage()
        and BOOM_PATH in r.getMessage()
        and "500" in r.getMessage()
    ]
    assert access_lines, [r.getMessage() for r in log_capture.records]
