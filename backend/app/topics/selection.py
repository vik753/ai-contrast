"""Selection of topics for an analysis request (ADR 0017 point 3; used by stage 9).

Catalog topics come by id and ``catalog_version``: the server builds them from its own catalog.
Suggested and client topics come as definitions. Every topic passes ``confirm_topic`` with the
catalog. Raises ``TopicSelectionError`` (a code only), ``TopicDefinitionError`` or
``TopicTextError``; none of them holds any text.
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict

from app.pseudo.gate import ConfirmedTopic, confirm_topic
from app.topics.catalog import Catalog
from app.topics.model import TopicDefinition, TopicDefinitionError

__all__ = ["CatalogRef", "TopicSelection", "TopicSelectionError", "resolve_topics"]

MAX_CATALOG: Final = 30
MAX_SUGGESTED: Final = 10
MAX_CUSTOM: Final = 10


class TopicSelectionError(Exception):
    """The selection is refused. ``str(error)`` is the code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CatalogRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    domain: str
    topic_id: str
    side: str
    lang: str
    catalog_version: str


class TopicSelection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    catalog: list[CatalogRef] = []
    suggested: list[TopicDefinition] = []
    custom: list[TopicDefinition] = []


def _own_origin(definitions: list[TopicDefinition], origin: str) -> None:
    if any(definition.origin != origin for definition in definitions):
        raise TopicDefinitionError("invalid_topic_definition")


def resolve_topics(selection: TopicSelection, catalog: Catalog) -> tuple[ConfirmedTopic, ...]:
    """Build the confirmed topics of a selection, catalog topics first."""
    if (
        len(selection.catalog) > MAX_CATALOG
        or len(selection.suggested) > MAX_SUGGESTED
        or len(selection.custom) > MAX_CUSTOM
    ):
        raise TopicSelectionError("too_many_topics")
    _own_origin(selection.suggested, "suggested")
    _own_origin(selection.custom, "custom")
    definitions: list[TopicDefinition] = []
    for ref in selection.catalog:
        if ref.catalog_version != catalog.catalog_version:
            raise TopicSelectionError("catalog_version_mismatch")
        try:
            definitions.append(catalog.definition(ref.domain, ref.topic_id, ref.side, ref.lang))
        except KeyError:
            raise TopicSelectionError("unknown_topic") from None
    definitions += selection.suggested
    definitions += selection.custom
    return tuple(confirm_topic(definition, catalog=catalog) for definition in definitions)
