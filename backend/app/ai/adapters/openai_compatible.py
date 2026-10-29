"""Adapter on the official ``openai`` SDK, Chat Completions (ADR 0016 point 3).

It serves every preset except ``anthropic``. A new SDK client per call, on our guarded client;
``max_retries=0``; explicit ``base_url``; no tools; the key goes only to the SDK constructor.
"""

from __future__ import annotations

import asyncio

import openai
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
from app.ai.prompting import CHECK_MAX_TOKENS, CHECK_PROBE, Message, build_messages
from app.net.ai_client import AITransport, ai_client

_quiet_sdk_loggers()


def _text_of(payload: dict[str, object]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        _bad_response()
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        _bad_response()
    return content


class OpenAICompatibleAdapter:
    def __init__(
        self,
        model: str,
        key: SecretStr,
        base_url: str,
        transport: AITransport | None = None,
        *,
        completion_tokens_field: bool = False,
    ) -> None:
        self._model = model
        self._key = key
        self._base_url = base_url
        self._transport = transport
        # OpenAI's own models want ``max_completion_tokens``; compatible servers ``max_tokens``.
        self._completion_tokens_field = completion_tokens_field

    async def _post(
        self, messages: tuple[Message, ...], max_tokens: int, timeout: float
    ) -> dict[str, object]:
        _quiet_sdk_loggers()
        wire: list[openai.types.chat.ChatCompletionMessageParam] = [
            {"role": "system", "content": m.content}
            if m.role == "system"
            else {"role": "user", "content": m.content}
            for m in messages
        ]
        legacy = None if self._completion_tokens_field else max_tokens
        modern = max_tokens if self._completion_tokens_field else None
        try:
            async with asyncio.timeout(timeout):
                http = ai_client(
                    connect_timeout=CONNECT_TIMEOUT_SECONDS,
                    read_timeout=timeout,
                    transport=self._transport,
                )
                client = openai.AsyncOpenAI(
                    api_key=self._key.get_secret_value(),
                    base_url=self._base_url,
                    timeout=openai.Timeout(timeout, connect=CONNECT_TIMEOUT_SECONDS),
                    max_retries=0,
                    http_client=http,
                )
                try:
                    raw = await client.chat.completions.with_raw_response.create(
                        model=self._model,
                        messages=wire,
                        max_tokens=legacy if legacy is not None else openai.omit,
                        max_completion_tokens=modern if modern is not None else openai.omit,
                    )
                    return _load_object(await raw.http_response.aread())
                finally:
                    await client.close()
                    await http.aclose()
        except Exception as error:  # noqa: BLE001 - every error becomes an AIError (T1)
            raise _error_for(error) from None

    async def check(self) -> CheckResult:
        probe = (Message("user", CHECK_PROBE),)
        await self._post(probe, CHECK_MAX_TOKENS, CHECK_TIMEOUT_SECONDS)
        return CheckResult(ok=True)

    async def complete_json(self, request: AIRequest) -> ModelJson:
        payload = await self._post(
            build_messages(request), request.max_tokens, COMPLETE_TIMEOUT_SECONDS
        )
        return _model_json(_text_of(payload))
