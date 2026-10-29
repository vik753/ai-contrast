"""The ``AIProvider`` port (ADR 0016 point 2).

No ``str`` parameter anywhere: content reaches a model only as gate types
(ADR 0008, ADR 0015 point 5). One ``AIRequest`` carries one document (ADR 0009).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

from pydantic import BaseModel

from app.ai.prompts import PromptTemplate
from app.pseudo.gate import ConfirmedTopic, PseudonymizedDocument, PseudonymizedText

__all__ = ["AIError", "AIErrorCode", "AIProvider", "AIRequest", "CheckResult", "ModelJson"]

MAX_OUTPUT_TOKENS: Final = 16384

# The parsed JSON object of a model answer. Schema validation happens in the caller.
type ModelJson = dict[str, object]


class AIErrorCode(enum.StrEnum):
    PROVIDER_AUTH_FAILED = "provider_auth_failed"
    PROVIDER_MODEL_NOT_FOUND = "provider_model_not_found"
    PROVIDER_RATE_LIMITED = "provider_rate_limited"
    PROVIDER_BAD_REQUEST = "provider_bad_request"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_BLOCKED_HOST = "provider_blocked_host"
    PROVIDER_BAD_RESPONSE = "provider_bad_response"


class AIError(Exception):
    """An AI call failed. It holds the code and no other text. Raise it ``from None``."""

    def __init__(self, code: AIErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


@dataclass(frozen=True)
class CheckResult:
    ok: bool


@dataclass(frozen=True)
class AIRequest:
    template: PromptTemplate
    document: PseudonymizedDocument
    schema: type[BaseModel]
    max_tokens: int
    text: PseudonymizedText | None = None
    topic: ConfirmedTopic | None = None

    def __post_init__(self) -> None:
        checks = (
            (self.template, PromptTemplate),
            (self.document, PseudonymizedDocument),
        )
        optional = ((self.text, PseudonymizedText), (self.topic, ConfirmedTopic))
        if not all(isinstance(value, kind) for value, kind in checks):
            raise TypeError("template or document has a wrong type")  # noqa: TRY003
        if not all(value is None or isinstance(value, kind) for value, kind in optional):
            raise TypeError("text or topic has a wrong type")  # noqa: TRY003
        if not (isinstance(self.schema, type) and issubclass(self.schema, BaseModel)):
            raise TypeError("schema must be a pydantic model class")  # noqa: TRY003
        if type(self.max_tokens) is not int or not 1 <= self.max_tokens <= MAX_OUTPUT_TOKENS:
            raise ValueError("max_tokens is out of range")  # noqa: TRY003


@runtime_checkable
class AIProvider(Protocol):
    async def check(self) -> CheckResult:
        """Send the fixed probe. Return success or raise ``AIError``. Never returns model text."""
        ...

    async def complete_json(self, request: AIRequest) -> ModelJson:
        """Run one request; return the parsed JSON object of the answer."""
        ...
