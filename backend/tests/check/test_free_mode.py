"""S6-T4 AC2, AC3a, AC3b (free mode): availability, Turnstile, quotas, free URL and token."""

from __future__ import annotations

import json

import httpx2
import pytest
from app.limits.free import CHECK_NEURONS
from pydantic import ValidationError

from app.settings import Settings
from tests.ai.helpers import error_reply, model_reply
from tests.check.helpers import (
    ACCOUNT,
    ACTION,
    CF_TOKEN,
    CLIENT_KEY,
    DAY,
    FREE_ENV,
    FREE_MODEL,
    HOSTNAME,
    KEY_HEADER,
    TS_SECRET,
    Rig,
    free_rig,
    siteverify_reply,
)

IP_A = "198.51.100.1"
IP_B = "198.51.100.2"


# --- availability (AC2) ---------------------------------------------------------------------


def test_free_without_any_secret_returns_503_free_mode_unavailable() -> None:
    rig = Rig()
    response = rig.free()
    assert response.status_code == 503
    assert response.json() == {"error": "free_mode_unavailable"}
    assert rig.upstream.seen == []
    assert rig.turnstile.seen == []


@pytest.mark.parametrize("missing", ["cf_account_id", "cf_ai_token", "turnstile_secret_key"])
def test_free_with_one_secret_missing_returns_503_free_mode_unavailable(missing: str) -> None:
    rig = Rig(**{k: v for k, v in FREE_ENV.items() if k != missing})
    response = rig.free()
    assert response.status_code == 503
    assert response.json() == {"error": "free_mode_unavailable"}
    assert rig.upstream.seen == []
    assert rig.turnstile.seen == []


def test_free_with_client_key_returns_unexpected_provider_key_even_when_unconfigured() -> None:
    rig = Rig()
    response = rig.check({"provider": "free"}, headers=KEY_HEADER)
    assert response.status_code == 422
    assert response.json() == {"error": "unexpected_provider_key"}


def test_free_with_client_key_is_never_sent_anywhere() -> None:
    rig = free_rig()
    response = rig.check({"provider": "free", "turnstile_token": "t"}, headers=KEY_HEADER)
    assert response.status_code == 422
    assert response.json() == {"error": "unexpected_provider_key"}
    assert rig.upstream.seen == []
    assert rig.turnstile.seen == []


def test_free_token_longer_than_2048_returns_invalid_request() -> None:
    rig = free_rig()
    response = rig.free("t" * 2049)
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_request"}
    assert rig.turnstile.seen == []


@pytest.mark.parametrize(
    "account",
    [
        "0123456789ABCDEF0123456789abcdef",
        "0123456789abcdef0123456789abcde",
        ACCOUNT + "0",
        "0123456789abcdef0123456789abcdeg",
        "../" + ACCOUNT,
        ACCOUNT + "/x",
        "",
    ],
)
def test_free_account_id_not_32_lower_hex_is_refused_at_startup(account: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**{**FREE_ENV, "cf_account_id": account})


def test_free_secrets_are_not_visible_in_settings_repr() -> None:
    text = repr(Settings(**FREE_ENV)) + str(Settings(**FREE_ENV).model_dump())
    assert CF_TOKEN not in text
    assert TS_SECRET not in text


@pytest.mark.parametrize("budget", [0, 10000, 50000, -1])
def test_free_neuron_budget_outside_1_to_9999_is_refused_at_startup(budget: int) -> None:
    with pytest.raises(ValidationError):
        Settings(free_neuron_budget=budget)


def test_free_defaults_match_the_adr() -> None:
    s = Settings()
    assert s.check_per_minute == 10
    assert s.check_per_day == 60
    assert s.free_calls_per_ip_per_day == 5
    assert s.free_neuron_budget == 8000
    assert s.max_concurrent_checks == 2
    assert s.turnstile_replay_max_entries == 10000
    assert s.cf_account_id is None
    assert s.cf_ai_token is None
    assert s.turnstile_secret_key is None


# --- the provider call (AC2, AC3b) ----------------------------------------------------------


def test_free_success_calls_cloudflare_with_our_token_and_the_fixed_model() -> None:
    rig = free_rig()
    response = rig.free()
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert len(rig.upstream.seen) == 1
    seen = rig.upstream.seen[0]
    assert seen.host == "api.cloudflare.com"
    assert seen.path.startswith(f"/client/v4/accounts/{ACCOUNT}/ai/v1/")
    assert seen.headers["authorization"] == f"Bearer {CF_TOKEN}"
    assert json.loads(seen.body)["model"] == FREE_MODEL
    assert CF_TOKEN not in seen.url + seen.body.decode()


