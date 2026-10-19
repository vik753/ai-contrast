"""S1-T1b AC4: request validation errors return a safe 422 body (T1).

Body: ``{"error": "invalid_request", "fields": [<loc as list of strings>]}``.
No ``input``, ``ctx``, ``msg`` or ``url``; the canary never appears.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

import httpx
import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from tests.helpers import all_log_text, new_canary

VALIDATE_PATH = "/api/test/validate"
GOOD_KEY = "k" * 120


class _Payload(BaseModel):
    name: str = Field(max_length=5)
    items: list[int] = Field(default_factory=list)


def _validation_client(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> TestClient:
    app = make_app()

    async def _validate(
        payload: _Payload,
        x_provider_key: Annotated[str, Header(min_length=100)],
    ) -> dict[str, str]:
        return {"status": "ok"}

    app.add_api_route(VALIDATE_PATH, _validate, methods=["POST"])
    return make_client(app)


def _fields(response: httpx.Response) -> set[tuple[str, ...]]:
    return {tuple(loc) for loc in response.json()["fields"]}


def _assert_absent(response: httpx.Response, needle: str) -> None:
    assert needle not in response.text
    for name, value in response.headers.items():
        assert needle not in name
        assert needle not in value


def test_validation_control_valid_request_returns_200(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    client = _validation_client(make_app, make_client)

    response = client.post(VALIDATE_PATH, json={"name": "ok"}, headers={"X-Provider-Key": GOOD_KEY})

    assert response.status_code == 200


def test_validation_invalid_header_and_body_returns_422(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    canary = new_canary()
    client = _validation_client(make_app, make_client)

    response = client.post(VALIDATE_PATH, json={"name": canary}, headers={"X-Provider-Key": canary})

    assert response.status_code == 422


def test_validation_body_has_only_error_and_fields_keys(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    canary = new_canary()
    client = _validation_client(make_app, make_client)

    response = client.post(VALIDATE_PATH, json={"name": canary}, headers={"X-Provider-Key": canary})

    body = response.json()
    assert set(body) == {"error", "fields"}
    assert body["error"] == "invalid_request"


def test_validation_fields_are_lists_of_strings(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    canary = new_canary()
    client = _validation_client(make_app, make_client)

    response = client.post(VALIDATE_PATH, json={"name": canary}, headers={"X-Provider-Key": canary})

    fields = response.json()["fields"]
    assert isinstance(fields, list)
    assert fields
    for loc in fields:
        assert isinstance(loc, list)
        assert all(isinstance(part, str) for part in loc), loc


def test_validation_fields_name_header_and_body_locations(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    canary = new_canary()
    client = _validation_client(make_app, make_client)

    response = client.post(VALIDATE_PATH, json={"name": canary}, headers={"X-Provider-Key": canary})

    assert _fields(response) == {("header", "x-provider-key"), ("body", "name")}


def test_validation_list_index_in_loc_is_string(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    client = _validation_client(make_app, make_client)

    response = client.post(
        VALIDATE_PATH,
        json={"name": "ok", "items": [1, "not-an-int"]},
        headers={"X-Provider-Key": GOOD_KEY},
    )

    assert response.status_code == 422
    assert _fields(response) == {("body", "items", "1")}


def test_validation_missing_header_reports_location_only(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    client = _validation_client(make_app, make_client)

    response = client.post(VALIDATE_PATH, json={"name": "ok"})

    assert response.status_code == 422
    assert response.json() == {
        "error": "invalid_request",
        "fields": [["header", "x-provider-key"]],
    }


def test_validation_malformed_json_body_returns_safe_422(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    canary = new_canary()
    client = _validation_client(make_app, make_client)

    response = client.post(
        VALIDATE_PATH,
        content=f'{{"name": "{canary}"',  # truncated JSON
        headers={"Content-Type": "application/json", "X-Provider-Key": GOOD_KEY},
    )

    assert response.status_code == 422
    assert set(response.json()) == {"error", "fields"}
    _assert_absent(response, canary)


@pytest.mark.parametrize("forbidden", ["input", "ctx", "msg", "url", "detail"])
def test_validation_body_has_no_pydantic_detail_keys(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient], forbidden: str
) -> None:
    canary = new_canary()
    client = _validation_client(make_app, make_client)

    response = client.post(VALIDATE_PATH, json={"name": canary}, headers={"X-Provider-Key": canary})

    assert f'"{forbidden}"' not in response.text


def test_validation_canary_absent_from_response(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    canary = new_canary()
    client = _validation_client(make_app, make_client)

    response = client.post(VALIDATE_PATH, json={"name": canary}, headers={"X-Provider-Key": canary})

    _assert_absent(response, canary)


def test_validation_canary_absent_from_logs(
    make_app: Callable[..., FastAPI],
    make_client: Callable[..., TestClient],
    log_capture: pytest.LogCaptureFixture,
) -> None:
    canary = new_canary()
    client = _validation_client(make_app, make_client)
    log_capture.clear()

    client.post(VALIDATE_PATH, json={"name": canary}, headers={"X-Provider-Key": canary})

    assert canary not in all_log_text(log_capture)


def test_validation_422_has_security_headers(
    make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]
) -> None:
    client = _validation_client(make_app, make_client)

    response = client.post(VALIDATE_PATH, json={"name": "ok"})

    assert response.headers.get("cache-control") == "no-store"
    assert response.headers.get("x-content-type-options") == "nosniff"
