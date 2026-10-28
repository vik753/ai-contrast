"""The safety check inside the sandbox child (ADR 0015 point 4, ADR 0011).

``run`` gets the raw request bytes; the parent never parses them. Strict Pydantic
validation and a duplicate-key pass (as in ``app.segment.child``) give ``invalid_request``.
The reply is ``{"ok": true, "detector_version", "digest"}`` or ``{"error": code}``, with
``"spans"`` (clause ids and offsets only) for ``unmasked_identifier``.
"""

from __future__ import annotations

import hashlib
import json

from pydantic import ValidationError

from app.pseudo.gate import PseudonymizedDocument, SafetyError, safety_pass
from app.pseudo.lexicon import DETECTOR_VERSION
from app.pseudo.untrusted import UntrustedMaskedDocument

INVALID_REQUEST = "invalid_request"


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError
    return result


def digest(document: PseudonymizedDocument) -> str:
    """SHA-256 of the canonical masked document: label, clause ids and texts in order."""
    canonical = json.dumps(
        [document.label, [[clause.id, clause.text] for clause in document.clauses]],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run(data: bytes, *, max_clauses: int) -> bytes:
    try:
        untrusted = UntrustedMaskedDocument.model_validate_json(data)
        json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicate_keys)
    except (ValidationError, ValueError):
        return json.dumps({"error": INVALID_REQUEST}).encode()
    try:
        document = safety_pass(untrusted, max_clauses=max_clauses)
    except SafetyError as error:
        reply: dict[str, object] = {"error": error.code}
        if error.spans:
            reply["spans"] = [list(span) for span in error.spans]
        return json.dumps(reply).encode()
    return json.dumps(
        {"ok": True, "detector_version": DETECTOR_VERSION, "digest": digest(document)}
    ).encode()