def test_free_ignores_a_model_given_by_the_client() -> None:
    rig = free_rig()
    response = rig.check({"provider": "free", "model": "evil-model", "turnstile_token": "t"})
    assert response.status_code == 200
    assert json.loads(rig.upstream.seen[0].body)["model"] == FREE_MODEL


def test_free_base_url_from_the_client_is_refused() -> None:
    rig = free_rig()
    body = {"provider": "free", "turnstile_token": "t", "base_url": "https://evil.example/v1"}
    response = rig.check(body)
    assert response.status_code == 422
    assert response.json() == {"error": "unexpected_base_url"}
    assert rig.upstream.seen == []


@pytest.mark.parametrize(
    "body",
    [
        {"provider": "custom", "model": "m", "base_url": "https://llm.example.com/v1"},
        {"provider": "openai", "model": "m"},
        {"provider": "anthropic", "model": "m"},
    ],
)
def test_cloudflare_token_is_never_sent_to_a_client_chosen_provider(body: dict[str, str]) -> None:
    rig = free_rig()
    rig.check(body, headers=KEY_HEADER)
    for seen in rig.upstream.seen:
        assert CF_TOKEN not in seen.everything
        assert TS_SECRET not in seen.everything
        assert seen.headers.get("authorization", "") != f"Bearer {CF_TOKEN}"
    assert rig.turnstile.seen == []


# --- Turnstile (AC2, T10) -------------------------------------------------------------------


def test_turnstile_call_goes_to_the_constant_url_with_the_secret_only_in_the_body() -> None:
    rig = free_rig()
    rig.free("tok-xyz", ip=IP_A)
    assert len(rig.turnstile.seen) == 1
    seen = rig.turnstile.seen[0]
    assert seen.method == "POST"
    assert seen.host == "challenges.cloudflare.com"
    assert seen.path == "/turnstile/v0/siteverify"
    assert "?" not in seen.url
    body = seen.body.decode()
    assert TS_SECRET in body
    assert "tok-xyz" in body
    assert TS_SECRET not in seen.url
    assert all(TS_SECRET not in v for v in seen.headers.values())
    assert "remoteip" not in body


def test_turnstile_call_carries_no_client_ip_and_no_client_headers() -> None:
    rig = free_rig(trusted_proxy_hops=1)
    rig.client(IP_A).post(
        "/api/provider/check",
        json={"provider": "free", "turnstile_token": "t"},
        headers={"X-Forwarded-For": "203.0.113.77", "Origin": "https://app.example"},
    )
    seen = rig.turnstile.seen[0]
    assert IP_A not in seen.everything
    assert "203.0.113.77" not in seen.everything
    assert "x-forwarded-for" not in seen.headers
    assert "origin" not in seen.headers


def test_turnstile_missing_token_returns_403_turnstile_failed() -> None:
    rig = free_rig()
    response = rig.free(None)
    assert response.status_code == 403
    assert response.json() == {"error": "turnstile_failed"}
    assert rig.upstream.seen == []


def test_turnstile_success_false_returns_403_and_no_provider_call() -> None:
    rig = free_rig()
    rig.turnstile.reply = siteverify_reply(success=False)
    response = rig.free()
    assert response.status_code == 403
    assert response.json() == {"error": "turnstile_failed"}
    assert rig.upstream.seen == []


def test_turnstile_wrong_hostname_returns_403() -> None:
    rig = free_rig()
    rig.turnstile.reply = siteverify_reply(hostname="evil.example")
    assert rig.free().status_code == 403
    assert rig.upstream.seen == []


def test_turnstile_hostname_is_not_compared_when_not_configured() -> None:
    rig = Rig(**{k: v for k, v in FREE_ENV.items() if k != "turnstile_expected_hostname"})
    rig.turnstile.reply = siteverify_reply(hostname="anything.example")
    assert rig.free().status_code == 200


def test_turnstile_wrong_action_returns_403() -> None:
    rig = free_rig()
    rig.turnstile.reply = siteverify_reply(action="login")
    assert rig.free().status_code == 403
    assert rig.upstream.seen == []


def test_turnstile_challenge_300_seconds_old_is_accepted() -> None:
    rig = free_rig()
    rig.turnstile.reply = siteverify_reply(age=300, clock=rig.clock)
    assert rig.free().status_code == 200


