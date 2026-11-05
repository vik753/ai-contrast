"""Prompt assembly (ADR 0016 point 2).

Instructions are one system message. Data is user messages, one per block. Every block is
wrapped in a begin and an end delimiter with the same random nonce. The nonce is drawn
after the block text is known and is drawn again when it occurs in any block text.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from typing import Final, Literal

from app.ai.port import AIError, AIErrorCode, AIRequest
from app.pseudo.gate import ConfirmedTopic, PseudonymizedDocument

__all__ = ["CHECK_MAX_TOKENS", "CHECK_PROBE", "Message", "build_messages", "data_chars"]

# The fixed probe of ``check()``: a constant, never built from caller input.
CHECK_PROBE: Final = "Reply with the single word: ok"
CHECK_MAX_TOKENS: Final = 16

# Fixed texts of the repair codes (index = ``AIRequest.repair``).
_REPAIR_TEXTS: Final = (
    "",
    "not_json",
    "schema_violation",
    "cap_exceeded",
)

_MAX_DRAWS: Final = 8
_NONCE_BYTES: Final = 16
_SAFE_ID: Final = re.compile(r"[A-Za-z0-9_.-]{1,32}", re.ASCII)


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user"]
    content: str


def _document_text(document: PseudonymizedDocument) -> str:
    lines: list[str] = []
    for number, clause in enumerate(document.clauses, 1):
        clause_id = clause.id if _SAFE_ID.fullmatch(clause.id) else f"c{number}"
        lines.append(f"[{clause_id}]\n{clause.text}")
    return "\n\n".join(lines)


def _instructions(request: AIRequest) -> str:
    """The template text and the JSON schema of the answer (from the class, never a string)."""
    schema = json.dumps(request.schema.model_json_schema(), sort_keys=True, separators=(",", ":"))
    text = f"{request.template.value}\n\nJSON schema of the answer:\n{schema}"
    if request.repair:
        text += (
            f"\n\nYour previous answer was refused (error code: {_REPAIR_TEXTS[request.repair]}). "
            "Do the same task again and answer with one valid JSON object."
        )
    return text


def _topic_text(topic: ConfirmedTopic) -> str:
    """The topic as lines. Ids of values and attributes, synonyms and directions stay out.

    Domain and side are catalog ids (``confirm_topic`` scans them as words); a description is
    present only for a client-written topic (an AI suggestion never has one)."""
    lines = [f"name: {topic.title}"]
    if topic.description:
        lines.append(f"description: {topic.description}")
    if topic.domain is not None:
        lines.append(f"domain: {topic.domain}")
    lines.append(f"side: {topic.side}")
    lines.extend(f"attribute: {attribute.label}" for attribute in topic.attributes)
    return "\n".join(lines)


def _blocks(request: AIRequest) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    if request.document is not None:
        blocks.append(("DOCUMENT", _document_text(request.document)))
    if request.text is not None:
        blocks.append(("TEXT", request.text.text))
    if request.topic is not None:
        blocks.append(("TOPIC", _topic_text(request.topic)))
    return blocks


def build_messages(request: AIRequest) -> tuple[Message, ...]:
    blocks = _blocks(request)
    texts = [text for _, text in blocks]
    messages = [Message("system", _instructions(request))]
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


def data_chars(request: AIRequest) -> int:
    """Characters of everything sent: instructions, JSON schema, delimiters and data blocks."""
    return sum(len(message.content) for message in build_messages(request))
