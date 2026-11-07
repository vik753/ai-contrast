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
    _code_for,
    _load_object,
    _model_json,
    _quiet_sdk_loggers,
)
from app.ai.port import AIError, AIErrorCode, AIRequest, CheckResult, ModelJson, Usage
from app.ai.prompting import CHECK_MAX_TOKENS, CHECK_PROBE, build_messages
from app.net.ai_client import AITransport, ai_client

_quiet_sdk_loggers()


def _text_of(payload: dict[str, object], *, require_text: bool) -> str:
    content = payload.get("content")
    if not isinstance(content, list):
        _bad_response()
    parts = [
        text
        for block in content
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(text := block.get("text"), str)
    ]
    if require_text and not parts:
        _bad_response()
    return "".join(parts)


MAX_TOKEN_COUNT = 10**9


class AnthropicAdapter:
    def __init__(
        self, model: str, key: SecretStr, base_url: str, transport: AITransport | None = None
    ) -> None:
        self._model = model
        self._key = key
        self._base_url = base_url
        self._transport = transport
        self._usage = (0, 0)
        self._usage_missing = False

    @property
    def usage(self) -> Usage | None:
        """Input and output tokens reported for all calls of this adapter, or ``None`` if any
        answer did not report them."""
        return None if self._usage_missing else Usage(*self._usage)

    def _record_usage(self, payload: dict[str, object]) -> None:
        usage = payload.get("usage")
        counts = (
            (usage.get("input_tokens"), usage.get("output_tokens"))
            if isinstance(usage, dict)
            else (None, None)
        )
        if (
            type(counts[0]) is not int
            or type(counts[1]) is not int
            or not (0 <= counts[0] <= MAX_TOKEN_COUNT and 0 <= counts[1] <= MAX_TOKEN_COUNT)
        ):
            self._usage_missing = True
        else:
            self._usage = (self._usage[0] + counts[0], self._usage[1] + counts[1])

    async def _post(
        self,
        messages: list[anthropic.types.MessageParam],
        system: str | anthropic.Omit,
        max_tokens: int,
        timeout: float,
    ) -> dict[str, object]:
        _quiet_sdk_loggers()
        code = AIErrorCode.PROVIDER_UNAVAILABLE
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
            code = _code_for(error)
        # Raised outside the handler: the error keeps no cause and no context (the SDK error
        # holds the request with the key header).
        raise AIError(code)

    async def check(self) -> CheckResult:
        payload = await self._post(
            [{"role": "user", "content": CHECK_PROBE}],
            anthropic.omit,
            CHECK_MAX_TOKENS,
            CHECK_TIMEOUT_SECONDS,
        )
        _text_of(payload, require_text=False)  # the shape test; empty text is allowed
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
        self._record_usage(payload)
        return _model_json(_text_of(payload, require_text=True))
