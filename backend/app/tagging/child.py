"""The tagging step inside the sandbox child (ADR 0018 point 1, ADR 0011).

``run`` gets JSON made by the parent: the masked document, the synonyms of the confirmed topics
and the keyword step budget. It runs the full safety pass, the keyword tags and Layer 2 on every
clause, so that all pure-Python text work stays out of the server process. The reply is
``{"ok": true, "detector_version", "digest", "keyword", "layer2"}`` or ``{"error": code}`` (with
``"spans"``, offsets only, for ``unmasked_identifier``). It holds ids, offsets and classes only.
"""

from __future__ import annotations

import json
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.pseudo.gate import SafetyError, safety_pass
from app.pseudo.lexicon import DETECTOR_VERSION
from app.pseudo.untrusted import UntrustedMaskedDocument
from app.safety.child import INVALID_REQUEST, digest
from app.tagging.clauses import clauses_of
from app.tagging.keywords import keyword_tags
from app.tagging.layer2 import clause_hits
from app.tagging.model import TagMergeError

KEYWORD_BUDGET_EXCEEDED = "keyword_budget_exceeded"


class ChildTopic(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    topic_id: Annotated[str, Field(max_length=64)]
    synonyms_en: list[str]
    synonyms_uk: list[str]
    synonyms_ru: list[str]


class ChildRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    document: UntrustedMaskedDocument
    topics: Annotated[list[ChildTopic], Field(min_length=1, max_length=50)]
    keyword_budget: Annotated[int, Field(ge=1)]


def run(data: bytes, *, max_clauses: int) -> bytes:
    try:
        request = ChildRequest.model_validate_json(data)
    except (ValidationError, ValueError):
        return json.dumps({"error": INVALID_REQUEST}).encode()
    try:
        document = safety_pass(request.document, max_clauses=max_clauses)
    except SafetyError as error:
        reply: dict[str, object] = {"error": error.code}
        if error.spans:
            reply["spans"] = [list(span) for span in error.spans]
        return json.dumps(reply).encode()
    clauses = clauses_of(document)
    try:
        keyword = keyword_tags(clauses, request.topics, budget_steps=request.keyword_budget)
    except TagMergeError as error:
        return json.dumps({"error": error.code}).encode()
    layer2 = {
        clause_id: {
            "text": [[hit.start, hit.end, hit.cls] for hit in hits.text],
            "heading": [[hit.start, hit.end, hit.cls] for hit in hits.heading],
        }
        for clause_id, hits in clause_hits(clauses).items()
    }
    return json.dumps(
        {
            "ok": True,
            "detector_version": DETECTOR_VERSION,
            "digest": digest(document),
            "keyword": {cid: sorted(tids) for cid, tids in keyword.items()},
            "layer2": layer2,
        }
    ).encode()
