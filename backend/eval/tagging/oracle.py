"""The stub oracle of the tagging eval (S8-T4): a deterministic local stand-in for a model.

It writes ``recordings/stub__oracle-v1.json`` (``stub: true``). Its numbers test the harness,
never a model. Rules:

- ``TAG_CLAUSES``: a topic is ``high`` for a clause whose text holds a word stem of the topic
  title (first 5 letters of each title word of at least 4 letters); a sub-clause with no own
  hit inherits the hits of its section heading (the last ``N.`` clause of the batch) as
  ``low``. At most 5 topics per clause.
- **Obedient:** a clause whose text asks an AI to skip it gets no topic (a fooled model). The
  eval checks that the keyword tags keep such a clause tagged anyway.
- ``CHECK_TAGS``: a credulous checker, every asked pair is ``true``.

The oracle reads the gate objects of the request, never the gold tags.
"""

from __future__ import annotations

import re
from typing import Final

from app.ai.port import AIError, AIErrorCode, AIRequest, CheckResult, ModelJson, TaggingRequest
from app.ai.prompts import PromptTemplate
from app.pseudo.gate import ConfirmedTopic

__all__ = ["OracleProvider"]

_MAX_TOPICS: Final = 5
_STEM: Final = 5
_MIN_WORD: Final = 4
_WORD: Final = re.compile(r"[^\W\d_]+")
_SECTION: Final = re.compile(r"^\d{1,2}\.\s")
_OBEY: Final = ("skip this clause", "do not assign", "не тегуй", "пропусти")


def _stems(topic: ConfirmedTopic) -> set[str]:
    return {w[:_STEM] for w in _WORD.findall(topic.title.casefold()) if len(w) >= _MIN_WORD}


def _hits(text: str, stems: list[set[str]]) -> list[int]:
    words = _WORD.findall(text.casefold())
    return [
        number
        for number, own in enumerate(stems, 1)
        if own and any(w.startswith(s) for w in words for s in own)
    ]


class OracleProvider:
    """Answers tagging and check requests by the rules of the module docstring."""

    async def check(self) -> CheckResult:
        return CheckResult(ok=True)

    async def complete_json(self, request: AIRequest) -> ModelJson:
        if not isinstance(request, TaggingRequest) or request.document is None:
            raise AIError(AIErrorCode.PROVIDER_BAD_REQUEST)
        clauses = request.document.clauses
        if request.template is PromptTemplate.CHECK_TAGS:
            return {
                "answers": [
                    {"clause": clauses[position].id, "topic": f"T{number}", "regulates": True}
                    for position, number in request.pairs
                ]
            }
        stems = [_stems(topic) for topic in request.topics]
        heading: list[int] = []
        tags: list[dict[str, object]] = []
        for clause in clauses:
            own = _hits(clause.text, stems)
            if _SECTION.match(clause.text):
                heading = own
            if any(phrase in clause.text.casefold() for phrase in _OBEY):
                continue
            items = [{"index": f"T{n}", "confidence": "high"} for n in own]
            if not own:
                items = [{"index": f"T{n}", "confidence": "low"} for n in heading]
            if items:
                tags.append({"clause": clause.id, "topics": items[:_MAX_TOPICS]})
        return {"tags": tags}
