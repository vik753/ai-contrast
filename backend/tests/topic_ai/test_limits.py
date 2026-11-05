"""S7-T2 AC2, 3a: per-IP limits, in-flight limits shared with check, deadline, extraction slot."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.pseudo.lexicon import DETECTOR_VERSION
from app.settings import Settings
from tests.asgi_stream import chunks, drive, post_scope
from tests.check.helpers import CHECK, DAY, KEY_HEADER, GateTransport, valid_body
from tests.safety_helpers import SAFETY, doc
from tests.topic_ai.helpers import (
    PROPOSE,
    SUGGEST,
    TRig,
    error_of,
    gated_rig,
    suggest_body,
    topic_body,
)

IP_A, IP_B, IP_C = "198.51.100.1", "198.51.100.2", "198.51.100.3"


def test_settings_defaults() -> None:
    s = Settings(environment="development")
    assert (s.topics_per_minute, s.topics_per_day) == (10, 60)
    assert s.topic_ai_deadline_seconds == 60.0
    assert s.suggest_max_chars == 60000
    assert (s.free_topic_calls_per_ip_per_day, s.free_pass_max_calls) == (40, 20)


def test_eleventh_topic_call_in_a_minute_is_429_with_retry_after() -> None:
    rig = TRig()
    for _ in range(10):
        assert rig.propose(ip=IP_A).status_code == 200
    r = rig.propose(ip=IP_A)
    assert (r.status_code, error_of(r)) == (429, "rate_limited")
    assert int(r.headers["retry-after"]) == 60
    assert rig.propose(ip=IP_B).status_code == 200


def test_the_limit_is_shared_by_the_three_endpoints() -> None:
    rig = TRig(topics_per_minute=2)
    assert rig.propose().status_code == 200
    assert rig.post(SUGGEST, suggest_body()).status_code in (200, 502)
    assert rig.propose().status_code == 429


def test_validation_failures_count_nothing() -> None:
    rig = TRig(topics_per_minute=2)
    for _ in range(5):
        assert rig.post(PROPOSE, {**topic_body(), "extra": 1}, ip=IP_A).status_code == 422
        assert rig.post(PROPOSE, topic_body(side="x"), ip=IP_A).status_code == 422
    assert rig.propose(ip=IP_A).status_code == 200


def test_daily_limit_resets_at_00_00_utc_not_after_24_hours() -> None:
    rig = TRig(topics_per_minute=100, topics_per_day=3)
    for _ in range(3):
        assert rig.propose().status_code == 200
    r = rig.propose()
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) == DAY // 2
    rig.clock.now += DAY // 2
    assert rig.propose().status_code == 200


def test_daily_limit_keys_ipv6_by_48_but_minute_limit_by_64() -> None:
    rig = TRig(topics_per_minute=1, topics_per_day=2)
    assert rig.propose(ip="2001:db8:abcd:1::1").status_code == 200
    assert rig.propose(ip="2001:db8:abcd:2::1").status_code == 200  # other /64, same /48
    rig.clock.now += 61
    assert rig.propose(ip="2001:db8:abcd:3::1").status_code == 429  # daily, same /48
    assert rig.propose(ip="2001:db8:abce:1::1").status_code == 200


def _scope(path: str, body: bytes, ip: str, headers: dict[str, str]) -> dict[str, Any]:
    s = post_scope(
        path,
        content_type="application/json",
        content_length=len(body),
        extra_headers=list(headers.items()),
    )
    s["client"] = (ip, 50000)
    return s


async def _wait(gate: GateTransport, n: int) -> None:
    for _ in range(500):
        if gate.started >= n:
            return
        await asyncio.sleep(0.01)
    assert gate.started >= n


def _propose_scope(ip: str) -> tuple[dict[str, Any], bytes]:
    body = json.dumps(topic_body()).encode()
    return _scope(PROPOSE, body, ip, KEY_HEADER), body


def test_second_topic_call_of_the_same_client_is_503_busy() -> None:
    gate = GateTransport()
    rig = gated_rig(gate)

    async def go() -> None:
        s, b = _propose_scope(IP_A)
        first = asyncio.create_task(drive(rig.app, s, chunks(b)))
        await _wait(gate, 1)
        s2, b2 = _propose_scope(IP_A)
        second = await drive(rig.app, s2, chunks(b2))
        assert second.status == 503
        assert json.loads(second.body) == {"error": "busy"}
        assert "retry-after" in second.headers
        gate.release.set()
        await first

    asyncio.run(go())


def test_pool_of_two_is_shared_between_topic_calls_and_provider_check() -> None:
    gate = GateTransport()
    rig = gated_rig(gate)

    async def go() -> None:
        s1, b1 = _propose_scope(IP_A)
        body = json.dumps(valid_body()).encode()
        s2 = _scope(CHECK, body, IP_B, KEY_HEADER)
        first = asyncio.create_task(drive(rig.app, s1, chunks(b1)))
        second = asyncio.create_task(drive(rig.app, s2, chunks(body)))
        await _wait(gate, 2)
        s3, b3 = _propose_scope(IP_C)
        third = await drive(rig.app, s3, chunks(b3))
        assert (third.status, json.loads(third.body)) == (503, {"error": "busy"})
        gate.release.set()
        await first
        await second

    asyncio.run(go())


def test_a_check_in_flight_blocks_a_topic_call_of_the_same_client() -> None:
    gate = GateTransport()
    rig = gated_rig(gate)

    async def go() -> None:
        body = json.dumps(valid_body()).encode()
        first = asyncio.create_task(
            drive(rig.app, _scope(CHECK, body, IP_A, KEY_HEADER), chunks(body))
        )
        await _wait(gate, 1)
        s, b = _propose_scope(IP_A)
        second = await drive(rig.app, s, chunks(b))
        assert second.status == 503
        gate.release.set()
        await first

    asyncio.run(go())


def test_extraction_slot_is_free_while_the_suggest_ai_call_runs() -> None:
    gate = GateTransport()
    rig = gated_rig(gate)

    async def go() -> None:
        body = json.dumps(suggest_body()).encode()
        first = asyncio.create_task(
            drive(rig.app, _scope(SUGGEST, body, IP_A, KEY_HEADER), chunks(body))
        )
        await _wait(gate, 1)
        limiter = rig.app.state.extraction_limiter
        assert limiter.try_acquire()
        limiter.release()
        safety = json.dumps(doc(DETECTOR_VERSION, "1. Payment is due within 30 days.")).encode()
        other = await drive(rig.app, _scope(SAFETY, safety, IP_A, {}), chunks(safety))
        assert other.status == 200  # the same client's extraction slot is free too
        gate.release.set()
        await first

    asyncio.run(go())


def test_ai_deadline_returns_502_and_releases_the_slot() -> None:
    gate = GateTransport()  # never released: the provider hangs
    rig = gated_rig(gate, topic_ai_deadline_seconds=0.3)

    async def go() -> None:
        s, b = _propose_scope(IP_A)
        first = await drive(rig.app, s, chunks(b))
        assert (first.status, json.loads(first.body)) == (502, {"error": "provider_unavailable"})
        gate.release.set()
        s, b = _propose_scope(IP_A)
        again = await drive(rig.app, s, chunks(b))
        assert again.status != 503

    asyncio.run(go())
