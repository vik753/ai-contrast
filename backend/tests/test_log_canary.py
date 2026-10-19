"""AC6: log canary. A provider key sent in X-Provider-Key never appears in
logs, response bodies or response headers (T1)."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.helpers import ALLOWED_ORIGIN, add_raising_route, all_log_text, new_canary

BOOM_PATH = "/api/test/boom"


def _assert_canary_absent_from_response(response: httpx.Response, canary: str) -> None:
    assert canary not in response.text
    for name, value in response.headers.items():
        assert canary not in name
        assert canary not in value


def _boom_client(
    make_app: Callable[..., FastAPI],
    make_client: Callable[..., TestClient],
    message: str,
) -> TestClient:
    app = make_app()
    add_raising_route(app, BOOM_PATH, message)
    return make_client(app)


def test_canary_header_on_health_absent_from_logs(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    canary = new_canary()
    client = make_client()
    log_capture.clear()

    response = client.get("/api/health", headers={"X-Provider-Key": canary})

    assert response.status_code == 200
    assert canary not in all_log_text(log_capture)


def test_canary_header_on_health_absent_from_response(
    make_client: Callable[..., TestClient],
) -> None:
    canary = new_canary()

    response = make_client().get("/api/health", headers={"X-Provider-Key": canary})

    _assert_canary_absent_from_response(response, canary)


def test_canary_header_on_cors_preflight_absent_from_logs_and_response(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    canary = new_canary()
    client = make_client(allowed_origins=[ALLOWED_ORIGIN])
    log_capture.clear()

    response = client.options(
        "/api/health",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-Provider-Key",
            "X-Provider-Key": canary,
        },
    )

    assert canary not in all_log_text(log_capture)
    _assert_canary_absent_from_response(response, canary)


def test_canary_header_on_not_found_absent_from_logs_and_response(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    canary = new_canary()
    client = make_client()
    log_capture.clear()

    response = client.get("/api/does-not-exist", headers={"X-Provider-Key": canary})

    assert response.status_code == 404
    assert canary not in all_log_text(log_capture)
    _assert_canary_absent_from_response(response, canary)


def test_canary_header_on_raising_route_absent_from_logs(
    make_app: Callable[..., FastAPI],
    make_client: Callable[..., TestClient],
    log_capture: pytest.LogCaptureFixture,
) -> None:
    canary = new_canary()
    client = _boom_client(make_app, make_client, "unrelated failure")
    log_capture.clear()

    response = client.get(BOOM_PATH, headers={"X-Provider-Key": canary})

    assert response.status_code == 500
    assert canary not in all_log_text(log_capture)


def test_canary_header_on_raising_route_absent_from_response(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    canary = new_canary()
    client = _boom_client(make_app, make_client, "unrelated failure")

    response = client.get(BOOM_PATH, headers={"X-Provider-Key": canary})

    assert response.status_code == 500
    _assert_canary_absent_from_response(response, canary)


def test_canary_in_exception_message_absent_from_logs(
    make_app: Callable[..., FastAPI],
    make_client: Callable[..., TestClient],
    log_capture: pytest.LogCaptureFixture,
) -> None:
    # Simulates an SDK error that echoes the key in its message.
    canary = new_canary()
    client = _boom_client(make_app, make_client, f"invalid api key: {canary}")
    log_capture.clear()

    response = client.get(BOOM_PATH, headers={"X-Provider-Key": canary})

    assert response.status_code == 500
    assert canary not in all_log_text(log_capture)


def test_canary_in_exception_message_absent_from_response(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    canary = new_canary()
    client = _boom_client(make_app, make_client, f"invalid api key: {canary}")

    response = client.get(BOOM_PATH, headers={"X-Provider-Key": canary})

    assert response.status_code == 500
    _assert_canary_absent_from_response(response, canary)


@pytest.mark.parametrize("environment", ["development", "production"])
def test_canary_in_exception_message_absent_in_each_environment(
    make_app: Callable[..., FastAPI],
    make_client: Callable[..., TestClient],
    log_capture: pytest.LogCaptureFixture,
    environment: str,
) -> None:
    canary = new_canary()
    app = make_app(environment=environment)
    add_raising_route(app, BOOM_PATH, f"invalid api key: {canary}")
    client = make_client(app)
    log_capture.clear()

    response = client.get(BOOM_PATH, headers={"X-Provider-Key": canary})

    assert canary not in all_log_text(log_capture)
    _assert_canary_absent_from_response(response, canary)
