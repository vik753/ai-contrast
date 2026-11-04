"""S6-T4 AC1: request body, key header rules, answer shape (ADR 0016 points 5 and 6)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from tests.ai.helpers import BODY_CANARY, REQUEST_ID_CANARY, error_reply, model_reply
from tests.check.helpers import (
    CHECK,
    KEY_HEADER,
    PUBLIC_IP,
    Rig,
    valid_body,
)


def test_check_valid_request_returns_only_ok_true() -> None:
    rig = Rig()
    response = rig.check()
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_check_sends_the_key_to_the_provider_and_the_model_in_the_body() -> None:
    rig = Rig()
    rig.check()
    assert len(rig.upstream.seen) == 1
    seen = rig.upstream.seen[0]
    assert seen.host == "api.openai.com"
    assert json.loads(seen.body)["model"] == "gpt-test-1"
    assert "gpt-test-1" not in seen.url


def test_check_oversized_body_returns_413_before_parsing() -> None:
    rig = Rig()
    body = json.dumps({**valid_body(), "model": "a" * 4200})
    response = rig.client().post(
        CHECK, content=body, headers={**KEY_HEADER, "Content-Type": "application/json"}
    )
    assert response.status_code == 413
    assert response.json() == {"error": "request_too_large"}
    assert rig.upstream.seen == []


def test_check_body_of_exactly_4096_bytes_is_not_refused_for_size() -> None:
    rig = Rig()
    base = json.dumps({"provider": "openai", "model": "m", "base_url": None})
    pad = 4096 - len(base.encode())
    raw = json.dumps({"provider": "openai", "model": "m" + "a" * pad}, separators=(",", ":"))
    raw = raw + " " * (4096 - len(raw.encode()))
    assert len(raw.encode()) == 4096
    response = rig.client().post(
        CHECK, content=raw, headers={**KEY_HEADER, "Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_model"}


@pytest.mark.parametrize(
    "body",
    [
        {**valid_body(), "extra": 1},
        {**valid_body(), "api_key": "sk-x"},
        {"provider": 5, "model": "m"},
        {"provider": "openai", "model": ["m"]},
        [],
    ],
)
def test_check_unknown_field_or_wrong_type_returns_invalid_request(body: Any) -> None:
    rig = Rig()
    response = rig.check(body, headers=KEY_HEADER)
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_request"}
    assert rig.upstream.seen == []


def test_check_not_json_returns_invalid_request() -> None:
    rig = Rig()
    response = rig.client().post(
        CHECK, content=b"{nope", headers={**KEY_HEADER, "Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_request"}


def test_check_unknown_provider_returns_invalid_provider() -> None:
    rig = Rig()
    response = rig.check({"provider": "nope", "model": "m"}, headers=KEY_HEADER)
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_provider"}


@pytest.mark.parametrize("model", [None, "", "-bad", "a b", "a" * 129, "m\n", "m?x=1", "ü"])
def test_check_bad_model_returns_invalid_model(model: str | None) -> None:
    rig = Rig()
    body: dict[str, Any] = {"provider": "openai"}
    if model is not None:
        body["model"] = model
    response = rig.check(body, headers=KEY_HEADER)
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_model"}
    assert rig.upstream.seen == []


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini", "mistral", "openrouter"])
def test_check_base_url_for_non_custom_returns_unexpected_base_url(provider: str) -> None:
    rig = Rig()
    body = {"provider": provider, "model": "m1", "base_url": "https://example.com/v1"}
    response = rig.check(body, headers=KEY_HEADER)
    assert response.status_code == 422
    assert response.json() == {"error": "unexpected_base_url"}


def test_check_turnstile_token_for_non_free_returns_unexpected_turnstile_token() -> None:
    rig = Rig()
    body = {**valid_body(), "turnstile_token": "t"}
    response = rig.check(body, headers=KEY_HEADER)
    assert response.status_code == 422
    assert response.json() == {"error": "unexpected_turnstile_token"}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Provider-Key": ""},
        {"X-Provider-Key": "a" * 513},
        {"X-Provider-Key": "key with\ttab"},
    ],
)
def test_check_missing_or_bad_key_returns_invalid_provider_key(headers: dict[str, str]) -> None:
    rig = Rig()
    response = rig.check(valid_body(), headers=headers)
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_provider_key"}
    assert rig.upstream.seen == []


def test_check_non_ascii_key_returns_invalid_provider_key() -> None:
    rig = Rig()
    response = rig.client().post(
        CHECK,
        json=valid_body(),
        headers=[("X-Provider-Key", "sk-é".encode("latin-1"))],  # type: ignore[list-item]
    )
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_provider_key"}


@pytest.mark.parametrize("length", [1, 512])
def test_check_key_of_allowed_length_is_accepted(length: int) -> None:
    rig = Rig()
    response = rig.check(valid_body(), headers={"X-Provider-Key": "k" * length})
    assert response.status_code == 200


def test_check_key_in_query_string_is_ignored_and_header_still_required() -> None:
    rig = Rig()
    response = rig.client().post(CHECK + "?x_provider_key=abc", json=valid_body())
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_provider_key"}


def test_check_custom_without_key_returns_invalid_provider_key() -> None:
    rig = Rig()
    body = {"provider": "custom", "model": "m", "base_url": "https://llm.example.com/v1"}
    response = rig.check(body, headers={})
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_provider_key"}


def test_check_get_method_is_not_allowed() -> None:
    rig = Rig()
    assert rig.client().get(CHECK).status_code == 405


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (401, "provider_auth_failed"),
        (404, "provider_model_not_found"),
        (429, "provider_rate_limited"),
        (400, "provider_bad_request"),
        (503, "provider_unavailable"),
    ],
)
def test_check_provider_failure_returns_only_the_error_code(code: int, status: str) -> None:
    rig = Rig()
    rig.upstream.reply = error_reply(code, {"x-secret-header": REQUEST_ID_CANARY})
    response = rig.check()
    assert response.status_code >= 400
    assert response.json() == {"error": status}
    assert BODY_CANARY not in response.text
    assert REQUEST_ID_CANARY not in response.text
    assert "x-secret-header" not in {k.lower() for k in response.headers}


def test_check_provider_status_map_is_fixed() -> None:
    expected = {401: 401, 404: 404, 429: 429, 400: 400}
    for upstream, ours in expected.items():
        rig = Rig()
        rig.upstream.reply = error_reply(upstream)
        assert rig.check().status_code == ours


def test_check_response_never_carries_model_text() -> None:
    rig = Rig()
    rig.upstream.reply = model_reply("MODEL-TEXT-CANARY-5521")
    response = rig.check()
    assert "MODEL-TEXT-CANARY-5521" not in response.text
    assert set(response.json()) <= {"ok", "error"}
    assert PUBLIC_IP not in response.text
