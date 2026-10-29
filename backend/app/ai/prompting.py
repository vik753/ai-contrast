"""Prompt assembly (ADR 0016 point 2).

Instructions are one system message. Data is user messages, one per block. Every block is
wrapped in a begin and an end delimiter with the same random nonce. The nonce is drawn
after the block text is known and is drawn again when it occurs in any block text.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from typing import Final, Literal

from app.ai.port import AIError, AIErrorCode, AIRequest

__all__ = ["CHECK_MAX_TOKENS", "CHECK_PROBE", "Message", "build_messages"]

# The fixed probe of ``check()``: a constant, never built from caller input.
CHECK_PROBE: Final = "Reply with the single word: ok"
CHECK_MAX_TOKENS: Final = 16

_MAX_DRAWS: Final = 8
_NONCE_BYTES: Final = 16
_SAFE_ID: Final = re.compile(r"[A-Za-z0-9_.-]{1,32}", re.ASCII)


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user"]
    content: str


def _document_text(request: AIRequest) -> str:
    lines: list[str] = []
    for number, clause in enumerate(request.document.clauses, 1):
        clause_id = clause.id if _SAFE_ID.fullmatch(clause.id) else f"c{number}"
        lines.append(f"[{clause_id}]\n{clause.text}")
    return "\n\n".join(lines)


def _blocks(request: AIRequest) -> list[tuple[str, str]]:
    blocks = [("DOCUMENT", _document_text(request))]
    if request.text is not None:
        blocks.append(("TEXT", request.text.text))
    if request.topic is not None:
        blocks.append(("TOPIC", request.topic.title))
    return blocks


def build_messages(request: AIRequest) -> tuple[Message, ...]:
    blocks = _blocks(request)
    texts = [text for _, text in blocks]
    messages = [Message("system", request.template.value)]
    for kind, text in blocks:
        for _ in range(_MAX_DRAWS):
            nonce = secrets.token_hex(_NONCE_BYTES)
            if not any(nonce in other for other in texts):
                break
        else:
            raise AIError(AIErrorCode.PROVIDER_BAD_REQUEST) from None
        content = f"<<<BEGIN {kind} {nonce}>>>\n{text}\n<<<END {kind} {nonce}>>>"
        messages.append(Message("user", content))
    return tuple(messages)
