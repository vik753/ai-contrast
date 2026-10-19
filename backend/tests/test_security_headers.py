"""AC2: security headers on every API response (T1, T3)."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.helpers import ALLOWED_ORIGIN, add_raising_route, new_marker

EXPECTED_HEADERS = {
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
}


def _assert_security_headers(response: httpx.Response) -> None:
    for name, value in EXPECTED_HEADERS.items():
        assert response.headers.get(name) == value, (
            f"{name}: {response.headers.get(name)!r}"
        )


@pytest.mark.parametrize("environment", ["development", "production"])
def test_security_headers_on_health_response_present(
    make_client: Callable[..., TestClient], environment: str
) -> None:
    response = make_client(environment=environment).get("/api/health")

    _assert_security_headers(response)


def test_security_headers_on_404_response_present(
    make_client: Callable[..., TestClient],
) -> None:
    response = make_client().get("/api/does-not-exist")

    assert response.status_code == 404
    _assert_security_headers(response)


def test_security_headers_on_405_response_present(
    make_client: Callable[..., TestClient],
) -> None:
    response = make_client().delete("/api/health")

    assert response.status_code == 405
    _assert_security_headers(response)


def test_security_headers_on_500_response_present(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    app = make_app()
    add_raising_route(app, "/api/test/boom", new_marker("boom"))

    response = make_client(app).get("/api/test/boom")

    assert response.status_code == 500
    _assert_security_headers(response)


def test_security_headers_on_cors_preflight_response_present(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client(allowed_origins=[ALLOWED_ORIGIN])

    response = client.options(
        "/api/health",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "GET",
        },
    )

    _assert_security_headers(response)
