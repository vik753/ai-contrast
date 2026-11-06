# ruff: noqa: S106
"""S8-T2 AC4: the analysis pass (aud=analysis), free quota, size limits, Neuron and call caps."""

from __future__ import annotations

from app.main import create_app
from app.settings import Settings
from tests.check.helpers import CHECK, FREE_ENV, PUBLIC_IP, GateTransport
from tests.tag_api.helpers import (
    PASS_HEADER,
    TagRig,
    big_doc,
    error_of,
    free_tag_rig,
    issue,
    tag_body,
)
from tests.topic_ai.helpers import PROPOSE, free_trig, topic_body
from tests.topics.helpers import CATALOG_OK

IP_A, IP_B = PUBLIC_IP, "198.51.100.2"
LOW = lambda ids, n: {ids[0]: [("T1", "low")]}  # noqa: E731


def _tamper(pass_: str, index: int, value: str) -> str:
    parts = pass_.split(".")
    parts[index] = value
    return ".".join(parts)


def test_first_free_tag_call_verifies_turnstile_and_returns_an_analysis_pass() -> None:
    rig = free_tag_rig()
    pass_ = issue(rig)
    parts = pass_.split(".")
    assert (parts[0], parts[1], len(parts)) == ("v1", "analysis", 6)
    assert len(pass_) <= 256
    assert len(rig.turnstile.seen) == 1


def test_pass_makes_later_tag_calls_without_turnstile() -> None:
    rig = free_tag_rig()
    pass_ = issue(rig)
    for _ in range(3):
        r = rig.free_tag(pass_=pass_)
        assert r.status_code == 200
        assert "analysis_pass" not in r.json()
    assert len(rig.turnstile.seen) == 1


def test_tag_without_pass_and_token_is_403_turnstile_failed() -> None:
    r = free_tag_rig().free_tag(token=None)
    assert (r.status_code, error_of(r)) == (403, "turnstile_failed")


def test_pass_and_token_together_are_422() -> None:
    rig = free_tag_rig()
    pass_ = issue(rig)
    body = {"provider": "free", "turnstile_token": "t2"}
    r = rig.post({**body, **_nomodel()}, headers={PASS_HEADER: pass_})
    assert (r.status_code, error_of(r)) == (422, "invalid_request")


def _nomodel() -> dict[str, object]:
    return {k: v for k, v in tag_body().items() if k not in ("provider", "model", "check_model")}


def test_pass_header_with_a_non_free_provider_is_422() -> None:
    r = TagRig().post(tag_body(), headers={"X-Provider-Key": "sk-x", PASS_HEADER: "v1.x"})
    assert (r.status_code, error_of(r)) == (422, "unexpected_analysis_pass")


def test_pass_in_the_body_is_not_accepted() -> None:
    rig = free_tag_rig()
    pass_ = issue(rig)
    r = rig.post({"provider": "free", **_nomodel(), "analysis_pass": pass_}, headers={})
    assert (r.status_code, error_of(r)) == (422, "invalid_request")


def test_tampered_passes_are_invalid() -> None:
    rig = free_tag_rig()
    pass_ = issue(rig)
    mac = pass_.split(".")[-1]
    cases = {
        "mac": _tamper(pass_, 5, mac[:-1] + ("0" if mac[-1] != "0" else "1")),
        "aud": _tamper(pass_, 1, "topics"),
        "expiry": _tamper(pass_, 2, str(int(pass_.split(".")[2]) + 3600)),
        "client": _tamper(pass_, 3, "0" * len(pass_.split(".")[3])),
        "garbage": "abc",
        "too-long": pass_ + "a" * 300,
    }
    for name, value in cases.items():
        r = rig.free_tag(pass_=value)
        assert (r.status_code, error_of(r)) == (403, "analysis_pass_invalid"), name


def test_pass_expires_after_30_minutes() -> None:
    rig = free_tag_rig()
    pass_ = issue(rig)
    rig.clock.now += 1799
    assert rig.free_tag(pass_=pass_).status_code == 200
    rig.clock.now += 2
    r = rig.free_tag(pass_=pass_)
    assert (r.status_code, error_of(r)) == (403, "analysis_pass_expired")


