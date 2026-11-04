"""Unit tests of the S7-T2 building blocks (backend-dev): free pass table, topic quota, repair."""

from __future__ import annotations

import pytest

from app.ai.port import AIRequest
from app.ai.prompts import PromptTemplate
from app.limits.free import FreeQuota
from app.limits.free_pass import FreePassError, FreePasses
from app.topics.ai import ProposeOut
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
    assert not passes.has_room()


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
