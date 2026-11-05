# ruff: noqa: S106
"""S7-T2 AC3: free pass (HMAC, per process, aud, expiry, client, calls, table) and free quotas."""

from __future__ import annotations

import ast
from pathlib import Path

import httpx2

from tests.check.helpers import KEY_HEADER, PUBLIC_IP
from tests.topic_ai.helpers import (
    EXPAND,
    PROPOSE,
    TRig,
    attr,
    attr_out,
    error_of,
    free_trig,
    syn_out,
    topic_body,
)

APP = Path(__file__).resolve().parents[2] / "app"
IP_A, IP_B = PUBLIC_IP, "198.51.100.2"
OUT = attr_out(attr())


def issue(rig: TRig, token: str = "tok-1", ip: str = IP_A) -> str:  # noqa: S107
    response = rig.free_call("propose", token=token, ip=ip)
    assert response.status_code == 200, response.text
    return str(response.json()["free_pass"])


def test_first_free_call_verifies_turnstile_and_returns_a_pass() -> None:
    rig = free_trig(OUT)
    pass_ = issue(rig)
    parts = pass_.split(".")
    assert parts[0] == "v1"
    assert parts[1] == "topics"
    assert len(parts) == 6
    assert len(rig.turnstile.seen) == 1
    assert len(pass_) <= 256


def test_pass_makes_later_calls_without_turnstile() -> None:
    rig = free_trig(OUT)
    pass_ = issue(rig)
    for n in range(3):
        r = rig.free_call("propose", pass_=pass_)
        assert r.status_code == 200, n
        assert "free_pass" not in r.json()
    assert len(rig.turnstile.seen) == 1


def test_pass_works_on_expand_synonyms() -> None:
    rig = free_trig(OUT, syn_out(en=["towing"]))
    pass_ = issue(rig)
    body = {"provider": "free", "topic": topic_body()["topic"]}
    rig.upstream.texts[:] = [syn_out(en=["towing"])]  # type: ignore[union-attr]
    r = rig.post(EXPAND, body, headers={"X-Free-Pass": pass_})
    assert r.status_code == 200
    assert r.json()["synonyms_en"] == ["towing"]


def test_twentieth_call_is_allowed_and_twenty_first_is_refused_without_an_ai_call() -> None:
    rig = free_trig(OUT)
    pass_ = issue(rig)  # call 1
    for _ in range(19):
        assert rig.free_call("propose", pass_=pass_).status_code == 200
    calls = len(rig.upstream.seen)
    r = rig.free_call("propose", pass_=pass_)
    assert (r.status_code, error_of(r)) == (403, "free_pass_exhausted")
    assert len(rig.upstream.seen) == calls


def test_pass_expires_after_15_minutes() -> None:
    rig = free_trig(OUT)
    pass_ = issue(rig)
    rig.clock.now += 899
    assert rig.free_call("propose", pass_=pass_).status_code == 200
    rig.clock.now += 2
    r = rig.free_call("propose", pass_=pass_)
    assert (r.status_code, error_of(r)) == (403, "free_pass_expired")


def _tamper(pass_: str, index: int, value: str) -> str:
    parts = pass_.split(".")
    parts[index] = value
    return ".".join(parts)


def test_tampered_passes_are_invalid() -> None:
    rig = free_trig(OUT)
    pass_ = issue(rig)
    mac = pass_.split(".")[-1]
    bad_mac = mac[:-1] + ("0" if mac[-1] != "0" else "1")
    cases = {
        "mac": _tamper(pass_, 5, bad_mac),
        "aud": _tamper(pass_, 1, "check"),
        "expiry": _tamper(pass_, 2, str(int(pass_.split(".")[2]) + 3600)),
        "client": _tamper(pass_, 3, "0" * len(pass_.split(".")[3])),
        "nonce": _tamper(pass_, 4, "0" * len(pass_.split(".")[4])),
        "version": _tamper(pass_, 0, "v2"),
        "garbage": "abc",
        "empty-parts": ".....",
        "too-long": pass_ + "a" * 300,
    }
    for name, value in cases.items():
        r = rig.free_call("propose", pass_=value)
        assert (r.status_code, error_of(r)) == (403, "free_pass_invalid"), name


def test_a_new_app_instance_refuses_passes_of_the_old_one() -> None:
    old = free_trig(OUT)
    pass_ = issue(old)
    new = free_trig(OUT)
    r = new.free_call("propose", pass_=pass_)
    assert (r.status_code, error_of(r)) == (403, "free_pass_invalid")
    assert new.upstream.seen == []


def test_pass_is_refused_for_another_ipv4_client() -> None:
    rig = free_trig(OUT)
    pass_ = issue(rig)
    r = rig.free_call("propose", pass_=pass_, ip=IP_B)
    assert (r.status_code, error_of(r)) == (403, "free_pass_invalid")


def test_pass_is_valid_inside_the_same_ipv6_48_and_refused_outside() -> None:
    rig = free_trig(OUT)
    pass_ = issue(rig, ip="2001:db8:abcd:1::1")
    assert rig.free_call("propose", pass_=pass_, ip="2001:db8:abcd:7::9").status_code == 200
    r = rig.free_call("propose", pass_=pass_, ip="2001:db8:abce:1::1")
    assert (r.status_code, error_of(r)) == (403, "free_pass_invalid")


