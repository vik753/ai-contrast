"""AC3: CORS allows only configured origins, GET/POST, Content-Type and
X-Provider-Key (T6)."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.helpers import ALLOWED_ORIGIN, OTHER_ORIGIN

SECOND_ALLOWED_ORIGIN = "https://second.example"


def _client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client(allowed_origins=[ALLOWED_ORIGIN, SECOND_ALLOWED_ORIGIN])


def _preflight(
    client: TestClient,
    *,
    origin: str = ALLOWED_ORIGIN,
    method: str = "POST",
    request_headers: str | None = None,
) -> httpx.Response:
    headers = {"Origin": origin, "Access-Control-Request-Method": method}
    if request_headers is not None:
        headers["Access-Control-Request-Headers"] = request_headers
    return client.options("/api/health", headers=headers)


def _tokens(header_value: str | None) -> set[str]:
    if not header_value:
        return set()
    return {part.strip().lower() for part in header_value.split(",") if part.strip()}


def test_cors_allowed_origin_get_returns_matching_allow_origin(
    make_client: Callable[..., TestClient],
) -> None:
    response = _client(make_client).get("/api/health", headers={"Origin": ALLOWED_ORIGIN})

    assert response.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN


def test_cors_second_allowed_origin_get_returns_matching_allow_origin(
    make_client: Callable[..., TestClient],
) -> None:
    response = _client(make_client).get("/api/health", headers={"Origin": SECOND_ALLOWED_ORIGIN})

    assert response.headers.get("access-control-allow-origin") == SECOND_ALLOWED_ORIGIN


def test_cors_other_origin_get_returns_no_allow_origin(
    make_client: Callable[..., TestClient],
) -> None:
    response = _client(make_client).get("/api/health", headers={"Origin": OTHER_ORIGIN})

    assert "access-control-allow-origin" not in response.headers


def test_cors_default_settings_other_origin_returns_no_allow_origin(
    make_client: Callable[..., TestClient],
) -> None:
    response = make_client().get("/api/health", headers={"Origin": OTHER_ORIGIN})

    assert "access-control-allow-origin" not in response.headers


def test_cors_default_settings_localhost_dev_origin_returns_allow_origin(
    make_client: Callable[..., TestClient],
) -> None:
    origin = "http://localhost:5173"

    response = make_client().get("/api/health", headers={"Origin": origin})

    assert response.headers.get("access-control-allow-origin") == origin


def test_cors_origin_matching_is_exact_prefix_match_rejected(
    make_client: Callable[..., TestClient],
) -> None:
    response = _client(make_client).get(
        "/api/health", headers={"Origin": ALLOWED_ORIGIN + ".evil.example"}
    )

    assert "access-control-allow-origin" not in response.headers


def test_cors_allow_origin_never_wildcard(
    make_client: Callable[..., TestClient],
) -> None:
    client = _client(make_client)

    for origin in (ALLOWED_ORIGIN, OTHER_ORIGIN, "null"):
        response = client.get("/api/health", headers={"Origin": origin})
        assert response.headers.get("access-control-allow-origin") != "*"


def test_cors_preflight_allowed_origin_post_returns_2xx_and_allow_origin(
    make_client: Callable[..., TestClient],
) -> None:
    response = _preflight(_client(make_client), method="POST")

    assert 200 <= response.status_code < 300
    assert response.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN


def test_cors_preflight_allowed_origin_allows_get_and_post(
    make_client: Callable[..., TestClient],
) -> None:
    response = _preflight(_client(make_client), method="GET")

    assert {"get", "post"} <= _tokens(response.headers.get("access-control-allow-methods"))


def test_cors_preflight_allowed_methods_exclude_others(
    make_client: Callable[..., TestClient],
) -> None:
    response = _preflight(_client(make_client), method="POST")

    methods = _tokens(response.headers.get("access-control-allow-methods"))
    assert methods <= {"get", "post"}, methods


def test_cors_preflight_delete_method_not_allowed(
    make_client: Callable[..., TestClient],
) -> None:
    response = _preflight(_client(make_client), method="DELETE")

    methods = _tokens(response.headers.get("access-control-allow-methods"))
    assert "delete" not in methods
    assert "*" not in methods


def test_cors_preflight_put_method_not_allowed(
    make_client: Callable[..., TestClient],
) -> None:
    response = _preflight(_client(make_client), method="PUT")

    methods = _tokens(response.headers.get("access-control-allow-methods"))
    assert "put" not in methods
    assert "*" not in methods


def test_cors_preflight_content_type_and_provider_key_headers_allowed(
    make_client: Callable[..., TestClient],
) -> None:
    response = _preflight(
        _client(make_client),
        method="POST",
        request_headers="Content-Type, X-Provider-Key",
    )

    assert 200 <= response.status_code < 300
    allowed = _tokens(response.headers.get("access-control-allow-headers"))
    assert {"content-type", "x-provider-key"} <= allowed


def test_cors_preflight_unknown_request_header_not_allowed(
    make_client: Callable[..., TestClient],
) -> None:
    response = _preflight(_client(make_client), method="POST", request_headers="X-Something-Else")

    allowed = _tokens(response.headers.get("access-control-allow-headers"))
    assert "x-something-else" not in allowed
    assert "*" not in allowed


def test_cors_preflight_other_origin_returns_no_allow_origin(
    make_client: Callable[..., TestClient],
) -> None:
    response = _preflight(_client(make_client), origin=OTHER_ORIGIN, method="POST")

    assert "access-control-allow-origin" not in response.headers


def test_cors_allowed_origins_from_env_applied_to_app(
    make_client: Callable[..., TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", f" {ALLOWED_ORIGIN} , {SECOND_ALLOWED_ORIGIN}")

    response = make_client().get("/api/health", headers={"Origin": SECOND_ALLOWED_ORIGIN})

    assert response.headers.get("access-control-allow-origin") == SECOND_ALLOWED_ORIGIN
