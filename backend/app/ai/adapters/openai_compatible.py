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
    _code_for,
    _load_object,
    _model_json,
    _quiet_sdk_loggers,
)
from app.ai.port import (
    AIError,
    AIErrorCode,
    AIRequest,
    CheckResult,
    ModelJson,
    ReasoningEffort,
    Usage,
)
from app.ai.prompting import CHECK_MAX_TOKENS, CHECK_PROBE, Message, build_messages
from app.net.ai_client import AITransport, ai_client

_quiet_sdk_loggers()


def _text_of(payload: dict[str, object], *, require_text: bool) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        _bad_response()
    message = choices[0].get("message")
    if not isinstance(message, dict):
        _bad_response()
    content = message.get("content")
    if isinstance(content, str):
        return content
    if require_text or content is not None:
        _bad_response()
    return ""


MAX_TOKEN_COUNT = 10**9


def _usage_of(payload: dict[str, object]) -> tuple[int, int] | None:
    """``(prompt_tokens, completion_tokens)`` if both are plain non-negative integers."""
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if type(prompt) is not int or type(completion) is not int:
        return None
    if not (0 <= prompt <= MAX_TOKEN_COUNT and 0 <= completion <= MAX_TOKEN_COUNT):
        return None
    return prompt, completion


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
        self._usage = (0, 0)
        self._usage_missing = False

    @property
    def usage(self) -> Usage | None:
        """Input and output tokens the provider reported for all calls of this adapter, or
        ``None`` if any answer did not report them (the caller then assumes the worst case)."""
        return None if self._usage_missing else Usage(*self._usage)

    def _record_usage(self, payload: dict[str, object]) -> None:
        reported = _usage_of(payload)
        if reported is None:
            self._usage_missing = True
        else:
            self._usage = (self._usage[0] + reported[0], self._usage[1] + reported[1])

    async def _post(
        self,
        messages: tuple[Message, ...],
        max_tokens: int,
        timeout: float,
        effort: ReasoningEffort | None = None,
    ) -> dict[str, object]:
        _quiet_sdk_loggers()
        wire: list[openai.types.chat.ChatCompletionMessageParam] = [
            {"role": "system", "content": m.content}
            if m.role == "system"
            else {"role": "user", "content": m.content}
            for m in messages
        ]
        code = AIErrorCode.PROVIDER_UNAVAILABLE
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
                        max_tokens=openai.omit if self._completion_tokens_field else max_tokens,
                        max_completion_tokens=(
                            max_tokens if self._completion_tokens_field else openai.omit
                        ),
                        reasoning_effort=openai.omit if effort is None else effort.value,
                    )
                    return _load_object(await raw.http_response.aread())
                finally:
                    await client.close()
                    await http.aclose()
        except Exception as error:  # noqa: BLE001 - every error becomes an AIError (T1)
            code = _code_for(error)
        # Raised outside the handler: the error keeps no cause and no context (the SDK error
        # holds the request with the key header).
        raise AIError(code)

    async def check(self) -> CheckResult:
        probe = (Message("user", CHECK_PROBE),)
        payload = await self._post(probe, CHECK_MAX_TOKENS, CHECK_TIMEOUT_SECONDS)
        _text_of(payload, require_text=False)  # the shape test; empty text is allowed
        return CheckResult(ok=True)

    async def complete_json(self, request: AIRequest) -> ModelJson:
        payload = await self._post(
            build_messages(request), request.max_tokens, COMPLETE_TIMEOUT_SECONDS, request.effort
        )
        self._record_usage(payload)
        return _model_json(_text_of(payload, require_text=True))
