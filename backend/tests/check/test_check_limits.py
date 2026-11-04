"""S6-T4 AC1 and AC3a: per-IP limits, in-flight limit, Retry-After, when a hit is counted."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from tests.ai.helpers import error_reply, model_reply
from tests.asgi_stream import chunks, drive, post_scope
from tests.check.helpers import (
    CHECK,
    DAY,
    KEY_HEADER,
    GateTransport,
    Rig,
    free_rig,
    siteverify_reply,
    valid_body,
)

IP_A = "198.51.100.1"
IP_B = "198.51.100.2"


def test_check_eleventh_request_in_a_minute_returns_429_with_retry_after() -> None:
    rig = Rig()
    for _ in range(10):
        assert rig.check(ip=IP_A).status_code == 200
    response = rig.check(ip=IP_A)
    assert response.status_code == 429
    assert response.json() == {"error": "rate_limited"}
    assert int(response.headers["retry-after"]) == 60


def test_check_limit_is_per_ip() -> None:
    rig = Rig()
    for _ in range(10):
        rig.check(ip=IP_A)
    assert rig.check(ip=IP_A).status_code == 429
    assert rig.check(ip=IP_B).status_code == 200


def test_check_minute_window_ends_after_60_seconds() -> None:
    rig = Rig()
    for _ in range(10):
        rig.check(ip=IP_A)
    rig.clock.now += 60
    assert rig.check(ip=IP_A).status_code == 200


def test_check_sixty_first_request_of_the_day_returns_429_until_midnight_utc() -> None:
    rig = Rig(check_per_minute=1000)
    for _ in range(60):
        assert rig.check(ip=IP_A).status_code == 200
    rig.clock.now = (rig.clock.now // DAY) * DAY + 23 * 3600
    response = rig.check(ip=IP_A)
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) == 3600


def test_check_daily_limit_resets_at_midnight_utc_not_after_24_hours() -> None:
    rig = Rig(check_per_minute=1000, check_per_day=2)
    rig.check(ip=IP_A)
    rig.check(ip=IP_A)
    assert rig.check(ip=IP_A).status_code == 429
    midnight = (rig.clock.now // DAY + 1) * DAY
    rig.clock.now = midnight - 1
    assert rig.check(ip=IP_A).status_code == 429
    rig.clock.now = midnight
    assert rig.check(ip=IP_A).status_code == 200


def test_check_limits_are_settings() -> None:
    rig = Rig(check_per_minute=2)
    rig.check(ip=IP_A)
    rig.check(ip=IP_A)
    assert rig.check(ip=IP_A).status_code == 429


def test_check_invalid_requests_do_not_count_against_the_limit() -> None:
    rig = Rig(check_per_minute=2, check_per_day=2)
    for _ in range(30):
        assert rig.check({"provider": "nope"}, headers=KEY_HEADER, ip=IP_A).status_code == 422
        assert rig.check(valid_body(), headers={}, ip=IP_A).status_code == 422
        assert (
            rig.check({**valid_body(), "extra": 1}, headers=KEY_HEADER, ip=IP_A).status_code == 422
        )
    assert rig.check(ip=IP_A).status_code == 200
    assert rig.check(ip=IP_A).status_code == 200
    assert rig.check(ip=IP_A).status_code == 429


def test_check_oversized_requests_do_not_count_against_the_limit() -> None:
    rig = Rig(check_per_minute=1)
    big = json.dumps({**valid_body(), "model": "a" * 5000})
    for _ in range(5):
        r = rig.client(IP_A).post(
            CHECK, content=big, headers={**KEY_HEADER, "Content-Type": "application/json"}
        )
        assert r.status_code == 413
    assert rig.check(ip=IP_A).status_code == 200


def test_check_unknown_ip_shares_one_key() -> None:
    rig = Rig(check_per_minute=2)
    # A development peer that is not an IP address is the shared key "unknown".
    for ip in ("not-an-ip", "also-not-an-ip"):
        rig.check(ip=ip)
    assert rig.check(ip="third-bad-peer").status_code == 429


def test_check_ipv6_rotation_inside_one_slash_64_shares_the_minute_limit() -> None:
    rig = Rig(check_per_minute=2)
    rig.check(ip="2001:db8:1:2::1")
    rig.check(ip="2001:db8:1:2::2")
    assert rig.check(ip="2001:db8:1:2::3").status_code == 429


def test_check_ipv6_rotation_across_slash_64_in_one_slash_48_shares_the_daily_limit() -> None:
    rig = Rig(check_per_minute=1000, check_per_day=3)
    for n in range(3):
        assert rig.check(ip=f"2001:db8:1:{n}::1").status_code == 200
    assert rig.check(ip="2001:db8:1:99::1").status_code == 429


def test_check_ipv6_other_slash_48_has_its_own_daily_limit() -> None:
    rig = Rig(check_per_minute=1000, check_per_day=1)
    assert rig.check(ip="2001:db8:1:1::1").status_code == 200
    assert rig.check(ip="2001:db8:1:2::1").status_code == 429
    assert rig.check(ip="2001:db8:2:1::1").status_code == 200


def test_check_ipv6_rotation_cannot_lock_out_an_ipv4_client() -> None:
    rig = Rig(check_per_minute=1000, check_per_day=1)
    for n in range(50):
        rig.check(ip=f"2001:db8:1:{n}::1")
    assert rig.check(ip=IP_A).status_code == 200


def test_check_third_request_in_flight_returns_503_busy_with_retry_after() -> None:
    rig = Rig()
    gate = GateTransport()
    rig.app.state.provider_transport = gate

    async def scenario() -> None:
        body = json.dumps(valid_body()).encode()

        def scope(ip: str) -> dict[str, Any]:
            s = post_scope(
                CHECK,
                content_type="application/json",
                content_length=len(body),
                extra_headers=list(KEY_HEADER.items()),
            )
            s["client"] = (ip, 50000)
            return s

        first = asyncio.create_task(drive(rig.app, scope("198.51.100.11"), chunks(body)))
        second = asyncio.create_task(drive(rig.app, scope("198.51.100.12"), chunks(body)))
        for _ in range(500):
            if gate.started >= 2:
                break
            await asyncio.sleep(0.01)
        assert gate.started == 2
        third = await drive(rig.app, scope("198.51.100.13"), chunks(body))
        assert third.status == 503
        assert json.loads(third.body) == {"error": "busy"}
        assert int(third.headers["retry-after"]) >= 1
        assert gate.started == 2
        gate.release.set()
        assert (await first).status == 200
        assert (await second).status == 200
        # Both slots are free again.
        later = await drive(rig.app, scope("198.51.100.14"), chunks(body))
        assert later.status == 200

    asyncio.run(scenario())


def test_check_slot_is_released_after_a_provider_error() -> None:
    rig = Rig(check_per_minute=1000)
    rig.upstream.reply = error_reply(500)
    for n in range(6):
        rig.check(ip=f"198.51.100.{20 + n}")
    rig.upstream.reply = model_reply()
    assert rig.check(ip="198.51.100.40").status_code == 200


def test_check_failed_turnstile_does_not_consume_the_check_limit() -> None:
    rig = free_rig(check_per_minute=2, check_per_day=2)
    rig.turnstile.reply = siteverify_reply(success=False)
    for n in range(10):
        assert rig.free(f"t{n}", ip=IP_A).status_code == 403
    rig.turnstile.reply = siteverify_reply(clock=rig.clock)
    assert rig.free("good-1", ip=IP_A).status_code == 200