def test_new_app_instance_refuses_old_passes() -> None:
    pass_ = issue(free_tag_rig())
    new = free_tag_rig()
    r = new.free_tag(pass_=pass_)
    assert (r.status_code, error_of(r)) == (403, "analysis_pass_invalid")
    assert new.tags.seen == []


def test_pass_is_refused_for_another_client_and_valid_inside_the_same_ipv6_48() -> None:
    rig = free_tag_rig()
    pass_ = issue(rig, ip="2001:db8:abcd:1::1")
    assert rig.free_tag(pass_=pass_, ip="2001:db8:abcd:7::9").status_code == 200
    r = rig.free_tag(pass_=pass_, ip="2001:db8:abce:1::1")
    assert (r.status_code, error_of(r)) == (403, "analysis_pass_invalid")
    other = rig.free_tag(pass_=pass_, ip=IP_B)
    assert (other.status_code, error_of(other)) == (403, "analysis_pass_invalid")


def test_new_turnstile_solve_replaces_the_live_pass_of_the_client() -> None:
    rig = free_tag_rig()
    old = issue(rig, token="t1")
    new = issue(rig, token="t2")
    r = rig.free_tag(pass_=old)
    assert (r.status_code, error_of(r)) == (403, "analysis_pass_invalid")
    assert rig.free_tag(pass_=new).status_code == 200


def test_full_table_refuses_issuing_with_503() -> None:
    rig = free_tag_rig(free_pass_max_entries=1)
    issue(rig, ip=IP_A)
    r = rig.free_tag(token="t2", ip=IP_B)
    assert (r.status_code, error_of(r)) == (503, "analysis_pass_unavailable")


def test_tag_endpoint_refuses_a_topics_pass() -> None:
    topics_pass = free_trig().free_call("propose").json()["free_pass"]
    rig = free_tag_rig()
    r = rig.free_tag(pass_=topics_pass)
    assert (r.status_code, error_of(r)) == (403, "analysis_pass_invalid")
    assert rig.tags.seen == []


def test_topic_endpoints_refuse_an_analysis_pass() -> None:
    rig = free_tag_rig()
    pass_ = issue(rig)
    r = rig.post(
        {"provider": "free", "topic": topic_body()["topic"]},
        headers={"X-Free-Pass": pass_},
        path=PROPOSE,
    )
    assert (r.status_code, error_of(r)) == (403, "free_pass_invalid")


def test_provider_check_refuses_the_pass_header_and_an_analysis_pass_as_token() -> None:
    rig = free_tag_rig()
    pass_ = issue(rig)
    r = rig.post({"provider": "free"}, headers={PASS_HEADER: pass_}, path=CHECK)
    assert (r.status_code, error_of(r)) == (422, "unexpected_analysis_pass")
    r2 = rig.post({"provider": "free", "turnstile_token": pass_}, headers={}, path=CHECK)
    assert (r2.status_code, error_of(r2)) == (403, "turnstile_failed")


# --- quota ----------------------------------------------------------------------------------


def test_starting_an_analysis_charges_the_free_quota_once_per_pass() -> None:
    rig = free_tag_rig(free_calls_per_ip_per_day=2)
    pass_ = issue(rig, token="t1")
    for _ in range(4):
        assert rig.free_tag(pass_=pass_).status_code == 200
    issue(rig, token="t2")  # second analysis start
    r = rig.free_tag(token="t3")
    assert (r.status_code, error_of(r)) == (429, "free_quota_exhausted")
    assert "retry-after" in r.headers


# --- size -----------------------------------------------------------------------------------


def test_free_document_over_30_pages_of_3000_characters_is_422_free_too_large() -> None:
    rig = free_tag_rig()
    r = rig.free_tag(tag_body(*big_doc(91000, "alpha")))
    assert (r.status_code, error_of(r)) == (422, "free_too_large")
    assert rig.tags.seen == []


