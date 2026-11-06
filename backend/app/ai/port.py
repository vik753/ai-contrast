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
from app.pseudo.gate import (
    ConfirmedTopic,
    PseudonymizedDocument,
    PseudonymizedText,
    document_digest,
)

__all__ = [
    "REPAIR_CAP",
    "REPAIR_NOT_JSON",
    "REPAIR_SCHEMA",
    "AIError",
    "AIErrorCode",
    "AIProvider",
    "AIRequest",
    "CheckResult",
    "ModelJson",
    "TaggingRequest",
]

MAX_OUTPUT_TOKENS: Final = 16384
# Repair codes of ``AIRequest.repair`` (ADR 0009: a repair call carries an error-code enum and
# never the previous output). 0 is no repair; the texts live in ``app.ai.prompting``.
REPAIR_NOT_JSON: Final = 1
REPAIR_SCHEMA: Final = 2
REPAIR_CAP: Final = 3

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
        self.__suppress_context__ = True  # also when raised inside a handler


@dataclass(frozen=True)
class CheckResult:
    ok: bool


# Field set of each template: (document, topic, text) each "required", "optional" or "forbidden"
# (ADR 0017 point 5; ADR 0009: attribute proposal and synonym expansion take no document).
_FIELD_SETS: dict[PromptTemplate, tuple[str, str, str]] = {
    PromptTemplate.TAG_CLAUSES: ("required", "forbidden", "forbidden"),
    PromptTemplate.CHECK_TAGS: ("required", "forbidden", "forbidden"),
    PromptTemplate.DOCUMENT_JSON: ("required", "optional", "optional"),
    PromptTemplate.SUGGEST_TOPICS: ("required", "forbidden", "forbidden"),
    PromptTemplate.PROPOSE_ATTRIBUTES: ("forbidden", "required", "forbidden"),
    PromptTemplate.EXPAND_SYNONYMS: ("forbidden", "required", "forbidden"),
}


_TAGGING_TEMPLATES = frozenset({PromptTemplate.TAG_CLAUSES, PromptTemplate.CHECK_TAGS})


@dataclass(frozen=True)
class AIRequest:
    template: PromptTemplate
    schema: type[BaseModel]
    max_tokens: int
    document: PseudonymizedDocument | None = None
    text: PseudonymizedText | None = None
    topic: ConfirmedTopic | None = None
    repair: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.template, PromptTemplate):
            raise TypeError("template has a wrong type")  # noqa: TRY003
        if self.template in _TAGGING_TEMPLATES and not isinstance(self, TaggingRequest):
            raise TypeError("the fields do not fit the template")  # noqa: TRY003
        checks = (
            (self.document, PseudonymizedDocument),
            (self.text, PseudonymizedText),
            (self.topic, ConfirmedTopic),
        )
        if not all(value is None or isinstance(value, kind) for value, kind in checks):
            raise TypeError("document, text or topic has a wrong type")  # noqa: TRY003
        for value, rule in zip(
            (self.document, self.topic, self.text), _FIELD_SETS[self.template], strict=True
        ):
            if (rule == "required" and value is None) or (
                rule == "forbidden" and value is not None
            ):
                raise TypeError("the fields do not fit the template")  # noqa: TRY003
        if (
            self.text is not None
            and self.document is not None
            and self.text.source != document_digest(self.document)
        ):
            raise ValueError("text belongs to another document")  # noqa: TRY003
        if not (isinstance(self.schema, type) and issubclass(self.schema, BaseModel)):
            raise TypeError("schema must be a pydantic model class")  # noqa: TRY003
        if type(self.repair) is not int or not 0 <= self.repair <= REPAIR_CAP:
            raise ValueError("repair is out of range")  # noqa: TRY003
        if type(self.max_tokens) is not int or not 1 <= self.max_tokens <= MAX_OUTPUT_TOKENS:
            raise ValueError("max_tokens is out of range")  # noqa: TRY003


@dataclass(frozen=True)
class TaggingRequest(AIRequest):
    """A tagging call (ADR 0018 point 3): the request of ``TAG_CLAUSES`` or ``CHECK_TAGS``.

    ``topics`` are listed as ``T1..Tn`` (number = position + 1) with name and description only;
    ``topic_numbers`` selects which are listed (all when empty). ``pairs`` (``CHECK_TAGS`` only)
    are asked ``(clause position in document, topic number)`` pairs: numbers, never text.
    The fields live here, not in ``AIRequest``, which stays free of tuples and text."""

    topics: tuple[ConfirmedTopic, ...] = ()
    pairs: tuple[tuple[int, int], ...] = ()
    topic_numbers: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.template not in _TAGGING_TEMPLATES:
            raise TypeError("the fields do not fit the template")  # noqa: TRY003
        if not self.topics or not all(isinstance(t, ConfirmedTopic) for t in self.topics):
            raise TypeError("topics are missing or have a wrong type")  # noqa: TRY003
        asking = self.template is PromptTemplate.CHECK_TAGS
        if asking != bool(self.pairs) or (not asking and self.topic_numbers):
            raise TypeError("the fields do not fit the template")  # noqa: TRY003
        numbers = self.topic_numbers or tuple(range(1, len(self.topics) + 1))
        clauses = len(self.document.clauses) if self.document is not None else 0
        if (
            len(set(numbers)) != len(numbers)
            or not all(1 <= n <= len(self.topics) for n in numbers)
            or not all(0 <= c < clauses and n in numbers for c, n in self.pairs)
        ):
            raise ValueError("pairs or topic numbers do not fit the request")  # noqa: TRY003


@runtime_checkable
class AIProvider(Protocol):
    async def check(self) -> CheckResult:
        """Send the fixed probe. Return success or raise ``AIError``. Never returns model text."""
        ...

    async def complete_json(self, request: AIRequest) -> ModelJson:
        """Run one request; return the parsed JSON object of the answer."""
        ...
