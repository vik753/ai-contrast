"""S6-T2 AC3: SDK environment variables have no effect (ADR 0016 point 3).

Every variable is set to a canary. The wire, the logs and the span recorder show no effect.
A control test shows that the recorder sees the spans of a default Anthropic client.
"""

from __future__ import annotations

import asyncio

import anthropic
import httpx2
import pytest
from app.ai.presets import PresetId

from tests.ai.helpers import KEY, FakeUpstream, make_provider, record_spans, run, tap_logs

C = "envcanary5e2b"
ENV = {
    "ANTHROPIC_BASE_URL": f"https://anthropic.{C}.example",
    "OPENAI_BASE_URL": f"https://openai.{C}.example/v1",
    "OPENAI_ORG_ID": f"org-{C}",
    "OPENAI_PROJECT_ID": f"proj_{C}",
    "ANTHROPIC_CUSTOM_HEADERS": f"X-Env-Canary: {C}",
    "OPENAI_CUSTOM_HEADERS": f"X-Env-Canary: {C}",
    "ANTHROPIC_LOG": "debug",
    "OPENAI_LOG": "debug",
    "ANTHROPIC_OPEN_TELEMETRY": "true",
    "ANTHROPIC_OPEN_TELEMETRY_TRACES_CONTENT_MODE": "content",
    "ANTHROPIC_OPEN_TELEMETRY_TRACES_MAX_CONTENT_BYTES": "100000",
    "ANTHROPIC_OPEN_TELEMETRY_PROPAGATION": "true",
    "ANTHROPIC_API_KEY": f"sk-ant-{C}",
    "ANTHROPIC_AUTH_TOKEN": f"tok-{C}",
    "OPENAI_API_KEY": f"sk-{C}",
}
HEADERS_THAT_MUST_NOT_APPEAR = {
    "openai-organization",
    "openai-project",
    "x-env-canary",
    "traceparent",
    "tracestate",
    "baggage",
}
CASES = [
    (PresetId.ANTHROPIC, "api.anthropic.com"),
    (PresetId.OPENAI, "api.openai.com"),
]
OPS = ["check", "complete_json"]


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)


@pytest.mark.usefixtures("env")
@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize(("preset", "host"), CASES)
def test_env_canaries_do_not_change_host_or_headers_on_the_wire(
    preset: PresetId, host: str, op: str
) -> None:
    provider, upstream = make_provider(preset)

    run(provider, op)
    seen = upstream.seen[0]

    assert [s.host for s in upstream.seen] == [host]
    assert C not in seen.everything.lower()
    assert HEADERS_THAT_MUST_NOT_APPEAR.isdisjoint(seen.headers)
    assert KEY not in seen.without_auth()


@pytest.mark.usefixtures("env")
@pytest.mark.parametrize("op", OPS)
def test_env_anthropic_auth_uses_the_given_key_only(op: str) -> None:
    provider, upstream = make_provider(PresetId.ANTHROPIC)

    run(provider, op)
    headers = upstream.seen[0].headers

    assert headers["x-api-key"] == KEY
    assert "authorization" not in headers


@pytest.mark.usefixtures("env")
@pytest.mark.parametrize("op", OPS)
def test_env_openai_auth_uses_the_given_key_only(op: str) -> None:
    provider, upstream = make_provider(PresetId.OPENAI)

    run(provider, op)
    headers = upstream.seen[0].headers

    assert headers["authorization"] == f"Bearer {KEY}"
    assert "x-api-key" not in headers


@pytest.mark.usefixtures("env")
@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize(("preset", "host"), CASES)
def test_env_canaries_do_not_reach_the_logs(preset: PresetId, host: str, op: str) -> None:
    provider, _ = make_provider(preset)

    with tap_logs() as tap:
        run(provider, op)

    assert C not in tap.text.lower()
    assert KEY not in tap.text
    assert "Request options" not in tap.text  # SDK debug dump of the request


@pytest.mark.usefixtures("env")
@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize(("preset", "host"), CASES)
def test_env_telemetry_records_no_span(
    monkeypatch: pytest.MonkeyPatch, preset: PresetId, host: str, op: str
) -> None:
    spans = record_spans(monkeypatch)
    provider, _ = make_provider(preset)

    run(provider, op)

    assert spans == []


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize(("preset", "host"), CASES)
def test_telemetry_records_no_span_without_any_env(
    monkeypatch: pytest.MonkeyPatch, preset: PresetId, host: str, op: str
) -> None:
    spans = record_spans(monkeypatch)
    provider, upstream = make_provider(preset)

    run(provider, op)

    assert spans == []
    assert "traceparent" not in upstream.seen[0].headers


def test_control_span_recorder_sees_a_default_anthropic_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spans = record_spans(monkeypatch)
    upstream = FakeUpstream()

    async def go() -> None:
        client = anthropic.AsyncAnthropic(
            api_key="k",
            base_url="https://api.anthropic.com",
            http_client=httpx2.AsyncClient(transport=upstream),
            max_retries=0,
        )
        await client.messages.create(
            model="m", max_tokens=5, messages=[{"role": "user", "content": "hi"}]
        )

    asyncio.run(go())

    assert spans
