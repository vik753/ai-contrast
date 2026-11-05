# ruff: noqa: UP031
"""S8-T2 AC3: sandbox placement, budgets, reservation, batches, deadlines."""

from __future__ import annotations

import asyncio
import json
import time

from tests.check.helpers import GateTransport
from tests.tag_api.helpers import (
    TagRig,
    big_doc,
    error_of,
    free_tag_rig,
    gated_tag_rig,
    post_async,
    tag_body,
    wait_started,
)

IP_A = "198.51.100.1"


def test_keyword_budget_exceeded_is_a_refusal_with_no_ai_call() -> None:
    rig = TagRig(keyword_step_budget=10)
    r = rig.tag()
    assert (r.status_code, error_of(r)) == (422, "keyword_budget_exceeded")
    assert rig.tags.seen == []
    assert "tags" not in r.text


def test_document_over_the_token_budget_is_422_before_any_ai_call() -> None:
    rig = TagRig(tag_max_document_chars=1000)
    r = rig.tag(*big_doc(2000, "alpha"))
    assert (r.status_code, error_of(r)) == (422, "document_too_large_for_tagging")
    assert rig.tags.seen == []


def test_document_at_the_character_budget_is_accepted() -> None:
    rig = TagRig(tag_max_document_chars=3000)
    assert rig.tag(*big_doc(3000, "alpha")).status_code == 200


def test_document_needing_more_than_60_batches_is_422_before_any_ai_call() -> None:
    rig = TagRig(tag_max_document_chars=2_000_000)
    texts = tuple(("w%d " % n) * 2800 for n in range(61))  # about 11,000 characters each
    r = rig.tag(*[t[:11000] for t in texts])
    assert (r.status_code, error_of(r)) == (422, "document_too_large_for_tagging")
    assert rig.tags.seen == []


def test_extraction_slot_is_free_while_the_tag_ai_calls_run() -> None:
    gate = GateTransport()
    rig = gated_tag_rig(gate)

    async def go() -> None:
        first = asyncio.create_task(post_async(rig, tag_body(), IP_A))
        await wait_started(gate, 1)
        limiter = rig.app.state.extraction_limiter
        assert limiter.try_acquire()
        limiter.release()
        gate.release.set()
        await first

    asyncio.run(go())


def test_hung_provider_hits_the_per_call_deadline_and_keeps_keyword_tags() -> None:
    gate = GateTransport()  # never released
    rig = gated_tag_rig(gate, tag_call_deadline_seconds=0.3)

    async def go() -> None:
        start = time.monotonic()
        r = await post_async(rig, tag_body(), IP_A)
        assert time.monotonic() - start < 10
        body = json.loads(r.body)
        assert r.status == 200
        assert "timeout" in body["incomplete_reasons"]
        assert body["model_tagging_incomplete"] is True
        assert body["tags"]["c1"]
        gate.release.set()
        again = await post_async(rig, tag_body(), IP_A)
        assert again.status != 503  # slots were released

    asyncio.run(go())


def test_overall_deadline_ends_the_request_with_keyword_tags() -> None:
    gate = GateTransport()
    rig = gated_tag_rig(gate, tag_deadline_seconds=0.5)

    async def go() -> None:
        start = time.monotonic()
        r = await post_async(rig, tag_body(*[f"Clause {n} deductible." for n in range(90)]), IP_A)
        assert time.monotonic() - start < 10
        body = json.loads(r.body)
        assert r.status == 200
        assert "timeout" in body["incomplete_reasons"]
        assert len(body["tags"]) == 90
        gate.release.set()

    asyncio.run(go())


def test_total_ai_calls_stay_within_the_worst_case_of_two_per_step_per_batch() -> None:
    rig = TagRig(lambda ids, n: "garbage", lambda pairs: "garbage")
    rig.tag(*[f"Clause {n} deductible." for n in range(45)])  # 2 batches
    assert len(rig.tags.calls) <= 2 * 2 * 2


def test_free_worst_case_not_fitting_the_budget_fails_before_any_call() -> None:
    rig = free_tag_rig(free_neuron_budget=10)
    r = rig.free_tag()
    assert (r.status_code, error_of(r)) == (429, "free_quota_exhausted")
    assert "retry-after" in r.headers
    assert rig.tags.seen == []
