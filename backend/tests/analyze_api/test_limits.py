# ruff: noqa: E501, PT018
"""S9-T3 AC3: worst-case reservation, deadlines, disconnect, concurrency, free mode (analysis pass)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from tests.analyze_api.helpers import (
    ANALYZE,
    AnalyzeRig,
    Reply,
    free_analyze,
    free_analyze_rig,
    free_ready,
    issue,
    topics_for,
)
from tests.asgi_stream import chunks, drive, drive_receive
from tests.check.helpers import FREE_MODEL, KEY_HEADER, PUBLIC_IP
from tests.tag_api.helpers import PASS_HEADER, scope
from tests.topic_ai.helpers import free_trig

# --- reservation -----------------------------------------------------------------------------------


def test_the_worst_case_over_the_call_cap_is_422_before_any_call() -> None:
    rig = AnalyzeRig(analysis_max_calls=5)  # worst case here: 2 topics * 2 + 1 batch * 2 = 6
    body = rig.ready(topics=topics_for(rig, "deductible", n_custom=1))
    calls = len(rig.up.seen)
    r = rig.analyze(body)
    assert (r.status, r.error) == (422, "document_too_large_for_analysis")
    assert len(rig.up.seen) == calls and not r.is_stream


def test_the_worst_case_at_the_call_cap_is_accepted() -> None:
    rig = AnalyzeRig(analysis_max_calls=6)
    assert rig.run(topics=topics_for(rig, "deductible", n_custom=1)).status == 200


def test_the_reservation_counts_the_other_batches_needed_if_every_topic_fails() -> None:
    texts = (
        "The deductible for each insured event is 5000 UAH.",
    )  # one topic clause, Other is empty
    rig = AnalyzeRig(analysis_max_calls=3)  # 2 (topic) + 2 (Other batch if the topic fails) = 4
    body = rig.ready(*texts, topics=topics_for(rig, "deductible", n_custom=0))
    r = rig.analyze(body)
    assert (r.status, r.error) == (422, "document_too_large_for_analysis")
    ok = AnalyzeRig(analysis_max_calls=4)
    assert ok.run(*texts, topics=topics_for(ok, "deductible", n_custom=0)).status == 200


def test_a_document_over_the_character_cap_is_422_before_any_call() -> None:
    rig = AnalyzeRig(tag_max_document_chars=300_000)
    texts = [
        "The deductible " + "x" * 1900 + f" {n}." for n in range(160)
    ]  # about 306,000 characters
    tb = rig.base(*texts[:1], topics=topics_for(rig, "deductible", n_custom=0))
    body = rig.body(tb, rig.tagged(tb))
    body["document"]["clauses"] = [{"id": f"c{n}", "text": t} for n, t in enumerate(texts, 1)]
    r = rig.analyze(body)
    assert r.status in (409, 422) and not r.is_stream
    assert rig.up.rates == []


def test_reserved_calls_are_never_exceeded() -> None:
    rig = AnalyzeRig()
    rig.up.other_fn = lambda ids: "junk"
    rig.up.topic_fn = lambda t, ids: "junk"
    r = rig.run(topics=topics_for(rig, "deductible", n_custom=1))
    assert len(rig.up.rates) <= r.of("start")[0]["reserved_calls"]


def test_a_repair_is_the_only_retry_so_a_failing_topic_costs_two_calls() -> None:
    rig = AnalyzeRig()
    rig.up.topic_fn = lambda t, ids: "junk"
    rig.run(topics=topics_for(rig, "deductible", n_custom=0))
    assert len(rig.up.topic_calls("deductible")) == 2


# --- deadlines -------------------------------------------------------------------------------------


def test_the_overall_deadline_marks_open_topics_timeout_and_the_document_incomplete() -> None:
    rig = AnalyzeRig(analysis_deadline_seconds=0.4)
    body = rig.ready(topics=topics_for(rig, "deductible", n_custom=1))
    rig.up.hang = True
    r = rig.analyze(body)
    assert r.status == 200
    assert {t["state"] for t in r.of("topic")} == {"not_analyzed"}
    assert {t["reason"] for t in r.of("topic")} == {"timeout"}
    assert r.done["incomplete"] is True and r.done["greens_allowed"] is False
    assert r.done["unrated_other"] > 0
    assert [o["reason"] for o in r.of("other")] == ["timeout"]
    assert rig.up.cancelled == rig.up.hung  # nothing keeps running


def test_the_call_deadline_ends_one_slow_call_without_waiting_for_the_overall_deadline() -> None:
    rig = AnalyzeRig(analysis_call_deadline_seconds=0.2, analysis_deadline_seconds=60.0)
    body = rig.ready()
    rig.up.hang = True
    r = rig.analyze(body)
    assert r.topic("deductible")["reason"] == "timeout"
    assert r.done["incomplete"] is True


# --- disconnect, concurrency, rate limit -----------------------------------------------------------


async def _disconnect_after_hang(
    rig: AnalyzeRig, body: dict[str, Any], headers: dict[str, str]
) -> Any:
    raw = json.dumps(body).encode()
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": raw, "more_body": False}
        for _ in range(500):
            if rig.up.hung >= 1:
                break
            await asyncio.sleep(0.01)
        return {"type": "http.disconnect"}

    return await drive_receive(rig.app, scope(ANALYZE, raw, PUBLIC_IP, headers), receive)


def test_a_client_disconnect_cancels_the_outstanding_ai_calls() -> None:
    rig = AnalyzeRig()
    body = rig.ready()
    rig.up.hang = True
    asyncio.run(_disconnect_after_hang(rig, body, KEY_HEADER))
    assert rig.up.hung >= 1 and rig.up.cancelled == rig.up.hung


def test_a_second_analysis_of_the_same_client_is_503_busy_with_retry_after() -> None:
    rig = AnalyzeRig()
    body = rig.ready()
    rig.up.hang = True
    raw = json.dumps(body).encode()

    async def go() -> Any:
        release = asyncio.Event()
        first_sent = False

        async def receive() -> dict[str, Any]:
            nonlocal first_sent
            if not first_sent:
                first_sent = True
                return {"type": "http.request", "body": raw, "more_body": False}
            await release.wait()
            return {"type": "http.disconnect"}

        t1 = asyncio.create_task(
            drive_receive(rig.app, scope(ANALYZE, raw, PUBLIC_IP, KEY_HEADER), receive)
        )
        for _ in range(500):
            if rig.up.hung:
                break
            await asyncio.sleep(0.01)
        second = await drive(rig.app, scope(ANALYZE, raw, PUBLIC_IP, KEY_HEADER), chunks(raw))
        release.set()
        await t1
        return second

    second = asyncio.run(go())
    assert second.status == 503
    assert json.loads(second.body)["error"] == "busy"
    assert "retry-after" in second.headers


def test_the_per_minute_limit_is_429_rate_limited_with_retry_after() -> None:
    rig = AnalyzeRig(analysis_per_minute=1)
    body = rig.ready()
    assert rig.analyze(body).status == 200
    r = rig.client().post(ANALYZE, json=body, headers=KEY_HEADER)
    assert (r.status_code, r.json()["error"]) == (429, "rate_limited")
    assert "retry-after" in r.headers


def test_validation_failures_do_not_count_against_the_rate_limit() -> None:
    rig = AnalyzeRig(analysis_per_minute=1)
    body = rig.ready()
    for _ in range(3):
        assert rig.analyze({**body, "language": "xx"}).status == 422
    assert rig.analyze(body).status == 200


# --- free mode: the analysis pass ------------------------------------------------------------------


def _free(**kw: Any) -> tuple[AnalyzeRig, dict[str, Any], str]:
    rig = free_analyze_rig(**kw)
    body, pass_ = free_ready(rig)
    return rig, body, pass_


def test_free_analysis_runs_with_the_analysis_pass_and_the_free_model() -> None:
    rig, body, pass_ = _free()
    r = free_analyze(rig, body, pass_)
    assert r.status == 200 and r.done
    assert {c.model for c in rig.up.rates} == {FREE_MODEL}
    assert len(rig.turnstile.seen) == 1  # analyze never asks Turnstile


def test_free_analysis_without_a_pass_is_403() -> None:
    rig, body, _ = _free()
    r = free_analyze(rig, body, None)
    assert (r.status, r.error) == (403, "analysis_pass_invalid")
    assert rig.up.rates == []


def test_free_analysis_refuses_a_turnstile_token_and_a_model_field() -> None:
    rig, body, pass_ = _free()
    assert free_analyze(rig, {**body, "turnstile_token": "t"}, pass_).error == "invalid_request"
    r = free_analyze(rig, {**body, "model": "x"}, pass_)
    assert (r.status, r.error) == (422, "unexpected_model")


def test_a_topics_pass_never_works_for_analysis() -> None:
    topics_pass = free_trig().free_call("propose").json()["free_pass"]
    rig, body, _ = _free()
    r = free_analyze(rig, body, topics_pass)
    assert (r.status, r.error) == (403, "analysis_pass_invalid")
    r2 = rig.analyze(body, headers={"X-Free-Pass": topics_pass})
    assert r2.status in (403, 422) and rig.up.rates == []


def test_a_tampered_or_expired_pass_is_refused() -> None:
    rig, body, pass_ = _free()
    parts = pass_.split(".")
    parts[-1] = parts[-1][:-1] + ("0" if parts[-1][-1] != "0" else "1")
    assert free_analyze(rig, body, ".".join(parts)).error == "analysis_pass_invalid"
    rig.clock.now += 1801
    r = free_analyze(rig, body, pass_)
    assert (r.status, r.error) == (403, "analysis_pass_expired")
    assert rig.up.rates == []


def test_a_pass_header_with_a_paid_provider_is_422() -> None:
    rig = AnalyzeRig()
    r = rig.analyze(rig.ready(), headers={**KEY_HEADER, PASS_HEADER: "v1.x"})
    assert (r.status, r.error) == (422, "unexpected_analysis_pass")


def test_a_digest_that_the_pass_never_recorded_is_403_document_mismatch() -> None:
    rig = free_analyze_rig()
    pass_ = issue(rig)  # records the default document
    other = rig.base("Another document text for the deductible.")
    paid = rig.tagged(
        other
    )  # tagged with a key, so the signature is valid but the pass never saw it
    body = rig.body(
        {k: v for k, v in other.items() if k not in ("provider", "model", "check_model")}, paid
    )
    body["provider"] = "free"
    r = free_analyze(rig, body, pass_)
    assert (r.status, r.error) == (403, "analysis_pass_document_mismatch")
    assert rig.up.rates == []


def test_the_call_cap_of_the_pass_refuses_a_worst_case_that_does_not_fit_before_any_call() -> None:
    rig, body, pass_ = _free(
        analysis_pass_max_calls=4
    )  # tag 4 fits; analyze (worst case 4) does not
    r = free_analyze(rig, body, pass_)
    assert (r.status, r.error) == (403, "analysis_pass_exhausted")
    assert rig.up.rates == []


def test_the_pass_call_cap_bounds_all_calls_of_the_pass() -> None:
    rig, body, pass_ = _free(analysis_pass_max_calls=14)
    codes = [free_analyze(rig, body, pass_).status for _ in range(6)]
    assert 403 in codes
    assert len(rig.up.calls) + len(rig.up.rates) <= 14


def test_free_analysis_of_unfinished_calls_settles_at_the_worst_case() -> None:
    rig, body, pass_ = _free(analysis_pass_max_neurons=9999, analysis_pass_max_calls=100000)
    rig.up.hang = True
    refused: list[Reply] = []

    async def go() -> None:
        for _ in range(60):
            run = await _disconnect_after_hang(rig, body, {PASS_HEADER: pass_})
            if run.status != 200:
                refused.append(run)
                return

    asyncio.run(go())
    assert refused, "cancelled calls must consume the Neuron budget at the worst case"
    assert json.loads(refused[0].body)["error"] in {
        "analysis_pass_exhausted",
        "free_quota_exhausted",
    }
    assert rig.up.cancelled == rig.up.hung


def test_a_free_analysis_that_finished_settles_from_reported_usage_so_many_runs_fit() -> None:
    rig, body, pass_ = _free(analysis_pass_max_neurons=9999, analysis_pass_max_calls=100000)
    for n in range(8):
        r = free_analyze(rig, body, pass_)
        assert r.status == 200, (n, r.raw[:200])
