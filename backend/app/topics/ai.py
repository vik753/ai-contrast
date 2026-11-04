"""Model output schemas and the safety pass of the topic AI calls (ADR 0017 points 3 and 5).

Schemas are strict (``extra="forbid"``) and carry the caps; a cap that is broken fails the
whole answer (no truncation). Every text a model returned goes through ``check_topic_text``;
an item that fails is dropped and counted, never returned. A direction is never taken from a
model: every attribute starts with ``none``.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.injection import scan
from app.topics.model import (
    ID_RE,
    MAX_ATTRIBUTES,
    MAX_SYNONYMS,
    MAX_VALUES,
    AttributeDefinition,
    TopicDefinition,
    TopicDefinitionError,
    check_structure,
)
from app.topics.safety import TextKind, TopicTextError, check_topic_text

__all__ = [
    "EXPAND_MAX_TOKENS",
    "MAX_SUGGESTIONS",
    "PROPOSE_MAX_TOKENS",
    "SUGGEST_MAX_TOKENS",
    "ExpandOut",
    "ProposeOut",
    "SuggestOut",
    "checked_attributes",
    "checked_suggestions",
    "checked_synonyms",
]

SUGGEST_MAX_TOKENS: Final = 1200
PROPOSE_MAX_TOKENS: Final = 1500
EXPAND_MAX_TOKENS: Final = 800
MAX_SUGGESTIONS: Final = 8
# A text longer than this fails the schema; shorter texts are judged by the safety pass.
SCHEMA_TEXT_CAP: Final = 1000
MAX_UNITS: Final = 8

Text = Annotated[str, Field(max_length=SCHEMA_TEXT_CAP)]


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class SuggestItem(_Out):
    name: Text
    description: Text


class SuggestOut(_Out):
    topics: Annotated[list[SuggestItem], Field(max_length=MAX_SUGGESTIONS)]


class AttributeItem(_Out):
    id: Annotated[str, Field(max_length=64)]
    label: Text
    type: Literal["amount", "percentage", "duration", "enum", "categories", "text"]
    units: Annotated[list[Text], Field(max_length=MAX_UNITS)] = []
    values: Annotated[list[Text], Field(max_length=MAX_VALUES)] = []


class ProposeOut(_Out):
    attributes: Annotated[list[AttributeItem], Field(min_length=1, max_length=MAX_ATTRIBUTES)]


class ExpandOut(_Out):
    synonyms_en: Annotated[list[Text], Field(max_length=MAX_SYNONYMS)]
    synonyms_uk: Annotated[list[Text], Field(max_length=MAX_SYNONYMS)]
    synonyms_ru: Annotated[list[Text], Field(max_length=MAX_SYNONYMS)]


def _passes(text: str, kind: TextKind, lang: str | None = None) -> bool:
    try:
        check_topic_text(text, kind, lang)
    except TopicTextError:
        return False
    return True


def checked_suggestions(out: SuggestOut) -> tuple[list[tuple[str, str]], int]:
    """The ``(name, description)`` pairs that pass, and the number dropped."""
    kept = [
        (item.name, item.description)
        for item in out.topics
        if _passes(item.name, TextKind.NAME) and _passes(item.description, TextKind.DESCRIPTION)
    ]
    return kept, len(out.topics) - len(kept)


def _attribute(item: AttributeItem, topic: TopicDefinition) -> AttributeDefinition | None:
    """The attribute with direction ``none``, or ``None`` if any part fails."""
    if ID_RE.fullmatch(item.id) is None or scan(item.id.replace("_", " ")):
        return None
    if not _passes(item.label, TextKind.LABEL):
        return None
    if not all(_passes(value, TextKind.VALUE) for value in item.values):
        return None
    attribute = AttributeDefinition(
        id=item.id,
        label=item.label,
        type=item.type,
        units=tuple(item.units),
        values=tuple(item.values),
        value_ids=tuple(f"value_{number}" for number, _ in enumerate(item.values, 1)),
    )
    try:
        check_structure(topic.model_copy(update={"attributes": (attribute,)}))
    except TopicDefinitionError:
        return None
    return attribute


def checked_attributes(
    out: ProposeOut, topic: TopicDefinition
) -> tuple[list[AttributeDefinition], int]:
    """The attributes that pass (unique ids), and the number dropped."""
    kept: list[AttributeDefinition] = []
    for item in out.attributes:
        attribute = _attribute(item, topic)
        if attribute is not None and all(attribute.id != other.id for other in kept):
            kept.append(attribute)
    return kept, len(out.attributes) - len(kept)


def checked_synonyms(out: ExpandOut) -> tuple[dict[str, list[str]], int]:
    """The synonyms that pass (no repeats) per list name, and the number dropped."""
    result: dict[str, list[str]] = {}
    dropped = 0
    for lang, items in (
        ("en", out.synonyms_en),
        ("uk", out.synonyms_uk),
        ("ru", out.synonyms_ru),
    ):
        kept: list[str] = []
        for text in items:
            if _passes(text, TextKind.SYNONYM, lang) and text.lower() not in {
                other.lower() for other in kept
            }:
                kept.append(text)
        dropped += len(items) - len(kept)
        result[f"synonyms_{lang}"] = kept
    return result, dropped