def test_turnstile_challenge_older_than_300_seconds_returns_403() -> None:
    rig = free_rig()
    rig.turnstile.reply = siteverify_reply(age=301, clock=rig.clock)
    assert rig.free().status_code == 403
    assert rig.upstream.seen == []


def test_turnstile_challenge_from_the_future_returns_403() -> None:
    rig = free_rig()
    rig.turnstile.reply = siteverify_reply(age=-3600, clock=rig.clock)
    assert rig.free().status_code == 403


@pytest.mark.parametrize(
    "reply",
    [
        lambda r: httpx2.Response(200, json={"success": True}),
        lambda r: httpx2.Response(
            200,
            json={
                "success": True,
                "hostname": HOSTNAME,
                "action": ACTION,
                "challenge_ts": "yesterday",
            },
        ),
        lambda r: httpx2.Response(200, content=b"not json"),
        lambda r: httpx2.Response(200, json=["success"]),
        lambda r: httpx2.Response(500, json={"success": True}),
        lambda r: httpx2.Response(302, headers={"location": "https://evil.example/"}),
        lambda r: httpx2.Response(
            200, content=b'{"success": true, "pad": "' + b"a" * 70000 + b'"}'
        ),
    ],
)
def test_turnstile_bad_siteverify_answer_returns_403(reply: object) -> None:
    rig = free_rig()
    rig.turnstile.reply = reply  # type: ignore[assignment]
    response = rig.free()
    assert response.status_code == 403
    assert response.json() == {"error": "turnstile_failed"}
    assert rig.upstream.seen == []


