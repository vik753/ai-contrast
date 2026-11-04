"""Topic definitions as the client sends them, before ``confirm_topic`` (ADR 0017 point 3).

``TopicDefinition`` and ``AttributeDefinition`` are plain request-side models: they carry no
trust. ``check_structure`` applies the rules that need no text analysis (ids, types, units,
directions, caps). ``confirm_topic`` in ``app.pseudo.gate`` adds the text safety pass and
makes the only value the AI layer accepts.
"""

from __future__ import annotations

import re
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

__all__ = [
    "ALL_UNITS",
    "AMOUNT_UNITS",
    "DIRECTIONS_BY_TYPE",
    "DURATION_UNITS",
    "ID_RE",
    "MAX_ATTRIBUTES",
    "MAX_SYNONYMS",
    "MAX_VALUES",
    "TYPES",
    "AttributeDefinition",
    "TopicDefinition",
    "TopicDefinitionError",
    "check_structure",
]

ID_RE: Final = re.compile(r"[a-z][a-z0-9_]{1,47}", re.ASCII)
MAX_ATTRIBUTES: Final = 12
MAX_VALUES: Final = 30
MAX_SYNONYMS: Final = 40
AMOUNT_UNITS: Final = frozenset({"UAH", "USD", "EUR", "percent_of_sum", "percent_of_loss"})
DURATION_UNITS: Final = frozenset({"hours", "days", "working_days", "months", "years"})
ALL_UNITS: Final = {"amount": AMOUNT_UNITS, "duration": DURATION_UNITS}
_LOWER_HIGHER: Final = frozenset({"lower_better", "higher_better", "none"})
DIRECTIONS_BY_TYPE: Final = {
    "amount": _LOWER_HIGHER,
    "percentage": _LOWER_HIGHER,
    "duration": _LOWER_HIGHER,
    "enum": frozenset({"ordered", "none"}),
    "categories": frozenset({"more_better", "fewer_better", "none"}),
    "text": frozenset({"none"}),
}
TYPES: Final = frozenset(DIRECTIONS_BY_TYPE)
_VALUE_TYPES: Final = frozenset({"enum", "categories"})
INVALID_DEFINITION: Final = "invalid_topic_definition"


class TopicDefinitionError(Exception):
    """A topic definition is refused. ``str(error)`` is the code (never any text)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AttributeDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    label: str
    type: str
    units: tuple[str, ...] = ()
    direction: str = "none"
    order: tuple[str, ...] = ()
    values: tuple[str, ...] = ()
    direction_source: Literal["catalog", "client"] = "client"


class TopicDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    origin: Literal["catalog", "suggested", "custom"]
    domain: str | None = None
    topic_id: str
    title: str
    description: str = ""
    side: str
    attributes: tuple[AttributeDefinition, ...] = ()
    synonyms_en: tuple[str, ...] = ()
    synonyms_uk: tuple[str, ...] = ()
    synonyms_ru: tuple[str, ...] = ()


def _fail() -> TopicDefinitionError:
    return TopicDefinitionError(INVALID_DEFINITION)


def _check_attribute(attribute: AttributeDefinition) -> None:
    kind = attribute.type
    if ID_RE.fullmatch(attribute.id) is None or kind not in TYPES:
        raise _fail()
    allowed_units = ALL_UNITS.get(kind, frozenset())
    if not set(attribute.units) <= allowed_units or len(set(attribute.units)) != len(
        attribute.units
    ):
        raise _fail()
    values = attribute.values
    if kind in _VALUE_TYPES:
        if not 1 <= len(values) <= MAX_VALUES or len(set(values)) != len(values):
            raise _fail()
    elif values:
        raise _fail()
    if attribute.direction not in DIRECTIONS_BY_TYPE[kind]:
        raise _fail()
    if attribute.direction == "ordered":
        if sorted(attribute.order) != sorted(values):
            raise _fail()
    elif attribute.order:
        raise _fail()


def check_structure(definition: TopicDefinition) -> None:
    """Ids, types, units, directions, caps. Raises ``TopicDefinitionError`` with
    ``invalid_topic_definition``. Looks at no text content beyond the shape."""
    synonym_lists = (definition.synonyms_en, definition.synonyms_uk, definition.synonyms_ru)
    if (
        ID_RE.fullmatch(definition.topic_id) is None
        or ID_RE.fullmatch(definition.side) is None
        or (definition.domain is not None and ID_RE.fullmatch(definition.domain) is None)
        or len(definition.attributes) > MAX_ATTRIBUTES
        or any(len(items) > MAX_SYNONYMS for items in synonym_lists)
        or (definition.origin == "suggested" and definition.description != "")
    ):
        raise _fail()
    ids = [attribute.id for attribute in definition.attributes]
    if len(set(ids)) != len(ids):
        raise _fail()
    for attribute in definition.attributes:
        _check_attribute(attribute)
