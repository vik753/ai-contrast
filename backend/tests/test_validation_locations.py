"""S1-T1c AC1: 422 locations never echo client-chosen keys (T1, T3).

Each location keeps its source (``body``, ``header``, ``query``, ``path``) and
only names declared by our code or list indexes. Other parts become ``"*"``;
for ``extra_forbidden`` the last part is dropped. At most 20 deduplicated
entries, then one ``"..."`` entry. Each part has at most 64 characters.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict, Field

from tests.helpers import all_log_text, new_canary

STRICT_PATH = "/api/test/strict"
PARAMS_PATH = "/api/test/params/{item_id}"
LONG_NAME = "declared_" + "n" * 80  # a declared alias longer than 64 characters
MAX_ENTRIES = 20
ELLIPSIS = "..."
SMALL_BODY_BYTES = 4096


class _Inner(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: int


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scores: dict[str, int]
    items: list[int]
    inner: _Inner | None = None


class _LongNamed(BaseModel):
    long_field: int = Field(alias=LONG_NAME)


@pytest.fixture
def client(make_app: Callable[..., FastAPI], make_client: Callable[..., TestClient]) -> TestClient:
    app = make_app()

    async def _strict(payload: _Strict) -> dict[str, str]:
        return {"status": "ok"}

    async def _params(item_id: int, limit: int) -> dict[str, str]:
        return {"status": "ok"}

    async def _long(payload: _LongNamed) -> dict[str, str]:
        return {"status": "ok"}

    app.add_api_route(STRICT_PATH, _strict, methods=["POST"])
    app.add_api_route(PARAMS_PATH, _params, methods=["GET"])
    app.add_api_route("/api/test/long", _long, methods=["POST"])
    return make_client(app)


def _post(client: TestClient, payload: dict[str, Any]) -> httpx.Response:
    return client.post(STRICT_PATH, json=payload)


def _valid(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"scores": {}, "items": []}
    payload.update(overrides)
    return payload


def _fields(response: httpx.Response) -> list[Any]:
    assert response.status_code == 422, response.text
    body = response.json()
    assert set(body) == {"error", "fields"}
    fields = body["fields"]
    assert isinstance(fields, list)
    return fields


def _is_ellipsis(entry: Any) -> bool:
    return entry in (ELLIPSIS, [ELLIPSIS])


def test_locations_control_valid_payload_returns_200(client: TestClient) -> None:
    assert _post(client, _valid()).status_code == 200


# --- client-chosen keys -----------------------------------------------------


def test_locations_unknown_top_level_key_canary_absent(client: TestClient) -> None:
    canary = new_canary()

    response = _post(client, _valid(**{canary: 1}))

    assert response.status_code == 422
    assert canary not in response.text


def test_locations_unknown_top_level_key_last_part_dropped(client: TestClient) -> None:
    response = _post(client, _valid(**{new_canary(): 1}))

    assert _fields(response) == [["body"]]


def test_locations_dict_key_canary_absent(client: TestClient) -> None:
    canary = new_canary()

    response = _post(client, _valid(scores={canary: "not-an-int"}))

    assert response.status_code == 422
    assert canary not in response.text


def test_locations_dict_key_replaced_with_star(client: TestClient) -> None:
    response = _post(client, _valid(scores={new_canary(): "not-an-int"}))

    assert _fields(response) == [["body", "scores", "*"]]


def test_locations_nested_unknown_key_canary_absent(client: TestClient) -> None:
    canary = new_canary()

    response = _post(client, _valid(inner={"value": 1, canary: 2}))

    assert response.status_code == 422
    assert canary not in response.text


def test_locations_nested_unknown_key_last_part_dropped(client: TestClient) -> None:
    response = _post(client, _valid(inner={"value": 1, new_canary(): 2}))

    assert _fields(response) == [["body", "inner"]]


def test_locations_many_unknown_keys_deduplicated(client: TestClient) -> None:
    payload = _valid(**{new_canary(): i for i in range(30)})

    assert _fields(_post(client, payload)) == [["body"]]


def test_locations_many_bad_dict_values_deduplicated(client: TestClient) -> None:
    payload = _valid(scores={new_canary(): "x" for _ in range(30)})

    assert _fields(_post(client, payload)) == [["body", "scores", "*"]]


def test_locations_client_keys_canary_absent_from_logs(
    client: TestClient, log_capture: pytest.LogCaptureFixture
) -> None:
    canary = new_canary()
    log_capture.clear()

    _post(client, _valid(scores={canary: "x"}, inner={"value": 1, canary: 2}, **{canary: 3}))

    assert canary not in all_log_text(log_capture)


# --- declared names and indexes stay visible --------------------------------


def test_locations_missing_declared_fields_visible(client: TestClient) -> None:
    fields = _fields(_post(client, {}))

    assert sorted(fields) == [["body", "items"], ["body", "scores"]]


def test_locations_list_index_visible_as_string(client: TestClient) -> None:
    fields = _fields(_post(client, _valid(items=[1, "x"])))

    assert fields == [["body", "items", "1"]]


def test_locations_nested_declared_field_visible(client: TestClient) -> None:
    fields = _fields(_post(client, _valid(inner={"value": "x"})))

    assert fields == [["body", "inner", "value"]]


def test_locations_path_and_query_params_visible(client: TestClient) -> None:
    response = client.get("/api/test/params/not-int", params={"limit": "x"})

    assert sorted(_fields(response)) == [["path", "item_id"], ["query", "limit"]]


def test_locations_unknown_query_param_ignored(client: TestClient) -> None:
    canary = new_canary()

    response = client.get("/api/test/params/1", params={"limit": "x", canary: "1"})

    assert _fields(response) == [["query", "limit"]]
    assert canary not in response.text


def test_locations_each_part_at_most_64_characters(client: TestClient) -> None:
    response = client.post("/api/test/long", json={})

    fields = _fields(response)
    assert fields
    for loc in fields:
        assert all(len(part) <= 64 for part in loc), loc


# --- size limits ------------------------------------------------------------


def test_locations_5000_invalid_items_at_most_21_entries(client: TestClient) -> None:
    fields = _fields(_post(client, _valid(items=["x"] * 5000)))

    assert len(fields) == MAX_ENTRIES + 1


def test_locations_5000_invalid_items_last_entry_is_ellipsis(client: TestClient) -> None:
    fields = _fields(_post(client, _valid(items=["x"] * 5000)))

    assert _is_ellipsis(fields[-1])
    assert not any(_is_ellipsis(entry) for entry in fields[:-1])


def test_locations_5000_invalid_items_first_entries_keep_indexes(client: TestClient) -> None:
    fields = _fields(_post(client, _valid(items=["x"] * 5000)))

    assert fields[:3] == [["body", "items", "0"], ["body", "items", "1"], ["body", "items", "2"]]


def test_locations_5000_invalid_items_small_body(client: TestClient) -> None:
    response = _post(client, _valid(items=["x"] * 5000))

    assert response.status_code == 422
    assert len(response.content) < SMALL_BODY_BYTES


def test_locations_exactly_20_errors_no_ellipsis(client: TestClient) -> None:
    fields = _fields(_post(client, _valid(items=["x"] * MAX_ENTRIES)))

    assert len(fields) == MAX_ENTRIES
    assert not any(_is_ellipsis(entry) for entry in fields)


def test_locations_21_errors_truncated_with_ellipsis(client: TestClient) -> None:
    fields = _fields(_post(client, _valid(items=["x"] * (MAX_ENTRIES + 1))))

    assert len(fields) == MAX_ENTRIES + 1
    assert _is_ellipsis(fields[-1])
