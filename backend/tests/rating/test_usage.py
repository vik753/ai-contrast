"""S9-T2 AC3: typed optional ``usage`` on the port (replaces ``getattr`` in the free pass)."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import httpx2

from app.ai.port import AIProvider, AIRequest, ReasoningEffort, Usage
from app.ai.presets import PresetId
from app.limits.free import reported_neurons, usage_neurons
from tests.ai.helpers import (
    FakeUpstream,
    Reply,
    Verdict,
    first_template,
    make_document,
    make_provider,
    model_reply,
    run,
)

from .helpers import FakeProvider

APP = Path(__file__).resolve().parents[2] / "app"


def _request(effort: ReasoningEffort | None = None) -> AIRequest:
    return AIRequest(
        template=first_template(),
        document=make_document(),
        schema=Verdict,
        max_tokens=256,
        effort=effort,
    )


def _openai_reply(usage: dict[str, int] | None) -> Reply:
    def reply(request: httpx2.Request) -> httpx2.Response:
        response = model_reply()(request)
        payload = json.loads(response.content)
        if usage is None:
            payload.pop("usage", None)
        else:
            payload["usage"] = usage
        return httpx2.Response(response.status_code, json=payload, headers=response.headers)

    return reply


def test_usage_is_a_frozen_pair_of_token_counts() -> None:
    usage = Usage(input_tokens=10, output_tokens=5)

    assert (usage.input_tokens, usage.output_tokens) == (10, 5)
    try:
        usage.input_tokens = 1  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("Usage is not frozen")  # noqa: TRY003


def test_usage_openai_compatible_adapter_reports_a_typed_usage() -> None:
    provider, _ = make_provider(
        PresetId.OPENAI,
        upstream=FakeUpstream(
            _openai_reply({"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150})
        ),
    )

    run(provider, "complete_json", _request())

    assert provider.usage == Usage(120, 30)


def test_usage_openai_compatible_adapter_without_usage_reports_none() -> None:
    provider, _ = make_provider(PresetId.OPENAI, upstream=FakeUpstream(_openai_reply(None)))

    run(provider, "complete_json", _request())

    assert provider.usage is None


def test_usage_anthropic_adapter_has_the_member() -> None:
    provider, _ = make_provider(PresetId.ANTHROPIC)

    assert provider.usage is None or isinstance(provider.usage, Usage)


def test_usage_fake_provider_satisfies_the_protocol() -> None:
    assert isinstance(FakeProvider(), AIProvider)


def test_usage_reported_neurons_reads_the_typed_value() -> None:
    provider = FakeProvider()
    provider.usage = Usage(1000, 500)  # type: ignore[assignment]

    assert reported_neurons(provider) == usage_neurons(1000, 500)


def test_usage_reported_neurons_without_usage_is_none() -> None:
    assert reported_neurons(FakeProvider()) is None


def test_usage_app_code_has_no_getattr_on_usage() -> None:
    found = []
    for path in sorted(APP.glob("**/*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == "usage"
            ):
                found.append(f"{path.relative_to(APP)}:{node.lineno}")
    assert found == []


def test_usage_openai_compatible_adapter_sends_the_reasoning_effort() -> None:
    provider, upstream = make_provider(PresetId.OPENAI)

    run(provider, "complete_json", _request(ReasoningEffort.HIGH))

    assert upstream.seen[0].json["reasoning_effort"] == "high"


def test_usage_openai_compatible_adapter_sends_no_effort_when_unset() -> None:
    provider, upstream = make_provider(PresetId.OPENAI)

    run(provider, "complete_json", _request())

    assert "reasoning_effort" not in upstream.seen[0].json
