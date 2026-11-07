# ruff: noqa: E501, PLC0415, PT018
"""S9-T3 AC4/AC5: result_signature, analysis_version, log canary on every path."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import pytest

from tests.ai.helpers import tap_logs
from tests.analyze_api.helpers import (
    AnalyzeRig,
    free_analyze,
    free_analyze_rig,
    free_ready,
    rev,
    rfind,
    topic_out,
)
from tests.check.helpers import CF_TOKEN, CLIENT_KEY, TS_SECRET
from tests.tag_api.helpers import custom

CLAUSE = "Zcanaryclause: the deductible for each insured event is 5000 UAH."
TITLE = "Zcanarytitle subject"
MODEL_MARK = "ZcanaryModelOutput"
NEEDLES = (
    CLIENT_KEY,
    "Zcanary",
    MODEL_MARK,
    "deductible for each insured event",
    CF_TOKEN,
    TS_SECRET,
)


def _topics() -> dict[str, Any]:
    return {"custom": [custom(1, title=TITLE, desc="Zcanarydesc text", syn=["deductible"])]}


def _texts() -> tuple[str, ...]:
    return (CLAUSE, "Second clause about a penalty in writing.")


def _clean(tap: Any) -> None:
    for needle in NEEDLES:
        assert needle not in tap.text, needle


# --- result signature -------------------------------------------------------------------------------


def _done(rig: AnalyzeRig | None = None, **over: Any) -> dict[str, Any]:
    return (rig or AnalyzeRig()).run(**over).done


def test_done_carries_a_result_signature_and_an_analysis_version() -> None:
    d = _done()
    assert re.fullmatch(r"[0-9a-f]{64}", d["result_signature"])
    assert isinstance(d["analysis_version"], str) and d["analysis_version"]


def test_the_same_inputs_give_the_same_signature_and_version() -> None:
    rig = AnalyzeRig()
    body = rig.ready()
    a, b = rig.analyze(body).done, rig.analyze(body).done
    assert a["result_signature"] == b["result_signature"]
    assert a["analysis_version"] == b["analysis_version"]


def test_the_signature_binds_the_verified_result() -> None:
    rig = AnalyzeRig()
    body = rig.ready()
    first = rig.analyze(body).done["result_signature"]
    rig.up.topic_fn = lambda t, ids: topic_out([rfind("red")])
    assert rig.analyze(body).done["result_signature"] != first


def test_the_signature_binds_language_model_and_flags() -> None:
    rig = AnalyzeRig()
    body = rig.ready()
    base = rig.analyze(body).done["result_signature"]
    for change in (
        {"language": "uk"},
        {"model": "gpt-strong-2"},
        {"flags": ["not_read_material"]},
        {"flags": ["hidden_text_removed"]},
    ):
        assert rig.analyze({**body, **change}).done["result_signature"] != base, change


def test_the_signature_binds_the_side() -> None:
    from tests.analyze_api.helpers import ref

    rig = AnalyzeRig()
    a = rig.run(topics={"catalog": [ref("deductible", rig)]}).done
    tb = rig.base(side="insurer", topics={"catalog": [ref("deductible", rig, "insurer")]})
    b = rig.analyze(rig.body(tb, rig.tagged(tb))).done
    assert a["result_signature"] != b["result_signature"]


def test_the_signature_key_is_per_process() -> None:
    assert _done()["result_signature"] != _done()["result_signature"]


def test_the_rating_calls_use_the_given_strong_model() -> None:
    rig = AnalyzeRig()
    body = rig.ready()
    rig.analyze({**body, "model": "gpt-strong-2"})
    assert {c.model for c in rig.up.rates} == {"gpt-strong-2"}


def test_the_strong_model_of_the_preset_is_the_default() -> None:
    from app.ai.presets import MODEL_PAIRS, PresetId

    rig = AnalyzeRig()
    body = rig.ready()
    del body["model"]
    assert rig.analyze(body).status == 200
    assert {c.model for c in rig.up.rates} == {MODEL_PAIRS[PresetId("openai")].strong}


# --- log canary -------------------------------------------------------------------------------------


def test_logs_hold_no_key_clause_topic_or_model_text_on_a_good_run() -> None:
    rig = AnalyzeRig()
    rig.up.topic_fn = lambda t, ids: topic_out(
        [
            rfind(
                "green",
                explanation=MODEL_MARK,
                evidence=[rev("c1", "the deductible for each insured event is 5000 UAH")],
            )
        ]
    )
    body = rig.ready(*_texts(), topics=_topics())
    with tap_logs() as tap:
        r = rig.analyze(body)
    assert r.status == 200
    _clean(tap)
    assert "/api/analyze" in tap.text  # the access log line itself exists


def test_logs_hold_no_text_on_refusals() -> None:
    rig = AnalyzeRig()
    body = rig.ready(*_texts(), topics=_topics())
    bad_sig = {**body, "tagging": {**body["tagging"], "signature": "x" + CLAUSE}}
    with tap_logs() as tap:
        rig.analyze({**body, "extra": CLAUSE})
        rig.analyze(bad_sig)
        rig.analyze({**body, "language": MODEL_MARK})
        rig.analyze(body, headers={})
    _clean(tap)


@pytest.mark.parametrize("answer", [MODEL_MARK + " not json", 401, 503, 429])
def test_logs_hold_no_text_when_the_model_fails(answer: Any) -> None:
    rig = AnalyzeRig()
    rig.up.topic_fn = lambda t, ids: answer
    rig.up.other_fn = lambda ids: answer
    body = rig.ready(*_texts(), topics=_topics())
    with tap_logs() as tap:
        rig.analyze(body)
    _clean(tap)


def test_logs_hold_no_text_on_deadline_and_disconnect() -> None:
    from tests.analyze_api.test_limits import _disconnect_after_hang

    rig = AnalyzeRig(analysis_deadline_seconds=0.3)
    body = rig.ready(*_texts(), topics=_topics())
    rig.up.hang = True
    with tap_logs() as tap:
        rig.analyze(body)
        rig2 = AnalyzeRig()
        body2 = rig2.ready(*_texts(), topics=_topics())
        rig2.up.hang = True
        from tests.check.helpers import KEY_HEADER

        asyncio.run(_disconnect_after_hang(rig2, body2, KEY_HEADER))
    _clean(tap)


def test_logs_hold_no_text_or_secret_in_free_mode() -> None:
    rig = free_analyze_rig()
    tb = rig.base(*_texts(), topics=_topics())
    body, pass_ = free_ready(rig, tb=tb)
    rig.up.topic_fn = lambda t, ids: topic_out([rfind("yellow", explanation=MODEL_MARK)])
    with tap_logs() as tap:
        free_analyze(rig, body, pass_)
        free_analyze(rig, body, "garbage")
    _clean(tap)
    assert pass_ not in tap.text


def test_the_result_signature_and_tag_signature_are_not_logged() -> None:
    rig = AnalyzeRig()
    body = rig.ready()
    with tap_logs() as tap:
        r = rig.analyze(body)
    assert r.done["result_signature"] not in tap.text
    assert body["tagging"]["signature"] not in tap.text


def test_errors_never_echo_the_key_or_the_text() -> None:
    rig = AnalyzeRig()
    body = rig.ready(*_texts(), topics=_topics())
    replies = [
        rig.analyze({**body, "extra": CLIENT_KEY + CLAUSE}),
        rig.analyze({**body, "tagging": {**body["tagging"], "signature": CLAUSE}}),
    ]
    for r in replies:
        for needle in (CLIENT_KEY, "Zcanary"):
            assert needle not in r.raw


def test_the_wire_carries_the_key_only_in_the_auth_header_and_no_tools() -> None:
    rig = AnalyzeRig()
    rig.run()
    assert rig.up.rates
    for seen in rig.up.seen:
        assert CLIENT_KEY not in seen.url
        assert CLIENT_KEY not in seen.body.decode()
        sent = json.loads(seen.body)
        assert "tools" not in sent
        assert "tool_choice" not in sent
