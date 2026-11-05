# ruff: noqa: S106
"""S7-T2 review round 1: Neuron reservation per job, one live pass per client, refund rules."""

from __future__ import annotations

import asyncio
import json
import math

import httpx2
import pytest

from app.limits.free import topic_neurons
from tests.ai.helpers import error_reply, model_reply
from tests.asgi_stream import chunks, drive, post_scope
from tests.check.helpers import FREE_ENV, GateTransport
from tests.topic_ai.helpers import (
    EXPAND,
    PROPOSE,
    SUGGEST,
    TRig,
    attr,
    attr_out,
    error_of,
    free_trig,
    gated_rig,
    suggest_body,
    suggest_out,
    syn_out,
    topic_body,
    usage_reply,
)

BIG = "The Insurer pays the claim in time. " * 833 + "x" * 12  # 30000 characters
FREE_ENV_BUDGET = 4700  # topic share 1410 Neurons
OUT = attr_out(attr())


def _free_suggest_body(token: str) -> dict[str, object]:
    body = suggest_body(BIG, BIG)
    return {
        "provider": "free",
        "turnstile_token": token,
        **{k: v for k, v in body.items() if k not in ("provider", "model")},
    }


# --- the estimate ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("chars", "max_tokens", "repair", "expected"),
    [
        (3000, 1000, False, 100),
        (3000, 1000, True, 200),
        (60000, 1200, False, 719),
        (60000, 1200, True, 1438),
        (0, 1, False, 1),
    ],
)
def test_topic_neurons_is_the_worst_case_cost_rounded_up_and_doubled_for_a_repair(
    chars: int, max_tokens: int, repair: bool, expected: int
) -> None:
    assert topic_neurons(chars, max_tokens, repair=repair) == expected


def test_topic_neurons_matches_the_formula_for_any_size() -> None:
    for chars, tokens in ((1, 1), (999, 800), (12345, 1500), (60000, 1200)):
        exact = (chars / 3 * 31818 + tokens * 68182) / 1_000_000
        assert topic_neurons(chars, tokens, repair=False) >= math.floor(exact)
        assert topic_neurons(chars, tokens, repair=False) <= math.ceil(exact) + 1


def test_a_suggest_at_the_input_cap_costs_more_than_a_propose() -> None:
    assert topic_neurons(60000, 1200, repair=True) > topic_neurons(400, 1500, repair=True)


# --- reservation at the endpoints -----------------------------------------------------------


def test_free_suggest_at_the_cap_is_refused_by_the_topic_share_before_the_call() -> None:
    rig = free_trig(suggest_out(("Roadside help", "Towing")), free_neuron_budget=FREE_ENV_BUDGET)
    r = rig.post(SUGGEST, _free_suggest_body("t1"), headers={})
    assert (r.status_code, error_of(r)) == (429, "free_quota_exhausted")
    assert rig.upstream.seen == []


def test_free_propose_fits_the_same_budget_where_the_big_suggest_did_not() -> None:
    rig = free_trig(OUT, free_neuron_budget=FREE_ENV_BUDGET)
    assert rig.free_call("propose", token="t1").status_code == 200


def test_free_suggest_at_the_cap_fits_a_larger_budget() -> None:
    rig = free_trig(suggest_out(("Roadside help", "Towing")), free_neuron_budget=9999)
    r = rig.post(SUGGEST, _free_suggest_body("t1"), headers={})
    assert r.status_code == 200


def test_daily_budget_refuses_before_it_would_be_exceeded() -> None:
    # Budget 700: share 210 is enough for one propose, but analyses used most of the day.
    rig = free_trig(
        OUT,
        free_neuron_budget=700,
        free_calls_per_ip_per_day=100,
        check_per_minute=100,
        check_per_day=1000,
    )
    for n in range(60):
        done = rig.check({"provider": "free", "turnstile_token": f"c{n}"}, headers={})
        assert done.status_code == 200, n
    before = len(rig.upstream.seen)
    r = rig.free_call("propose", token="tp")
    assert (r.status_code, error_of(r)) == (429, "free_quota_exhausted")
    assert len(rig.upstream.seen) == before


def test_the_reservation_is_held_while_the_call_is_in_flight() -> None:
    gate = GateTransport()
    # A share of 210 Neurons: one propose fits, two do not.
    rig = gated_rig(gate, free_neuron_budget=700, topics_per_minute=100, **FREE_ENV)

    def scope(ip: str, token: str) -> tuple[dict[str, object], bytes]:
        payload = {"provider": "free", "turnstile_token": token, "topic": topic_body()["topic"]}
        body = json.dumps(payload).encode()
        s = post_scope(PROPOSE, content_type="application/json", content_length=len(body))
        s["client"] = (ip, 50000)
        return s, body

    async def go() -> None:
        s1, b1 = scope("198.51.100.1", "a")
        first = asyncio.create_task(drive(rig.app, s1, chunks(b1)))
        for _ in range(500):
            if gate.started:
                break
            await asyncio.sleep(0.01)
        s2, b2 = scope("198.51.100.2", "b")
        second = await drive(rig.app, s2, chunks(b2))
        assert (second.status, json.loads(second.body)) == (429, {"error": "free_quota_exhausted"})
        gate.release.set()
        await first

    asyncio.run(go())


# --- settle ---------------------------------------------------------------------------------


def _ip(n: int) -> str:
    return f"198.51.100.{n}"


def test_settle_uses_the_reported_usage_so_small_calls_do_not_exhaust_the_share() -> None:
    rig = free_trig(OUT, free_neuron_budget=FREE_ENV_BUDGET)
    rig.upstream.reply = usage_reply(OUT, 50, 20)
    # Reserved worst case ~206 each: without a settle, the 7th call exceeds the share of 1410.
    for n in range(1, 13):
        r = rig.free_call("propose", token=f"t{n}", ip=_ip(n))
        assert r.status_code == 200, n


