"""S6-T2 AC4: every SDK and transport error becomes one of our codes (ADR 0016 point 3).

No SDK text, response body or request ID in the error or in the logs; ``raise ... from None``.
"""

from __future__ import annotations

import httpx2
import pytest
from app.ai.port import AIError, AIErrorCode
from app.ai.presets import PresetId

from app.net.guard import BlockedAddressError, BlockedHostError
from tests.ai.helpers import (
    BODY_CANARY,
    KEY,
    REQUEST_ID_CANARY,
    TEXTS,
    FakeUpstream,
    Reply,
    error_reply,
    failure,
    make_provider,
    model_reply,
    raising,
    tap_logs,
)

PRESETS = [PresetId.ANTHROPIC, PresetId.OPENAI]
OPS = ["check", "complete_json"]
LEAKS = [BODY_CANARY, REQUEST_ID_CANARY, KEY, "CANARY", *TEXTS]

STATUS = [
    (401, "provider_auth_failed"),
    (403, "provider_auth_failed"),
    (404, "provider_model_not_found"),
    (429, "provider_rate_limited"),
    (400, "provider_bad_request"),
    (422, "provider_bad_request"),
    (500, "provider_unavailable"),
    (502, "provider_unavailable"),
    (503, "provider_unavailable"),
    (504, "provider_unavailable"),
    (529, "provider_unavailable"),
]
TRANSPORT = [
    (httpx2.ConnectError("boom CANARY"), "provider_unavailable"),
    (httpx2.ConnectTimeout("boom CANARY"), "provider_unavailable"),
    (httpx2.ReadTimeout("boom CANARY"), "provider_unavailable"),
    (httpx2.WriteTimeout("boom CANARY"), "provider_unavailable"),
    (httpx2.PoolTimeout("boom CANARY"), "provider_unavailable"),
    (httpx2.ReadError("boom CANARY"), "provider_unavailable"),
    (httpx2.RemoteProtocolError("boom CANARY"), "provider_unavailable"),
    (BlockedAddressError("boom CANARY"), "provider_blocked_host"),
    (BlockedHostError("boom CANARY"), "provider_blocked_host"),
]


def _assert_clean(error: AIError, logs: str) -> None:
    visible = f"{error!s} {error!r} {error.args!r}"
    for leak in LEAKS:
        assert leak not in visible, leak
        assert leak not in logs, leak
    assert str(error) == error.code
    assert error.__cause__ is None
    assert error.__suppress_context__ is True


def _fail(preset: PresetId, op: str, reply: Reply) -> tuple[AIError, str, FakeUpstream]:
    provider, upstream = make_provider(preset, upstream=FakeUpstream(reply))
    with tap_logs() as tap:
        error = failure(provider, op)
    return error, tap.text, upstream


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize(("status", "code"), STATUS)
def test_error_http_status_maps_to_the_documented_code(
    preset: PresetId, op: str, status: int, code: str
) -> None:
    error, _, _ = _fail(preset, op, error_reply(status, {"retry-after": "1"}))

    assert error.code == code


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize(("status", "code"), STATUS)
def test_error_http_status_leaks_no_sdk_text_body_or_request_id(
    preset: PresetId, op: str, status: int, code: str
) -> None:
    error, logs, _ = _fail(preset, op, error_reply(status, {"retry-after": "1"}))

    _assert_clean(error, logs)


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize(("status", "code"), STATUS)
def test_error_http_status_is_not_retried(
    preset: PresetId, op: str, status: int, code: str
) -> None:
    _, _, upstream = _fail(preset, op, error_reply(status, {"retry-after": "0"}))

    assert len(upstream.seen) == 1


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize(
    ("exc", "code"), TRANSPORT, ids=lambda v: type(v).__name__ if isinstance(v, Exception) else v
)
def test_error_transport_failure_maps_to_the_documented_code(
    preset: PresetId, op: str, exc: Exception, code: str
) -> None:
    error, logs, upstream = _fail(preset, op, raising(exc))

    assert error.code == code
    assert len(upstream.seen) == 1
    _assert_clean(error, logs)


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("preset", PRESETS)
def test_error_unknown_exception_from_the_transport_still_becomes_an_ai_error(
    preset: PresetId, op: str
) -> None:
    error, logs, _ = _fail(preset, op, raising(RuntimeError("secret CANARY text")))

    assert error.code in {c.value for c in AIErrorCode}
    _assert_clean(error, logs)


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("preset", PRESETS)
def test_error_200_with_a_body_that_is_not_json_is_a_bad_response(
    preset: PresetId, op: str
) -> None:
    def reply(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            content=f"<html>{BODY_CANARY}</html>".encode(),
            headers={"content-type": "text/html"},
        )

    error, logs, _ = _fail(preset, op, reply)

    assert error.code == "provider_bad_response"
    _assert_clean(error, logs)


@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize(
    "text",
    [
        "",
        "hello CANARY",
        "[1, 2]",
        '"text"',
        "42",
        "null",
        '{"a": ',
        "{'a': 1}",
        "```json\nnot json\n```",
    ],
    ids=lambda t: repr(t)[:20],
)
def test_error_model_text_that_is_not_a_json_object_is_a_bad_response(
    preset: PresetId, text: str
) -> None:
    error, logs, _ = _fail(preset, "complete_json", model_reply(text))

    assert error.code == "provider_bad_response"
    _assert_clean(error, logs)


def test_error_openai_answer_without_choices_is_a_bad_response() -> None:
    def reply(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"id": "x", "object": "chat.completion", "choices": []})

    error, _, _ = _fail(PresetId.OPENAI, "complete_json", reply)

    assert error.code == "provider_bad_response"


def test_error_anthropic_answer_without_text_is_a_bad_response() -> None:
    def reply(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            json={
                "id": "m",
                "type": "message",
                "role": "assistant",
                "model": "x",
                "content": [],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 0},
            },
        )

    error, _, _ = _fail(PresetId.ANTHROPIC, "complete_json", reply)

    assert error.code == "provider_bad_response"


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("preset", PRESETS)
def test_error_success_path_writes_no_prompt_key_or_output_to_the_logs(
    preset: PresetId, op: str
) -> None:
    provider, _ = make_provider(
        preset, upstream=FakeUpstream(model_reply('{"ok": true, "x": "CANARY"}'))
    )

    from tests.ai.helpers import run  # noqa: PLC0415 - kept local: only this test needs it

    with tap_logs() as tap:
        run(provider, op)

    for leak in (KEY, "CANARY", *TEXTS):
        assert leak not in tap.text
