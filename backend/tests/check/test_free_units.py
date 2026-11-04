"""S6-T4 units: FreeQuota (app.limits.free) and Turnstile verify (app.net.turnstile)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime

import httpx2
import pytest
from pydantic import SecretStr

from app.limits.free import FreeQuota
from app.net.turnstile import TurnstileError, TurnstileVerdict, verify
from tests.ai.helpers import FakeUpstream
from tests.check.helpers import DAY, DEFAULT_TOKEN, NOW, TS_SECRET, Clock

MIDNIGHT = (NOW // DAY + 1) * DAY


def quota(
    calls: int = 2, budget: int = 100, max_keys: int = 100, clock: Clock | None = None
) -> FreeQuota:
    return FreeQuota(
        calls_per_ip=calls, neuron_budget=budget, max_keys=max_keys, clock=clock or Clock()
    )


def test_quota_allows_calls_up_to_the_per_ip_limit() -> None:
    q = quota(calls=2)
    assert q.reserve("a", 1).allowed
    assert q.reserve("a", 1).allowed
    d = q.reserve("a", 1)
    assert not d.allowed
    assert d.reason == "ip"
    assert d.retry_after == int(MIDNIGHT - NOW)


def test_quota_budget_refusal_counts_no_per_ip_call() -> None:
    q = quota(calls=1, budget=10)
    d = q.reserve("a", 11)
    assert not d.allowed
    assert d.reason == "budget"
    assert q.reserve("a", 10).allowed


def test_quota_budget_is_global_across_keys() -> None:
    q = quota(calls=5, budget=10)
    assert q.reserve("a", 6).allowed
    d = q.reserve("b", 6)
    assert not d.allowed
    assert d.reason == "budget"
    assert q.remaining_neurons == 4


def test_quota_settle_returns_unused_neurons() -> None:
    q = quota(budget=10)
    q.reserve("a", 8)
    q.settle(8, 3)
    assert q.remaining_neurons == 7


def test_quota_settle_charges_extra_usage_but_never_goes_below_zero() -> None:
    q = quota(budget=10)
    q.reserve("a", 5)
    q.settle(5, 50)
    assert q.remaining_neurons == 0
    q2 = quota(budget=10)
    q2.reserve("a", 5)
    q2.settle(5, 0)
    assert q2.remaining_neurons == 10


def test_quota_resets_at_midnight_utc() -> None:
    clock = Clock()
    q = quota(calls=1, budget=10, clock=clock)
    q.reserve("a", 10)
    clock.now = MIDNIGHT - 1
    assert not q.reserve("a", 1).allowed
    clock.now = MIDNIGHT
    assert q.reserve("a", 10).allowed
    assert q.remaining_neurons == 0


def test_quota_full_table_refuses_new_keys_fail_closed() -> None:
    q = quota(calls=5, max_keys=2)
    assert q.reserve("a", 1).allowed
    assert q.reserve("b", 1).allowed
    d = q.reserve("c", 1)
    assert not d.allowed
    assert d.reason == "table"
    assert d.retry_after >= 1
    assert q.reserve("a", 1).allowed


def test_quota_full_table_gives_back_the_budget_of_a_refused_key() -> None:
    q = quota(calls=5, budget=10, max_keys=1)
    q.reserve("a", 1)
    q.reserve("b", 5)
    assert q.remaining_neurons == 9


@pytest.mark.parametrize("neurons", [0, -1])
def test_quota_rejects_non_positive_reservations(neurons: int) -> None:
    with pytest.raises(ValueError, match=r"."):
        quota().reserve("a", neurons)


@pytest.mark.parametrize("bad", [{"calls": 0}, {"budget": 0}, {"max_keys": 0}])
def test_quota_rejects_non_positive_settings(bad: dict[str, int]) -> None:
    with pytest.raises(ValueError, match=r"."):
        quota(**bad)


# --- Turnstile verify -----------------------------------------------------------------------


def _reply(body: object, status: int = 200) -> Callable[[httpx2.Request], httpx2.Response]:
    def reply(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json=body)

    return reply


def run_verify(transport: FakeUpstream, token: str = DEFAULT_TOKEN) -> TurnstileVerdict:
    return asyncio.run(verify(token, SecretStr(TS_SECRET), transport=transport))


def test_verify_returns_the_fields_the_endpoint_checks() -> None:
    ts = datetime.fromtimestamp(NOW - 10, UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    t = FakeUpstream(
        _reply({"success": True, "hostname": "h.example", "action": "check", "challenge_ts": ts})
    )
    verdict = run_verify(t)
    assert verdict.success is True
    assert verdict.hostname == "h.example"
    assert verdict.action == "check"
    assert verdict.challenge_ts == pytest.approx(NOW - 10)


def test_verify_failed_answer_has_success_false() -> None:
    t = FakeUpstream(_reply({"success": False, "error-codes": ["timeout-or-duplicate"]}))
    assert run_verify(t).success is False


def test_verify_posts_secret_and_token_in_the_body_only() -> None:
    t = FakeUpstream(_reply({"success": True}))
    run_verify(t, "tok-1")
    seen = t.seen[0]
    assert (seen.method, seen.host, seen.path) == (
        "POST",
        "challenges.cloudflare.com",
        "/turnstile/v0/siteverify",
    )
    assert TS_SECRET in seen.body.decode()
    assert "tok-1" in seen.body.decode()
    assert "remoteip" not in seen.body.decode()
    assert TS_SECRET not in seen.url
    assert all(TS_SECRET not in v for v in seen.headers.values())


def test_verify_uses_a_timeout_of_at_most_10_seconds() -> None:
    t = FakeUpstream(_reply({"success": True}))
    run_verify(t)
    values = [v for v in t.seen[0].timeout.values() if v is not None]
    assert values
    assert max(values) <= 10


@pytest.mark.parametrize(
    "transport",
    [
        FakeUpstream(_reply({"success": True}, 500)),
        FakeUpstream(lambda r: httpx2.Response(200, content=b"nope")),
        FakeUpstream(_reply([1])),
        FakeUpstream(_reply({"success": "yes"})),
        FakeUpstream(
            lambda r: httpx2.Response(200, content=b'{"success":true,"x":"' + b"a" * 70000 + b'"}')
        ),
        FakeUpstream(lambda r: httpx2.Response(302, headers={"location": "https://evil.example"})),
    ],
)
def test_verify_bad_answer_raises_turnstile_error(transport: FakeUpstream) -> None:
    with pytest.raises(TurnstileError):
        run_verify(transport)


def test_verify_transport_error_raises_turnstile_error_without_the_secret() -> None:
    def boom(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow " + TS_SECRET)

    with pytest.raises(TurnstileError) as info:
        run_verify(FakeUpstream(boom))
    assert TS_SECRET not in str(info.value)
    assert TS_SECRET not in repr(info.value)
    assert json.dumps(str(info.value)).count(TS_SECRET) == 0
