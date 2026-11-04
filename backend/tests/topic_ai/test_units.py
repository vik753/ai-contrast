"""Unit tests of the S7-T2 building blocks (backend-dev): free pass table, topic quota, repair."""

from __future__ import annotations

import pytest

from app.ai.port import AIRequest
from app.ai.prompts import PromptTemplate
from app.limits.free import FreeQuota, usage_neurons
from app.limits.free_pass import FreePassError, FreePasses
from app.limits.hits import Hits
from app.limits.window import FixedWindowLimiter
from app.topics.ai import ProposeOut
from tests.topic_ai.helpers import SUGGEST, free_trig, suggest_body
from tests.topics.helpers import confirmed

NOW = 1_800_000_000.0


def test_pass_refund_and_discard() -> None:
    passes = FreePasses(2, 2, lambda: NOW)
    value, nonce = passes.issue("1.2.3.4") or ("", "")
    assert passes.use(value, "1.2.3.4") == nonce
    with pytest.raises(FreePassError) as info:
        passes.use(value, "1.2.3.4")
    assert info.value.code == "free_pass_exhausted"
    passes.refund(nonce)
    assert passes.use(value, "1.2.3.4") == nonce
    passes.discard(nonce)
    with pytest.raises(FreePassError) as gone:
        passes.use(value, "1.2.3.4")
    assert gone.value.code == "free_pass_invalid"


def test_pass_table_is_bounded() -> None:
    passes = FreePasses(1, 5, lambda: NOW)
    assert passes.issue("a") is not None
    assert passes.issue("b") is None
    assert not passes.has_room("b")
    assert passes.has_room("a")


def test_topic_quota_share_and_refund() -> None:
    quota = FreeQuota(5, 100, 10, lambda: NOW, topic_calls_per_ip=3)
    assert quota.reserve_topic("k", 20).allowed
    assert not quota.reserve_topic("k", 20).allowed  # 40 > 30 % of 100
    quota.settle_topic(20, 0)
    quota.refund_topic_call("k")
    assert quota.remaining_neurons == 100
    assert quota.reserve_topic("k", 20).allowed


def test_repair_code_is_range_checked() -> None:
    with pytest.raises(ValueError, match="repair"):
        AIRequest(PromptTemplate.PROPOSE_ATTRIBUTES, ProposeOut, 100, topic=confirmed(), repair=9)


def test_hits_count_and_refund_only_what_was_counted() -> None:
    minute = FixedWindowLimiter(1, 60, 10, lambda: NOW)
    day = FixedWindowLimiter(1, 86400, 10, lambda: NOW, aligned=True)
    first = Hits(minute, day, "m", "d")
    assert first.count() is None
    second = Hits(minute, day, "m", "d")
    refused = second.count()
    assert refused is not None
    assert not second.minute
    first.refund()
    assert Hits(minute, day, "m", "d").count() is None


def test_usage_neurons_rounds_up() -> None:
    assert usage_neurons(0, 0) == 0
    assert usage_neurons(50, 20) == 3
    assert usage_neurons(1_000_000, 0) == 31818


def test_free_suggest_checks_the_pass_before_the_sandbox() -> None:
    rig = free_trig()
    body = {"provider": "free", **{k: v for k, v in suggest_body().items() if k != "provider"}}
    body.pop("model", None)
    r = rig.post(SUGGEST, body, headers={"X-Free-Pass": "v1.topics.1.2.3.4"})
    assert (r.status_code, r.json()["error"]) == (403, "free_pass_invalid")
    no_token = rig.post(SUGGEST, body, headers={})
    assert (no_token.status_code, no_token.json()["error"]) == (403, "turnstile_failed")
