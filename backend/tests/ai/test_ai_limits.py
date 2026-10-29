"""S6-T2 AC3: no redirects, response cap, timeouts, per-request SDK clients, guard."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from typing import Any

import anthropic
import httpcore2
import httpx2
import openai
import pytest
from app.ai.factory import provider_for
from app.ai.port import AIError
from app.ai.presets import PresetId
from pydantic import SecretStr

from tests.ai.helpers import (
    KEY,
    MIB,
    FakeUpstream,
    failure,
    make_provider,
    make_request,
    model_reply,
    run,
)

PRESETS = [PresetId.ANTHROPIC, PresetId.OPENAI]
OPS = ["check", "complete_json"]
JSON = {"content-type": "application/json"}


# --- redirects --------------------------------------------------------------------------------


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_redirect_cross_host_is_refused_and_not_followed(
    preset: PresetId, op: str, status: int
) -> None:
    def reply(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, headers={"location": "https://evil.example.net/steal"})

    provider, upstream = make_provider(preset, upstream=FakeUpstream(reply))

    error = failure(provider, op)

    assert error.code == "provider_bad_response"
    assert len(upstream.seen) == 1
    assert {s.host for s in upstream.seen} == {upstream.seen[0].host}
    assert "evil.example.net" not in upstream.seen[0].url


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("preset", PRESETS)
def test_redirect_to_the_same_host_is_refused_too(preset: PresetId, op: str) -> None:
    def reply(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(307, headers={"location": str(request.url) + "/again"})

    provider, upstream = make_provider(preset, upstream=FakeUpstream(reply))

    assert failure(provider, op).code == "provider_bad_response"
    assert len(upstream.seen) == 1


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("status", [300, 304])
def test_redirect_3xx_without_a_location_is_a_bad_response(
    preset: PresetId, op: str, status: int
) -> None:
    provider, _ = make_provider(
        preset, upstream=FakeUpstream(lambda request: httpx2.Response(status))
    )

    assert failure(provider, op).code == "provider_bad_response"


@pytest.mark.parametrize("preset", PRESETS)
def test_redirect_never_carries_the_key_to_the_second_host(preset: PresetId) -> None:
    hosts: list[str] = []

    def reply(request: httpx2.Request) -> httpx2.Response:
        hosts.append(request.url.host)
        if request.url.host != "evil.example.net":
            return httpx2.Response(307, headers={"location": "https://evil.example.net/x"})
        return model_reply()(request)

    provider, _ = make_provider(preset, upstream=FakeUpstream(reply))

    failure(provider, "check")

    assert "evil.example.net" not in hosts


# --- response cap -----------------------------------------------------------------------------


def _big(size: int) -> bytes:
    return b'{"pad":"' + b"x" * size + b'"}'


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("preset", PRESETS)
def test_cap_response_over_2_mib_with_a_length_header_fails_closed(
    preset: PresetId, op: str
) -> None:
    provider, _ = make_provider(
        preset,
        upstream=FakeUpstream(
            lambda r: httpx2.Response(200, content=_big(2 * MIB + 1), headers=JSON)
        ),
    )

    assert failure(provider, op).code == "provider_bad_response"


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("preset", PRESETS)
def test_cap_streamed_response_stops_reading_after_the_cap(preset: PresetId, op: str) -> None:
    sent = [0]
    total = 8 * MIB

    async def body() -> AsyncIterator[bytes]:
        yield b'{"pad":"'
        while sent[0] < total:
            sent[0] += 65536
            yield b"x" * 65536
        yield b'"}'

    provider, _ = make_provider(
        preset, upstream=FakeUpstream(lambda r: httpx2.Response(200, content=body(), headers=JSON))
    )

    assert failure(provider, op).code == "provider_bad_response"
    assert sent[0] < total
    assert sent[0] <= 2 * MIB + 4 * 65536


@pytest.mark.parametrize("preset", PRESETS)
def test_cap_error_body_over_the_cap_is_still_an_ai_error(preset: PresetId) -> None:
    provider, _ = make_provider(
        preset,
        upstream=FakeUpstream(lambda r: httpx2.Response(500, content=_big(3 * MIB), headers=JSON)),
    )

    assert failure(provider, "check").code in {"provider_bad_response", "provider_unavailable"}


@pytest.mark.parametrize("preset", PRESETS)
def test_cap_response_of_one_mib_is_accepted(preset: PresetId) -> None:
    text = '{"pad": "' + "x" * MIB + '"}'
    provider, _ = make_provider(preset, upstream=FakeUpstream(model_reply(text)))

    result: Any = run(provider, "complete_json")

    assert len(result["pad"]) == MIB


# --- timeouts ---------------------------------------------------------------------------------


@pytest.mark.parametrize("preset", PRESETS)
def test_timeouts_check_uses_connect_5_and_at_most_20_seconds(preset: PresetId) -> None:
    provider, upstream = make_provider(preset)

    run(provider, "check")
    timeout = upstream.seen[0].timeout

    assert timeout["connect"] == 5
    assert 0 < (timeout["read"] or 0) <= 20


@pytest.mark.parametrize("preset", PRESETS)
def test_timeouts_complete_json_uses_connect_5_and_at_most_120_seconds(preset: PresetId) -> None:
    provider, upstream = make_provider(preset)

    run(provider, "complete_json")
    timeout = upstream.seen[0].timeout

    assert timeout["connect"] == 5
    assert 20 < (timeout["read"] or 0) <= 120


# --- one SDK client per request ---------------------------------------------------------------


def _spy(monkeypatch: pytest.MonkeyPatch, cls: type) -> list[Any]:
    created: list[Any] = []
    original = cls.__init__

    def init(self: Any, *args: Any, **kwargs: Any) -> None:
        created.append(self)
        original(self, *args, **kwargs)

    monkeypatch.setattr(cls, "__init__", init)
    return created


@pytest.mark.parametrize(
    ("preset", "cls"),
    [(PresetId.ANTHROPIC, anthropic.AsyncAnthropic), (PresetId.OPENAI, openai.AsyncOpenAI)],
)
@pytest.mark.parametrize("op", OPS)
def test_client_is_built_per_request_and_closed_afterwards(
    monkeypatch: pytest.MonkeyPatch, preset: PresetId, cls: type, op: str
) -> None:
    created = _spy(monkeypatch, cls)
    provider, _ = make_provider(preset)
    assert created == []  # nothing is built, nothing holds the key, before a request

    run(provider, op)
    first = list(created)
    run(provider, op)
    second = [c for c in created if c not in first]

    assert first
    assert second
    assert all(c.is_closed() for c in created)


@pytest.mark.parametrize(
    ("preset", "cls"),
    [(PresetId.ANTHROPIC, anthropic.AsyncAnthropic), (PresetId.OPENAI, openai.AsyncOpenAI)],
)
def test_client_is_closed_after_a_failed_request_too(
    monkeypatch: pytest.MonkeyPatch, preset: PresetId, cls: type
) -> None:
    created = _spy(monkeypatch, cls)
    provider, _ = make_provider(preset, upstream=FakeUpstream(lambda r: httpx2.Response(500)))

    with pytest.raises(AIError):
        run(provider, "check")

    assert created
    assert all(c.is_closed() for c in created)


@pytest.mark.parametrize(
    ("preset", "cls"),
    [(PresetId.ANTHROPIC, anthropic.AsyncAnthropic), (PresetId.OPENAI, openai.AsyncOpenAI)],
)
def test_client_has_no_retries_and_an_explicit_base_url(
    monkeypatch: pytest.MonkeyPatch, preset: PresetId, cls: type
) -> None:
    created = _spy(monkeypatch, cls)
    provider, _ = make_provider(preset)

    run(provider, "check")

    assert created[0].max_retries == 0
    assert str(created[0].base_url).startswith(
        "https://api.anthropic.com" if preset is PresetId.ANTHROPIC else "https://api.openai.com/v1"
    )


@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("status", [429, 500, 503])
def test_client_does_not_retry_retryable_statuses(preset: PresetId, status: int) -> None:
    provider, upstream = make_provider(
        preset,
        upstream=FakeUpstream(lambda r: httpx2.Response(status, headers={"retry-after": "0"})),
    )

    with pytest.raises(AIError):
        run(provider, "complete_json")

    assert len(upstream.seen) == 1


@pytest.mark.parametrize("preset", PRESETS)
def test_client_does_not_retry_a_connection_error(preset: PresetId) -> None:
    def reply(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("x")

    provider, upstream = make_provider(preset, upstream=FakeUpstream(reply))

    with pytest.raises(AIError):
        run(provider, "check")

    assert len(upstream.seen) == 1


def test_client_requests_of_two_providers_do_not_share_a_key() -> None:
    first, up_1 = make_provider(PresetId.OPENAI, key="sk-first-111")
    second, up_2 = make_provider(PresetId.OPENAI, key="sk-second-222")

    run(first, "check")
    run(second, "check")

    assert up_1.seen[0].headers["authorization"] == "Bearer sk-first-111"
    assert up_2.seen[0].headers["authorization"] == "Bearer sk-second-222"


# --- the production path uses the guard -------------------------------------------------------


@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("op", OPS)
def test_guard_without_a_transport_refuses_a_host_that_resolves_to_loopback(
    monkeypatch: pytest.MonkeyPatch, preset: PresetId, op: str
) -> None:
    answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
    connects: list[str] = []

    async def fake_loop_getaddrinfo(self: object, host: str, port: object, **kw: object) -> Any:
        return answer

    def fake_getaddrinfo(host: str, port: object, *args: object, **kw: object) -> Any:
        return answer

    async def refuse_connect(self: object, *args: object, **kw: object) -> Any:
        connects.append("connect")
        raise AssertionError

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake_loop_getaddrinfo)
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(httpcore2.AnyIOBackend, "connect_tcp", refuse_connect)
    from httpcore2._backends.auto import AutoBackend  # noqa: PLC0415 - private, patched on purpose

    monkeypatch.setattr(AutoBackend, "connect_tcp", refuse_connect)
    provider = provider_for(preset, "test-model-1", SecretStr(KEY))

    async def go() -> None:
        if op == "check":
            await provider.check()
        else:
            await provider.complete_json(make_request())

    with pytest.raises(AIError) as info:
        asyncio.run(go())

    assert info.value.code == "provider_blocked_host"
    assert connects == []
