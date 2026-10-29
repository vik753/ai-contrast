"""Adapter on the official ``anthropic`` SDK, Messages API (ADR 0016 point 3).

A new SDK client per call, on our guarded client; ``max_retries=0``; explicit ``base_url``;
tracing off; no tools; the key goes only to the SDK constructor.
"""

from __future__ import annotations

import asyncio

import anthropic
from pydantic import SecretStr

from app.ai.adapters._common import (
    CHECK_TIMEOUT_SECONDS,
    COMPLETE_TIMEOUT_SECONDS,
    CONNECT_TIMEOUT_SECONDS,
    _bad_response,
    _error_for,
    _load_object,
    _model_json,
    _quiet_sdk_loggers,
)
from app.ai.port import AIRequest, CheckResult, ModelJson
from app.ai.prompting import CHECK_MAX_TOKENS, CHECK_PROBE, build_messages
from app.net.ai_client import AITransport, ai_client

_quiet_sdk_loggers()


def _text_of(payload: dict[str, object]) -> str:
    content = payload.get("content")
    if not isinstance(content, list):
        _bad_response()
    parts = [
        block["text"]
        for block in content
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block["text"], str)
    ]
    if not parts:
        _bad_response()
    return "".join(parts)


class AnthropicAdapter:
    def __init__(
        self, model: str, key: SecretStr, base_url: str, transport: AITransport | None = None
    ) -> None:
        self._model = model
        self._key = key
        self._base_url = base_url
        self._transport = transport

    async def _post(
        self,
        messages: list[anthropic.types.MessageParam],
        system: str | anthropic.Omit,
        max_tokens: int,
        timeout: float,
    ) -> dict[str, object]:
        _quiet_sdk_loggers()
        try:
            async with asyncio.timeout(timeout):
                http = ai_client(
                    connect_timeout=CONNECT_TIMEOUT_SECONDS,
                    read_timeout=timeout,
                    transport=self._transport,
                )
                client = anthropic.AsyncAnthropic(
                    api_key=self._key.get_secret_value(),
                    base_url=self._base_url,
                    timeout=anthropic.Timeout(timeout, connect=CONNECT_TIMEOUT_SECONDS),
                    max_retries=0,
                    http_client=http,
                    open_telemetry={"traces": {"enabled": False}, "propagation": False},
                )
                try:
                    raw = await client.messages.with_raw_response.create(
                        model=self._model,
                        max_tokens=max_tokens,
                        messages=messages,
                        system=system,
                    )
                    return _load_object(await raw.read())
                finally:
                    await client.close()
                    await http.aclose()
        except Exception as error:  # noqa: BLE001 - every error becomes an AIError (T1)
            raise _error_for(error) from None

    async def check(self) -> CheckResult:
        await self._post(
            [{"role": "user", "content": CHECK_PROBE}],
            anthropic.omit,
            CHECK_MAX_TOKENS,
            CHECK_TIMEOUT_SECONDS,
        )
        return CheckResult(ok=True)

    async def complete_json(self, request: AIRequest) -> ModelJson:
        messages = build_messages(request)
        system = messages[0].content
        payload = await self._post(
            [{"role": "user", "content": m.content} for m in messages[1:]],
            system,
            request.max_tokens,
            COMPLETE_TIMEOUT_SECONDS,
        )
        return _model_json(_text_of(payload))