def test_turnstile_network_error_returns_403_without_details() -> None:
    def boom(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("dns failure for challenges.cloudflare.com " + TS_SECRET)

    rig = free_rig()
    rig.turnstile.reply = boom
    response = rig.free()
    assert response.status_code == 403
    assert response.json() == {"error": "turnstile_failed"}
    assert TS_SECRET not in response.text


def test_turnstile_replayed_token_returns_403_even_if_siteverify_says_success() -> None:
    rig = free_rig()
    assert rig.free("same-token").status_code == 200
    again = rig.free("same-token")
    assert again.status_code == 403
    assert again.json() == {"error": "turnstile_failed"}
    assert len(rig.upstream.seen) == 1


def test_turnstile_replayed_token_from_another_ip_is_refused() -> None:
    rig = free_rig()
    assert rig.free("same-token", ip=IP_A).status_code == 200
    assert rig.free("same-token", ip=IP_B).status_code == 403


def test_turnstile_different_tokens_are_each_accepted_once() -> None:
    rig = free_rig()
    assert rig.free("t1").status_code == 200
    assert rig.free("t2").status_code == 200


def test_turnstile_token_is_remembered_for_10_minutes() -> None:
    rig = free_rig(free_calls_per_ip_per_day=100)
    assert rig.free("same").status_code == 200
    rig.clock.now += 599
    rig.turnstile.reply = siteverify_reply(clock=rig.clock)
    assert rig.free("same").status_code == 403
    rig.clock.now += 2
    rig.turnstile.reply = siteverify_reply(clock=rig.clock)
    assert rig.free("same").status_code == 200


def test_turnstile_refused_token_is_not_stored_in_the_replay_table() -> None:
    rig = free_rig()
    rig.turnstile.reply = siteverify_reply(success=False)
    assert rig.free("t").status_code == 403
    rig.turnstile.reply = siteverify_reply(clock=rig.clock)
    assert rig.free("t").status_code == 200


def test_turnstile_full_replay_table_fails_closed() -> None:
    rig = free_rig(turnstile_replay_max_entries=3, free_calls_per_ip_per_day=100)
    for n in range(3):
        assert rig.free(f"fill-{n}").status_code == 200
    response = rig.free("brand-new")
    assert response.status_code == 403
    assert response.json() == {"error": "turnstile_failed"}
    assert len(rig.upstream.seen) == 3


def test_turnstile_full_table_recovers_when_entries_expire() -> None:
    rig = free_rig(turnstile_replay_max_entries=2, free_calls_per_ip_per_day=100)
    rig.free("a")
    rig.free("b")
    assert rig.free("c").status_code == 403
    rig.clock.now += 601
    rig.turnstile.reply = siteverify_reply(clock=rig.clock)
    assert rig.free("c").status_code == 200


# --- quotas (AC2, AC3a) ---------------------------------------------------------------------


def test_free_sixth_call_of_the_day_from_one_ip_returns_429_free_quota_exhausted() -> None:
    rig = free_rig(check_per_minute=1000, check_per_day=1000)
    for n in range(5):
        assert rig.free(f"t{n}", ip=IP_A).status_code == 200
    response = rig.free("t5", ip=IP_A)
    assert response.status_code == 429
    assert response.json() == {"error": "free_quota_exhausted"}
    assert int(response.headers["retry-after"]) == 12 * 3600
    assert len(rig.upstream.seen) == 5


def test_free_quota_is_per_ip() -> None:
    rig = free_rig(free_calls_per_ip_per_day=1)
    assert rig.free("a", ip=IP_A).status_code == 200
    assert rig.free("b", ip=IP_A).status_code == 429
    assert rig.free("c", ip=IP_B).status_code == 200


def test_free_quota_resets_at_midnight_utc() -> None:
    rig = free_rig(free_calls_per_ip_per_day=1)
    assert rig.free("a").status_code == 200
    midnight = (rig.clock.now // DAY + 1) * DAY
    rig.clock.now = midnight - 1
    rig.turnstile.reply = siteverify_reply(clock=rig.clock)
    assert rig.free("b").status_code == 429
    rig.clock.now = midnight
    rig.turnstile.reply = siteverify_reply(clock=rig.clock)
    assert rig.free("c").status_code == 200


def test_free_failed_turnstile_does_not_use_the_daily_free_call() -> None:
    rig = free_rig(free_calls_per_ip_per_day=1)
    rig.turnstile.reply = siteverify_reply(success=False)
    for n in range(5):
        assert rig.free(f"bad{n}").status_code == 403
    rig.turnstile.reply = siteverify_reply(clock=rig.clock)
    assert rig.free("good").status_code == 200


def test_free_provider_failure_still_uses_the_daily_free_call() -> None:
    rig = free_rig(free_calls_per_ip_per_day=1)
    rig.upstream.reply = error_reply(500)
    rig.free("a")
    rig.upstream.reply = model_reply()
    assert rig.free("b").status_code == 429


def test_free_ipv6_rotation_inside_one_slash_48_shares_the_daily_free_quota() -> None:
    rig = free_rig(free_calls_per_ip_per_day=2, check_per_minute=1000)
    assert rig.free("a", ip="2001:db8:5:1::1").status_code == 200
    assert rig.free("b", ip="2001:db8:5:2::1").status_code == 200
    response = rig.free("c", ip="2001:db8:5:3::1")
    assert response.status_code == 429
    assert response.json() == {"error": "free_quota_exhausted"}


def test_free_ipv6_other_slash_48_has_its_own_quota() -> None:
    rig = free_rig(free_calls_per_ip_per_day=1)
    assert rig.free("a", ip="2001:db8:5:1::1").status_code == 200
    assert rig.free("b", ip="2001:db8:6:1::1").status_code == 200


def test_free_budget_below_one_check_refuses_every_ip_with_429() -> None:
    rig = free_rig(free_neuron_budget=CHECK_NEURONS - 1)
    for n, ip in enumerate((IP_A, IP_B, "198.51.100.3")):
        response = rig.free(f"t{n}", ip=ip)
        assert response.status_code == 429
        assert response.json() == {"error": "free_quota_exhausted"}
        assert int(response.headers["retry-after"]) == 12 * 3600
    assert rig.upstream.seen == []


def test_free_budget_refusal_gives_back_the_check_and_free_hits() -> None:
    rig = free_rig(
        free_neuron_budget=CHECK_NEURONS - 1,
        check_per_minute=2,
        check_per_day=2,
        free_calls_per_ip_per_day=2,
    )
    for n in range(8):
        response = rig.free(f"t{n}", ip=IP_A)
        assert response.status_code == 429
        assert response.json() == {"error": "free_quota_exhausted"}


def test_free_non_free_providers_do_not_touch_the_free_budget() -> None:
    rig = free_rig(free_neuron_budget=CHECK_NEURONS - 1)
    assert rig.check(headers=KEY_HEADER, ip=IP_A).status_code == 200
    assert rig.check({"provider": "openai", "model": "m1"}, headers=KEY_HEADER).status_code == 200


def test_free_quota_refusal_does_not_leak_the_client_key_or_secrets() -> None:
    rig = free_rig(free_neuron_budget=1)
    response = rig.free()
    for secret in (CF_TOKEN, TS_SECRET, CLIENT_KEY):
        assert secret not in response.text
        assert secret not in str(dict(response.headers))
