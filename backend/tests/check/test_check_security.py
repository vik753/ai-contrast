"""S6-T4 AC3, AC3b, AC4: log canary on every path, SSRF refusal, private URL switch."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.settings import Settings
from tests.ai.helpers import error_reply, model_reply
from tests.canary.harness import find_leaks, tap_logs
from tests.check.helpers import (
    CF_TOKEN,
    CLIENT_KEY,
    FREE_ENV,
    KEY_HEADER,
    TS_SECRET,
    Rig,
    free_rig,
    siteverify_reply,
)
from tests.helpers import SETTINGS_ENV_VARS

SECRETS = (CF_TOKEN, TS_SECRET, CLIENT_KEY)
CUSTOM = {"provider": "custom", "model": "m1", "base_url": "https://llm.example.com/v1"}


def _everything(response: Any, tap: Any) -> str:
    return response.text + str(dict(response.headers)) + tap.text


def _paths(rig: Rig) -> list[Any]:
    """One call per path: success, validation errors, provider errors, Turnstile, quota, limit."""
    out: list[Any] = []
    out.append(rig.check(headers=KEY_HEADER))
    out.append(rig.check({"provider": "nope", "model": "m"}, headers=KEY_HEADER))
    out.append(rig.check({"provider": "openai", "model": "bad model"}, headers=KEY_HEADER))
    out.append(rig.check({"provider": "free"}, headers=KEY_HEADER))
    out.append(rig.check({"provider": "openai", "model": "m1", "extra": 1}, headers=KEY_HEADER))
    out.append(rig.check({"provider": "openai", "model": "m1"}, headers={"X-Provider-Key": "k\tk"}))
    out.append(
        rig.check(
            {"provider": "openai", "model": "m1", "base_url": "https://x.example"},
            headers=KEY_HEADER,
        )
    )
    out.append(rig.check(CUSTOM, headers=KEY_HEADER))
    out.append(rig.check({**CUSTOM, "base_url": "https://127.0.0.1/v1"}, headers=KEY_HEADER))
    for code in (401, 404, 429, 500):
        rig.upstream.reply = error_reply(code)
        out.append(rig.check(headers=KEY_HEADER))
    rig.upstream.reply = model_reply()
    out.append(rig.free("tok-a"))
    out.append(rig.free("tok-a"))  # replay
    rig.turnstile.reply = siteverify_reply(success=False)
    out.append(rig.free("tok-b"))
    rig.turnstile.reply = siteverify_reply(clock=rig.clock)
    for _ in range(12):
        out.append(rig.check(headers=KEY_HEADER))  # reaches the rate limit
    for n in range(8):
        out.append(rig.free(f"q{n}"))  # reaches the free quota
    return out


def test_canary_secrets_never_reach_logs_responses_or_headers_on_any_path() -> None:
    rig = free_rig()
    with tap_logs() as tap:
        responses = _paths(rig)
    assert len({r.status_code for r in responses}) >= 6
    for response in responses:
        assert find_leaks(SECRETS, _everything(response, tap)) == []
    assert find_leaks(SECRETS, tap.text) == []


def test_canary_unconfigured_free_mode_leaks_nothing() -> None:
    rig = Rig()
    with tap_logs() as tap:
        response = rig.check({"provider": "free", "turnstile_token": "t"}, headers=KEY_HEADER)
        response2 = rig.free("t")
    assert response.status_code == 422
    assert response2.status_code == 503
    assert find_leaks(SECRETS, _everything(response, tap) + _everything(response2, tap)) == []


def test_canary_unexpected_exception_in_the_provider_leaks_nothing() -> None:
    def boom(request: Any) -> Any:
        message = f"boom {CLIENT_KEY} {CF_TOKEN} {TS_SECRET}"
        raise RuntimeError(message)

    rig = free_rig()
    rig.upstream.reply = boom
    with tap_logs() as tap:
        r1 = rig.check(headers=KEY_HEADER)
        r2 = rig.free("t9")
    assert r1.status_code >= 400
    assert r2.status_code >= 400
    assert find_leaks(SECRETS, _everything(r1, tap) + _everything(r2, tap)) == []


def test_canary_client_key_appears_on_the_wire_only_in_the_auth_header() -> None:
    rig = free_rig()
    rig.check(headers=KEY_HEADER)
    for seen in rig.upstream.seen:
        assert CLIENT_KEY not in seen.without_auth()
    assert CLIENT_KEY not in "".join(s.everything for s in rig.turnstile.seen)


def test_canary_log_has_no_ip_address_and_no_body() -> None:
    rig = free_rig()
    with tap_logs() as tap:
        rig.check(headers=KEY_HEADER, ip="198.51.100.77")
        rig.free("tok-ip", ip="2001:db8:9:9::1")
    assert "198.51.100.77" not in tap.text
    assert "2001:db8:9" not in tap.text
    assert "tok-ip" not in tap.text
    assert "gpt-test-1" not in tap.text


# --- SSRF and private URLs (AC4, AC3b) ------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1",
        "https://127.0.0.1/v1",
        "https://[::1]/v1",
        "https://169.254.169.254/latest",
        "https://10.0.0.5/v1",
        "https://localhost/v1",
    ],
)
def test_custom_ip_literal_or_local_url_returns_a_refusal_without_any_network_call(
    url: str,
) -> None:
    rig = Rig()
    response = rig.check({**CUSTOM, "base_url": url}, headers=KEY_HEADER)
    assert response.status_code == 422
    assert response.json()["error"] in {"provider_blocked_host", "invalid_base_url"}
    assert rig.upstream.seen == []


def test_custom_https_127_0_0_1_returns_provider_blocked_host() -> None:
    rig = Rig()
    response = rig.check({**CUSTOM, "base_url": "https://127.0.0.1"}, headers=KEY_HEADER)
    assert response.status_code == 422
    assert response.json() == {"error": "provider_blocked_host"}
    assert rig.upstream.seen == []


@pytest.mark.parametrize(
    "url",
    [
        "http://llm.example.com/v1",
        "https://user:pw@llm.example.com/v1",
        "https://llm.example.com:8443/v1",
        "https://llm.example.com/v1?x=1",
        "https://llm.example.com/v1#f",
        "ftp://llm.example.com/v1",
        "https://llm.example.com/" + "a" * 300,
        "",
    ],
)
def test_custom_bad_base_url_returns_invalid_base_url(url: str) -> None:
    rig = Rig()
    response = rig.check({**CUSTOM, "base_url": url}, headers=KEY_HEADER)
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_base_url"}
    assert rig.upstream.seen == []


def test_custom_without_base_url_returns_invalid_base_url() -> None:
    rig = Rig()
    response = rig.check({"provider": "custom", "model": "m1"}, headers=KEY_HEADER)
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_base_url"}


def test_custom_valid_url_reaches_the_given_host_with_the_client_key() -> None:
    rig = Rig()
    response = rig.check(CUSTOM, headers=KEY_HEADER)
    assert response.status_code == 200
    seen = rig.upstream.seen[0]
    assert seen.host == "llm.example.com"
    assert seen.headers["authorization"] == f"Bearer {CLIENT_KEY}"


def test_private_urls_are_refused_by_default() -> None:
    assert Settings().allow_private_provider_urls is False


def test_private_urls_switch_is_refused_in_production() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            allowed_origins=["https://app.example"],
            allow_private_provider_urls=True,
        )


def test_private_urls_switch_is_allowed_in_development() -> None:
    assert Settings(allow_private_provider_urls=True).allow_private_provider_urls is True


def test_private_urls_switch_allows_http_and_private_hosts_for_custom() -> None:
    rig = Rig(allow_private_provider_urls=True)
    body = {**CUSTOM, "base_url": "http://127.0.0.1:11434/v1"}
    response = rig.check(body, headers=KEY_HEADER)
    assert response.status_code == 200
    assert rig.upstream.seen[0].host == "127.0.0.1"


def test_private_urls_switch_never_applies_to_the_free_url_or_other_presets() -> None:
    rig = free_rig(allow_private_provider_urls=True)
    rig.free()
    assert rig.upstream.seen[0].host == "api.cloudflare.com"
    response = rig.check(
        {"provider": "openai", "model": "m1", "base_url": "http://127.0.0.1/v1"}, headers=KEY_HEADER
    )
    assert response.json() == {"error": "unexpected_base_url"}


def test_free_env_names_are_cleaned_by_the_test_harness() -> None:
    for name in (
        "CF_ACCOUNT_ID",
        "CF_AI_TOKEN",
        "TURNSTILE_SECRET_KEY",
        "TURNSTILE_EXPECTED_HOSTNAME",
    ):
        assert name in SETTINGS_ENV_VARS
    assert FREE_ENV