def test_free_total_size_over_two_documents_is_counted_by_the_pass() -> None:
    rig = free_tag_rig()
    pass_ = issue(rig, token="t1")
    assert (
        rig.free_tag(tag_body(*big_doc(20000, "alpha"), label="A"), pass_=pass_).status_code == 200
    )
    r = rig.free_tag(tag_body(*big_doc(75000, "beta"), label="B"), pass_=pass_)
    assert (r.status_code, error_of(r)) == (422, "free_too_large")


def test_pass_records_at_most_two_document_digests() -> None:
    rig = free_tag_rig()
    pass_ = issue(rig)  # document 1 (default texts)
    assert rig.free_tag(tag_body("Second document text."), pass_=pass_).status_code == 200
    r = rig.free_tag(tag_body("Third document text."), pass_=pass_)
    assert (r.status_code, error_of(r)) == (422, "too_many_documents")


def test_re_tagging_a_recorded_document_is_allowed() -> None:
    rig = free_tag_rig()
    pass_ = issue(rig)
    for _ in range(3):
        assert rig.free_tag(pass_=pass_).status_code == 200
    assert rig.free_tag(tag_body("Second document text."), pass_=pass_).status_code == 200


# --- caps -----------------------------------------------------------------------------------


def test_call_cap_refuses_a_request_whose_worst_case_does_not_fit_before_any_call() -> None:
    rig = free_tag_rig(analysis_pass_max_calls=3)  # one batch: 2 tag + 2 check calls worst case
    r = rig.free_tag()
    assert (r.status_code, error_of(r)) == (403, "analysis_pass_exhausted")
    assert rig.tags.seen == []


def test_call_cap_bounds_the_total_number_of_ai_calls_of_a_pass() -> None:
    rig = free_tag_rig(LOW, analysis_pass_max_calls=4)
    pass_ = issue(rig)
    codes = [rig.free_tag(pass_=pass_).status_code for _ in range(5)]
    assert 403 in codes
    assert len(rig.tags.calls) <= 4


def test_neuron_cap_refuses_before_any_call() -> None:
    rig = free_tag_rig(analysis_pass_max_neurons=1)
    r = rig.free_tag()
    assert (r.status_code, error_of(r)) == (403, "analysis_pass_exhausted")
    assert rig.tags.seen == []


def test_neurons_are_settled_from_reported_usage_so_many_small_calls_fit() -> None:
    rig = free_tag_rig(analysis_pass_max_neurons=3000, analysis_pass_max_calls=400)
    pass_ = issue(rig)
    for n in range(8):
        r = rig.free_tag(pass_=pass_)
        assert r.status_code == 200, (n, r.text)


# --- review findings: settlement without reported usage -------------------------------------


def _hung_free_rig() -> tuple[TagRig, GateTransport]:
    gate = GateTransport()  # never answers: every call ends by timeout
    rig = TagRig()
    rig.app = create_app(
        Settings(
            environment="development",
            topics_catalog_dir=CATALOG_OK,
            tag_per_minute=1000,
            tag_per_day=10000,
            tag_call_deadline_seconds=0.05,
            free_neuron_budget=9999,
            analysis_pass_max_neurons=9999,
            analysis_pass_max_calls=100000,
            **FREE_ENV,
        ),
        provider_transport=gate,
        turnstile_transport=rig.turnstile,
        clock=rig.clock,
    )
    return rig, gate


def test_calls_that_time_out_are_settled_at_the_worst_case_not_zero() -> None:
    rig, _ = _hung_free_rig()
    pass_ = issue(rig)
    codes = [rig.free_tag(pass_=pass_) for _ in range(40)]
    refused = [r for r in codes if r.status_code in (403, 429)]
    assert refused, "timeouts must consume the free Neuron budget"
    assert {error_of(r) for r in refused} <= {"free_quota_exhausted", "analysis_pass_exhausted"}


def test_hard_provider_error_does_not_settle_zero_when_calls_were_made() -> None:
    rig = free_tag_rig(analysis_pass_max_neurons=9999, analysis_pass_max_calls=100000)
    pass_ = issue(rig)
    rig.tags.tag_fn = lambda ids, n: 401
    codes = [rig.free_tag(pass_=pass_) for _ in range(40)]
    assert any(r.status_code in (403, 429) for r in codes)
    assert any(r.status_code == 401 for r in codes)
