"""S7-T2 AC1: strict output schemas, caps, one repair attempt, ai_bad_output, AIError mapping."""

from __future__ import annotations

import json

import httpx2
import pytest

from tests.ai.helpers import error_reply
from tests.topic_ai.helpers import (
    EXPAND,
    PROPOSE,
    SUGGEST,
    TRig,
    attr,
    attr_out,
    canary,
    error_of,
    suggest_body,
    suggest_out,
    syn_out,
    topic_body,
)

CASES = {
    "suggest": (SUGGEST, suggest_body),
    "propose": (PROPOSE, topic_body),
    "expand": (EXPAND, topic_body),
}


def _good(kind: str) -> str:
    return {
        "suggest": suggest_out(("Roadside help", "Towing")),
        "propose": attr_out(attr()),
        "expand": syn_out(en=["towing"]),
    }[kind]


def _call(rig: TRig, kind: str) -> httpx2.Response:
    path, body = CASES[kind]
    return rig.post(path, body())


@pytest.mark.parametrize("kind", list(CASES))
def test_valid_output_makes_one_upstream_call_and_200(kind: str) -> None:
    rig = TRig(_good(kind))
    assert _call(rig, kind).status_code == 200
    assert len(rig.upstream.seen) == 1


BAD = {
    "suggest": [
        "not json at all",
        json.dumps({"topics": [], "extra": 1}),
        json.dumps({"topics": [{"name": "A"}]}),
        suggest_out(*[(f"Topic {chr(97 + i)}", "d") for i in range(9)]),
        json.dumps({"topics": [{"name": "A", "description": "d", "x": 1}]}),
    ],
    "propose": [
        "[]",
        json.dumps({"attributes": []}),
        attr_out(*[attr(f"attr_{chr(97 + i)}x", f"Label {chr(97 + i)}") for i in range(13)]),
        attr_out(attr(direction="lower_better")),
        attr_out(attr(type="enum", values=[f"Value {chr(97 + i)}" for i in range(31)])),
    ],
    "expand": [
        "oops",
        json.dumps({"synonyms_en": ["towing"]}),
        syn_out(en=[f"word{chr(97 + i % 26)}{chr(97 + i // 26)}x" for i in range(41)]),
        json.dumps({**json.loads(syn_out()), "synonyms_de": []}),
    ],
}


@pytest.mark.parametrize(("kind", "bad"), [(k, b) for k, items in BAD.items() for b in items])
def test_bad_output_twice_returns_502_ai_bad_output_after_exactly_two_calls(
    kind: str, bad: str
) -> None:
    rig = TRig(bad)
    response = _call(rig, kind)
    assert response.status_code == 502
    assert error_of(response) == "ai_bad_output"
    assert len(rig.upstream.seen) == 2


@pytest.mark.parametrize("kind", list(CASES))
def test_one_bad_output_then_good_output_is_repaired_with_200(kind: str) -> None:
    rig = TRig("not json", _good(kind))
    assert _call(rig, kind).status_code == 200
    assert len(rig.upstream.seen) == 2


@pytest.mark.parametrize("kind", list(CASES))
def test_repair_request_never_contains_the_previous_model_output(kind: str) -> None:
    marker = canary("Prevout")
    bad = {
        "suggest": json.dumps({"topics": [{"name": marker, "description": marker}], "x": 1}),
        "propose": json.dumps({"attributes": [{"id": "abc_def", "label": marker}], "x": 1}),
        "expand": json.dumps({"synonyms_en": [marker], "x": 1}),
    }[kind]
    rig = TRig(bad, _good(kind))
    _call(rig, kind)
    first, second = rig.wire
    assert marker in bad
    assert marker not in second
    assert marker not in first


def test_repair_request_keeps_the_same_document_and_adds_no_other_document() -> None:
    rig = TRig("garbage", suggest_out(("Roadside help", "Towing")))
    rig.post(SUGGEST, suggest_body("1. The Insurer pays within thirty days."))
    first, second = rig.wire
    assert "The Insurer pays within thirty days" in first
    assert "The Insurer pays within thirty days" in second


def test_repair_request_differs_from_the_first_request() -> None:
    rig = TRig("garbage", attr_out(attr()))
    rig.post(PROPOSE, topic_body())
    first, second = rig.wire
    assert first != second


@pytest.mark.parametrize("status", [401, 404, 429, 400, 500])
def test_provider_error_maps_to_the_ai_error_code(status: int) -> None:
    rig = TRig()
    rig.upstream.reply = error_reply(status)
    response = rig.post(PROPOSE, topic_body())
    expected = {
        401: (401, "provider_auth_failed"),
        404: (404, "provider_model_not_found"),
        429: (429, "provider_rate_limited"),
        400: (400, "provider_bad_request"),
        500: (502, "provider_unavailable"),
    }[status]
    assert (response.status_code, error_of(response)) == expected