def test_pass_in_the_body_or_the_query_string_is_not_accepted() -> None:
    rig = free_trig(OUT)
    pass_ = issue(rig)
    body = {"provider": "free", "topic": topic_body()["topic"], "free_pass": pass_}
    r = rig.post(PROPOSE, body, headers={})
    assert (r.status_code, error_of(r)) == (422, "invalid_request")
    q = rig.client(IP_A).post(
        f"{PROPOSE}?free_pass={pass_}&x_free_pass={pass_}",
        json={"provider": "free", "topic": topic_body()["topic"]},
    )
    assert (q.status_code, error_of(q)) == (403, "turnstile_failed")


def test_pass_and_turnstile_token_together_are_invalid_request() -> None:
    rig = free_trig(OUT)
    pass_ = issue(rig)
    body = {"provider": "free", "topic": topic_body()["topic"], "turnstile_token": "tok-2"}
    r = rig.post(PROPOSE, body, headers={"X-Free-Pass": pass_})
    assert (r.status_code, error_of(r)) == (422, "invalid_request")


def test_free_call_without_pass_and_token_is_turnstile_failed() -> None:
    rig = free_trig(OUT)
    r = rig.free_call("propose", token=None)
    assert (r.status_code, error_of(r)) == (403, "turnstile_failed")
    assert rig.upstream.seen == []


def test_pass_header_with_a_non_free_provider_is_refused() -> None:
    rig = free_trig(OUT)
    pass_ = issue(rig)
    headers = {**KEY_HEADER, "X-Free-Pass": pass_}
    r = rig.post(PROPOSE, topic_body(), headers=headers)
    assert (r.status_code, error_of(r)) == (422, "unexpected_free_pass")


def test_provider_check_refuses_a_pass_in_the_header() -> None:
    rig = free_trig(OUT)
    pass_ = issue(rig)
    r = rig.check({"provider": "free"}, headers={"X-Free-Pass": pass_}, ip=IP_A)
    assert (r.status_code, error_of(r)) == (422, "unexpected_free_pass")


def test_provider_check_refuses_a_pass_used_as_a_turnstile_token() -> None:
    rig = free_trig(OUT)
    pass_ = issue(rig)

    def verdict(request: httpx2.Request) -> httpx2.Response:
        ok = pass_ not in request.content.decode()
        return httpx2.Response(200, json={"success": ok, "error-codes": ["invalid-input-response"]})

    rig.turnstile.reply = verdict
    r = rig.check({"provider": "free", "turnstile_token": pass_}, headers={}, ip=IP_A)
    assert (r.status_code, error_of(r)) == (403, "turnstile_failed")


def test_full_pass_table_refuses_new_passes_and_frees_after_expiry() -> None:
    rig = free_trig(OUT, free_pass_max_entries=2)
    issue(rig, "t1", "198.51.100.11")
    issue(rig, "t2", "198.51.100.12")
    calls = len(rig.upstream.seen)
    r = rig.free_call("propose", token="t3", ip="198.51.100.13")
    assert (r.status_code, error_of(r)) == (503, "free_pass_unavailable")
    assert len(rig.upstream.seen) == calls
    rig.clock.now += 901
    assert rig.free_call("propose", token="t4", ip="198.51.100.13").status_code == 200


def test_per_ip_free_topic_quota_is_enforced_before_the_call_and_resets_at_midnight() -> None:
    rig = free_trig(OUT, free_topic_calls_per_ip_per_day=2)
    pass_ = issue(rig)  # 1
    assert rig.free_call("propose", pass_=pass_).status_code == 200  # 2
    calls = len(rig.upstream.seen)
    r = rig.free_call("propose", pass_=pass_)
    assert (r.status_code, error_of(r)) == (429, "free_quota_exhausted")
    assert int(r.headers["retry-after"]) == 43200
    assert len(rig.upstream.seen) == calls
    rig.clock.now += 43200
    assert rig.free_call("propose", token="t9").status_code == 200


def test_free_topic_quota_is_separate_from_the_free_analysis_quota() -> None:
    rig = free_trig(OUT, free_topic_calls_per_ip_per_day=3)
    for n in range(3):
        assert rig.free_call("propose", token=f"t{n}").status_code == 200
    r = rig.check({"provider": "free", "turnstile_token": "tc"}, headers={}, ip=IP_A)
    assert r.status_code == 200


def test_topic_quota_counts_per_ipv6_48() -> None:
    rig = free_trig(OUT, free_topic_calls_per_ip_per_day=2)
    assert rig.free_call("propose", token="a", ip="2001:db8:abcd:1::1").status_code == 200
    assert rig.free_call("propose", token="b", ip="2001:db8:abcd:2::1").status_code == 200
    r = rig.free_call("propose", token="c", ip="2001:db8:abcd:3::1")
    assert (r.status_code, error_of(r)) == (429, "free_quota_exhausted")


def test_policy_pass_is_hmac_sha256_per_process_and_compared_in_constant_time() -> None:
    files = [
        p
        for p in APP.rglob("*.py")
        if "x-free-pass" in p.read_text(encoding="utf-8").lower()
        or "free_pass" in p.read_text(encoding="utf-8").lower()
    ]
    assert files
    source = "\n".join(p.read_text(encoding="utf-8") for p in files)
    assert "compare_digest" in source
    assert "sha256" in source.lower()
    assert "token_bytes(32)" in source
    assert "hmac" in source
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            is_eq = isinstance(node, ast.Compare) and any(
                isinstance(o, ast.Eq | ast.NotEq) for o in node.ops
            )
            if is_eq and isinstance(node, ast.Compare):
                names = ast.dump(node).lower()
                assert "mac" not in names, f"{path.name}:{node.lineno}"
                assert "signature" not in names, f"{path.name}:{node.lineno}"