# --- one live pass per client ---------------------------------------------------------------


def test_second_turnstile_solve_replaces_the_old_pass() -> None:
    rig = free_trig(OUT)
    first = rig.free_call("propose", token="t1").json()["free_pass"]
    second = rig.free_call("propose", token="t2").json()["free_pass"]
    assert first != second
    old = rig.free_call("propose", pass_=first)
    assert (old.status_code, error_of(old)) == (403, "free_pass_invalid")
    assert rig.free_call("propose", pass_=second).status_code == 200


def test_replacement_also_works_from_another_64_of_the_same_48() -> None:
    rig = free_trig(OUT)
    first = rig.free_call("propose", token="t1", ip="2001:db8:abcd:1::1").json()["free_pass"]
    rig.free_call("propose", token="t2", ip="2001:db8:abcd:2::1")
    old = rig.free_call("propose", pass_=first, ip="2001:db8:abcd:1::1")
    assert (old.status_code, error_of(old)) == (403, "free_pass_invalid")


def test_one_client_holds_one_table_entry_however_often_it_solves() -> None:
    rig = free_trig(OUT, free_pass_max_entries=2)
    for n in range(1, 6):
        assert rig.free_call("propose", token=f"a{n}", ip=_ip(11)).status_code == 200
    assert rig.free_call("propose", token="b1", ip=_ip(12)).status_code == 200
    third = rig.free_call("propose", token="c1", ip=_ip(13))
    assert (third.status_code, error_of(third)) == (503, "free_pass_unavailable")


def test_a_client_may_replace_its_pass_while_the_table_is_full() -> None:
    rig = free_trig(OUT, free_pass_max_entries=2)
    rig.free_call("propose", token="a1", ip=_ip(11))
    rig.free_call("propose", token="b1", ip=_ip(12))
    again = rig.free_call("propose", token="a2", ip=_ip(11))
    assert again.status_code == 200
    assert "free_pass" in again.json()


# --- refund of a pass call ------------------------------------------------------------------


def _calls_left(rig: TRig, pass_: str) -> int:
    """How many more calls the pass accepts (pass limit is 2 in these tests)."""
    n = 0
    while rig.free_call("propose", pass_=pass_).status_code == 200:
        n += 1
        assert n < 5
    return n


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_pass_call_is_refunded_when_the_provider_refuses_without_cost(status: int) -> None:
    rig = free_trig(OUT, free_pass_max_calls=3)
    pass_ = rig.free_call("propose", token="t1").json()["free_pass"]  # call 1
    ok = rig.upstream.reply
    rig.upstream.reply = error_reply(status)
    expected = 401 if status == 403 else status  # 403 maps to provider_auth_failed
    assert rig.free_call("propose", pass_=pass_).status_code == expected
    rig.upstream.reply = ok
    assert _calls_left(rig, pass_) == 2


def test_pass_call_is_not_refunded_after_ai_bad_output() -> None:
    rig = free_trig("garbage", free_pass_max_calls=3)
    rig.upstream.texts[:] = [OUT]  # type: ignore[union-attr]
    pass_ = rig.free_call("propose", token="t1").json()["free_pass"]  # call 1
    rig.upstream.texts[:] = ["garbage"]  # type: ignore[union-attr]
    bad = rig.free_call("propose", pass_=pass_)  # call 2, not refunded
    assert error_of(bad) == "ai_bad_output"
    rig.upstream.texts[:] = [OUT]  # type: ignore[union-attr]
    assert _calls_left(rig, pass_) == 1


class _Switch(httpx2.AsyncBaseTransport):
    """Answers with a valid propose output, or hangs while ``hang`` is set."""

    def __init__(self) -> None:
        self.hang = False
        self.out = syn_out(en=["towing"])

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        if self.hang:
            await asyncio.Event().wait()
        return model_reply(self.out)(request)


def test_pass_call_is_not_refunded_after_a_timeout() -> None:
    switch = _Switch()
    rig = gated_rig(
        switch,
        topic_ai_deadline_seconds=0.3,
        free_pass_max_calls=3,
        topics_per_minute=100,
        **FREE_ENV,
    )
    topic = topic_body()["topic"]

    def call(body: dict[str, object], pass_: str | None = None) -> tuple[dict[str, object], bytes]:
        raw = json.dumps(body).encode()
        headers = [("x-free-pass", pass_)] if pass_ else []
        s = post_scope(
            EXPAND, content_type="application/json", content_length=len(raw), extra_headers=headers
        )
        s["client"] = ("198.51.100.7", 50000)
        return s, raw

    async def go() -> None:
        s, raw = call({"provider": "free", "turnstile_token": "t1", "topic": topic})
        first = await drive(rig.app, s, chunks(raw))
        pass_ = json.loads(first.body)["free_pass"]  # call 1
        switch.hang = True
        s, raw = call({"provider": "free", "topic": topic}, pass_)
        slow = await drive(rig.app, s, chunks(raw))  # call 2, not refunded
        assert error_of_body(slow.body) == "provider_unavailable"
        switch.hang = False
        s, raw = call({"provider": "free", "topic": topic}, pass_)
        third = await drive(rig.app, s, chunks(raw))  # call 3
        assert third.status == 200
        s, raw = call({"provider": "free", "topic": topic}, pass_)
        fourth = await drive(rig.app, s, chunks(raw))
        assert error_of_body(fourth.body) == "free_pass_exhausted"

    asyncio.run(go())


def error_of_body(body: bytes) -> str:
    return str(json.loads(body).get("error", ""))
