"""S6-T2 AC3 (wire part), AC5 (model ID only in the body): what the adapters send.

Both adapters, ``check()`` and ``complete_json()``, against a recording ``httpx2.MockTransport``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from app.ai.port import CheckResult
from app.ai.presets import PresetId

from tests.ai.helpers import (
    KEY,
    TEXTS,
    FakeUpstream,
    Seen,
    make_provider,
    make_request,
    model_reply,
    run,
)

CASES = [
    (PresetId.ANTHROPIC, None, "api.anthropic.com", "/v1/messages"),
    (PresetId.OPENAI, None, "api.openai.com", "/v1/chat/completions"),
    (
        PresetId.GEMINI,
        None,
        "generativelanguage.googleapis.com",
        "/v1beta/openai/chat/completions",
    ),
    (PresetId.MISTRAL, None, "api.mistral.ai", "/v1/chat/completions"),
    (PresetId.OPENROUTER, None, "openrouter.ai", "/api/v1/chat/completions"),
    (PresetId.CUSTOM, "https://llm.example.com/v1", "llm.example.com", "/v1/chat/completions"),
]
IDS = [c[0].value for c in CASES]
OPS = ["check", "complete_json"]
TOOL_KEYS = {
    "tools",
    "tool_choice",
    "functions",
    "function_call",
    "parallel_tool_calls",
    "mcp_servers",
    "tool_resources",
    "container",
}
MODEL = "vendor/model-ZETA-7"


def _call(case: tuple[Any, ...], op: str, *, model: str = "test-model-1") -> Seen:
    preset, base_url, _, _ = case
    provider, upstream = make_provider(preset, model=model, base_url=base_url)
    run(provider, op)
    assert len(upstream.seen) == 1
    return upstream.seen[0]


def _keys(node: object) -> set[str]:
    if isinstance(node, dict):
        return set(node) | set().union(*(_keys(v) for v in node.values()))
    if isinstance(node, list):
        return set().union(*(_keys(v) for v in node)) if node else set()
    return set()


def _pieces(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            _pieces(c.get("text", "")) if isinstance(c, dict) else str(c) for c in content
        )
    return ""


def split_prompt(body: dict[str, Any]) -> tuple[str, str]:
    """(instruction text, data text) of a request body of either API."""
    instructions = [_pieces(body.get("system", ""))]
    data: list[str] = []
    for message in body["messages"]:
        target = instructions if message["role"] == "system" else data
        target.append(_pieces(message["content"]))
    return "\n".join(instructions), "\n".join(data)


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_wire_request_goes_to_the_preset_host_and_path_with_post(
    case: tuple[Any, ...], op: str
) -> None:
    seen = _call(case, op)

    assert seen.method == "POST"
    assert seen.host == case[2]
    assert seen.path == case[3]
    assert seen.url.startswith(f"https://{case[2]}/")


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_wire_key_is_only_in_the_auth_header(case: tuple[Any, ...], op: str) -> None:
    seen = _call(case, op)

    assert KEY not in seen.without_auth()
    if case[0] is PresetId.ANTHROPIC:
        assert seen.headers["x-api-key"] == KEY
        assert "authorization" not in seen.headers
    else:
        assert seen.headers["authorization"] == f"Bearer {KEY}"
        assert "x-api-key" not in seen.headers


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_wire_model_id_is_only_in_the_body(case: tuple[Any, ...], op: str) -> None:
    seen = _call(case, op, model=MODEL)
    outside_body = seen.url + " ".join(f"{k} {v}" for k, v in seen.headers.items())

    assert seen.json["model"] == MODEL
    assert MODEL not in outside_body
    assert "ZETA" not in outside_body


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_wire_body_has_no_tool_fields(case: tuple[Any, ...], op: str) -> None:
    assert _keys(_call(case, op).json) & TOOL_KEYS == set()


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_wire_body_is_not_a_streaming_request(case: tuple[Any, ...], op: str) -> None:
    assert not _call(case, op).json.get("stream")


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_wire_max_tokens_is_always_set(case: tuple[Any, ...], op: str) -> None:
    body = _call(case, op).json
    limit = body.get("max_tokens", body.get("max_completion_tokens"))

    assert isinstance(limit, int)
    assert limit > 0


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_wire_check_probe_asks_for_at_most_16_tokens(case: tuple[Any, ...]) -> None:
    body = _call(case, "check").json

    assert body.get("max_tokens", body.get("max_completion_tokens")) <= 16


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_wire_complete_json_uses_the_max_tokens_of_the_request(case: tuple[Any, ...]) -> None:
    provider, upstream = make_provider(case[0], base_url=case[1])

    run(provider, "complete_json", make_request(max_tokens=777))
    body = upstream.seen[0].json

    assert body.get("max_tokens", body.get("max_completion_tokens")) == 777


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_wire_check_sends_a_fixed_probe_that_no_caller_input_changes(case: tuple[Any, ...]) -> None:
    first, upstream_1 = make_provider(case[0], model="model-one", base_url=case[1], key="sk-one")
    second, upstream_2 = make_provider(case[0], model="model-two", base_url=case[1], key="sk-two")
    run(first, "check")
    run(second, "check")

    one = split_prompt(upstream_1.seen[0].json)
    two = split_prompt(upstream_2.seen[0].json)

    assert one == two
    assert one[1]  # a probe exists
    assert not any(text in one[1] for text in TEXTS)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_wire_check_returns_only_a_success_flag(case: tuple[Any, ...]) -> None:
    provider, _ = make_provider(case[0], base_url=case[1], upstream=FakeUpstream(model_reply("hi")))

    assert run(provider, "check") == CheckResult(ok=True)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_wire_complete_json_keeps_instructions_and_data_apart(case: tuple[Any, ...]) -> None:
    provider, upstream = make_provider(case[0], base_url=case[1])

    run(provider, "complete_json")
    instructions, data = split_prompt(upstream.seen[0].json)

    assert instructions
    assert all(text not in instructions for text in TEXTS)
    assert all(text in data for text in TEXTS)
    assert instructions not in data


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_wire_complete_json_returns_the_parsed_json_object(case: tuple[Any, ...]) -> None:
    payload = {"clauses": [{"id": "c1", "rating": "green"}], "n": 2, "nested": {"a": [1, None]}}
    provider, _ = make_provider(
        case[0], base_url=case[1], upstream=FakeUpstream(model_reply(json.dumps(payload)))
    )

    assert run(provider, "complete_json") == payload


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_wire_complete_json_sends_exactly_one_request(case: tuple[Any, ...]) -> None:
    provider, upstream = make_provider(case[0], base_url=case[1])

    run(provider, "complete_json")

    assert len(upstream.seen) == 1
