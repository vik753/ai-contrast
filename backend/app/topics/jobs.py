"""The three topic AI calls as data: template, schema, caps and the reply builder.

A ``Job`` holds what to ask (gate objects only) and how to turn a validated answer into the
reply body. Every text of the answer goes through the topic safety pass in ``app.topics.ai``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel

from app.ai.port import AIRequest
from app.ai.prompting import data_chars
from app.ai.prompts import PromptTemplate
from app.limits.free import topic_neurons
from app.pseudo.gate import ConfirmedTopic, PseudonymizedDocument
from app.topics.ai import (
    EXPAND_MAX_TOKENS,
    PROPOSE_MAX_TOKENS,
    SUGGEST_MAX_TOKENS,
    ExpandOut,
    ProposeOut,
    SuggestOut,
    checked_attributes,
    checked_suggestions,
    checked_synonyms,
)
from app.topics.model import TopicDefinition

__all__ = ["BadOutputError", "Job", "expand_job", "propose_job", "suggest_job"]


class BadOutputError(Exception):
    """The model answer is unusable after the repair attempt."""


@dataclass(frozen=True)
class Job:
    """One AI call: what to ask and how to turn the validated answer into the reply."""

    template: PromptTemplate
    schema: type[BaseModel]
    max_tokens: int
    finish: Callable[[BaseModel], dict[str, object]]
    document: PseudonymizedDocument | None = None
    topic: ConfirmedTopic | None = None

    def request(self, repair: int = 0) -> AIRequest:
        return AIRequest(
            self.template,
            self.schema,
            self.max_tokens,
            document=self.document,
            topic=self.topic,
            repair=repair,
        )

    def neurons(self) -> int:
        """The worst case in Neurons: the input, the output cap, and a repair call (ADR 0017)."""
        return topic_neurons(data_chars(self.request()), self.max_tokens, repair=True)


def propose_job(topic: ConfirmedTopic, definition: TopicDefinition) -> Job:
    def finish(out: BaseModel) -> dict[str, object]:
        if not isinstance(out, ProposeOut):
            raise BadOutputError
        attributes, dropped = checked_attributes(out, definition)
        if not attributes:
            raise BadOutputError
        return {"attributes": [a.model_dump(mode="json") for a in attributes], "dropped": dropped}

    return Job(
        PromptTemplate.PROPOSE_ATTRIBUTES, ProposeOut, PROPOSE_MAX_TOKENS, finish, topic=topic
    )


def expand_job(topic: ConfirmedTopic) -> Job:
    def finish(out: BaseModel) -> dict[str, object]:
        if not isinstance(out, ExpandOut):
            raise BadOutputError
        lists, dropped = checked_synonyms(out)
        return {**lists, "dropped": dropped}

    return Job(PromptTemplate.EXPAND_SYNONYMS, ExpandOut, EXPAND_MAX_TOKENS, finish, topic=topic)


def suggest_job(document: PseudonymizedDocument) -> Job:
    def finish(out: BaseModel) -> dict[str, object]:
        if not isinstance(out, SuggestOut):
            raise BadOutputError
        kept, dropped = checked_suggestions(out)
        suggestions = [
            {"id": f"suggested_{number}", "name": name, "description": description}
            for number, (name, description) in enumerate(kept, 1)
        ]
        return {"suggestions": suggestions, "dropped": dropped}

    return Job(
        PromptTemplate.SUGGEST_TOPICS, SuggestOut, SUGGEST_MAX_TOKENS, finish, document=document
    )
