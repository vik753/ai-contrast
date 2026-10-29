"""Shared fakes for the S6-T2 tests. No network, no real provider (see README.md for the names).

``FakeUpstream`` is an ``httpx2.MockTransport`` that records every request. It is injected
through ``provider_for(..., transport=...)``. Documents come from the real safety pass.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx2
import pytest
from app.ai.factory import provider_for
from app.ai.port import AIError, AIProvider, AIRequest
from app.ai.presets import PresetId
from app.ai.prompts import PromptTemplate
from opentelemetry import trace
from pydantic import BaseModel, SecretStr

from app.pseudo.gate import PseudonymizedDocument, safety_pass
from app.pseudo.lexicon import DETECTOR_VERSION
from app.pseudo.untrusted import MaskedClause, UntrustedMaskedDocument
from tests.canary.harness import LogTap

BACKEND = Path(__file__).resolve().parents[2]
LOG_CONFIG = BACKEND / "log_config.json"
KEY = "sk-CANARY-" + secrets.token_hex(8)
BODY_CANARY = "CANARY-UPSTREAM-BODY-7f3a"
REQUEST_ID_CANARY = "req_CANARY_9c1d"
AUTH_HEADERS = frozenset({"x-api-key", "authorization"})
MIB = 1024 * 1024

TEXTS = (
    "1. The Client shall pay the Supplier within thirty days.",
    "2. Either party may end the agreement with written notice.",
)

Reply = Callable[[httpx2.Request], httpx2.Response]


class Verdict(BaseModel):
    ok: bool


@dataclass(frozen=True)
class Seen:
    method: str
    url: str
    host: str
    path: str
    headers: dict[str, str]
    body: bytes
    timeout: dict[str, float | None]

    @property
    def json(self) -> Any:
        return json.loads(self.body)

    @property
    def everything(self) -> str:
        """URL, header names and values, and body: all that a network observer sees."""
        heads = " ".join(f"{k}: {v}" for k, v in self.headers.items())
        return f"{self.url} {heads} {self.body.decode('utf-8', 'replace')}"

    def without_auth(self) -> str:
        heads = " ".join(f"{k}: {v}" for k, v in self.headers.items() if k not in AUTH_HEADERS)
        return f"{self.url} {heads} {self.body.decode('utf-8', 'replace')}"


def model_reply(text: str = '{"ok": true}', *, request_id: str = "req_ok") -> Reply:
    """A 200 answer in the wire format of the path that was called."""

    def reply(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/messages"):
            body: dict[str, Any] = {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "test-model-1",
                "content": [{"type": "text", "text": text}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            }
        else:
            body = {
                "id": "chatcmpl-1",
                "object": "chat.completion",
                "created": 1,
                "model": "test-model-1",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": text},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        return httpx2.Response(200, json=body, headers={"request-id": request_id})

    return reply


def error_reply(status: int, headers: dict[str, str] | None = None) -> Reply:
    """An error answer whose body and request ID hold canaries."""

    def reply(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/messages"):
            body: dict[str, Any] = {
                "type": "error",
                "error": {"type": "api_error", "message": BODY_CANARY},
                "request_id": REQUEST_ID_CANARY,
            }
        else:
            body = {"error": {"message": BODY_CANARY, "type": "api_error", "code": "x"}}
        return httpx2.Response(
            status, json=body, headers={"request-id": REQUEST_ID_CANARY, **(headers or {})}
        )

    return reply


def raising(error: BaseException) -> Reply:
    def reply(request: httpx2.Request) -> httpx2.Response:
        raise error

    return reply


class FakeUpstream(httpx2.MockTransport):
    """Records every request; ``reply`` builds the answer."""

    def __init__(self, reply: Reply | None = None) -> None:
        self.seen: list[Seen] = []
        self.closed = False
        self.reply = reply or model_reply()
        super().__init__(self._handle)

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.seen.append(
            Seen(
                method=request.method,
                url=str(request.url),
                host=request.url.host,
                path=request.url.path,
                headers={k.lower(): v for k, v in request.headers.items()},
                body=request.content,
                timeout=dict(request.extensions.get("timeout", {})),
            )
        )
        return self.reply(request)

    async def aclose(self) -> None:
        self.closed = True
        await super().aclose()


def make_document(*texts: str, label: str = "A") -> PseudonymizedDocument:
    untrusted = UntrustedMaskedDocument(
        label=label,
        detector_version=DETECTOR_VERSION,
        clauses=[MaskedClause(id=f"c{i}", text=t) for i, t in enumerate(texts or TEXTS, 1)],
        acknowledged_unmasked=[],
    )
    return safety_pass(untrusted)


def first_template() -> PromptTemplate:
    return next(iter(PromptTemplate))


def make_request(
    document: PseudonymizedDocument | None = None, *, max_tokens: int = 512
) -> AIRequest:
    return AIRequest(
        template=first_template(),
        document=document or make_document(),
        schema=Verdict,
        max_tokens=max_tokens,
    )


def make_provider(
    preset: PresetId = PresetId.ANTHROPIC,
    *,
    model: str = "test-model-1",
    key: str | None = None,
    base_url: str | None = None,
    upstream: FakeUpstream | None = None,
) -> tuple[AIProvider, FakeUpstream]:
    upstream = upstream or FakeUpstream()
    return provider_for(
        preset, model, SecretStr(key or KEY), base_url, transport=upstream
    ), upstream


def run(provider: AIProvider, op: str, request: AIRequest | None = None) -> object:
    """``op`` is ``check`` or ``complete_json``."""

    async def go() -> object:
        if op == "check":
            return await provider.check()
        return await provider.complete_json(request or make_request())

    return asyncio.run(go())


def failure(provider: AIProvider, op: str) -> AIError:
    with pytest.raises(AIError) as info:
        run(provider, op)
    return info.value


# ------------------------------------------------------------------------------- logs

SDK_LOGGERS = ("anthropic", "openai", "httpx2", "httpcore2")


@contextmanager
def tap_logs() -> Iterator[LogTap]:
    """All records at DEBUG on the root; the SDK loggers keep the level of ``log_config.json``
    (production), so a missing entry there shows up as leaked debug output."""
    configured = json.loads(LOG_CONFIG.read_text(encoding="utf-8"))["loggers"]
    saved = {name: logging.getLogger(name).level for name in SDK_LOGGERS}
    root = logging.getLogger()
    root_level = root.level
    tap = LogTap()
    for name in SDK_LOGGERS:
        level = configured.get(name, {}).get("level", "NOTSET")
        logging.getLogger(name).setLevel(logging.getLevelName(level))
    root.setLevel(logging.DEBUG)
    root.addHandler(tap)
    try:
        yield tap
    finally:
        root.removeHandler(tap)
        root.setLevel(root_level)
        for name, level_no in saved.items():
            logging.getLogger(name).setLevel(level_no)


# ------------------------------------------------------------------------------ spans


class _RecordingTracer(trace.Tracer):
    def __init__(self, spans: list[str]) -> None:
        self.spans = spans

    def start_span(self, name: str, *args: Any, **kwargs: Any) -> trace.Span:
        self.spans.append(name)
        return trace.INVALID_SPAN

    @contextmanager
    def start_as_current_span(self, name: str, *args: Any, **kwargs: Any) -> Iterator[trace.Span]:
        self.spans.append(name)
        yield trace.INVALID_SPAN


class _RecordingProvider(trace.TracerProvider):
    def __init__(self) -> None:
        self.spans: list[str] = []

    def get_tracer(self, *args: Any, **kwargs: Any) -> trace.Tracer:
        return _RecordingTracer(self.spans)


def record_spans(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Make the global OpenTelemetry provider a recorder; returns the list of span names."""
    provider = _RecordingProvider()
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: provider)
    return provider.spans
