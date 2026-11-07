"""The result signature and ``analysis_version`` (ADR 0019 point 8).

``result_signature`` = HMAC-SHA256 with a per-process key (``secrets.token_bytes(32)``, memory
only, never logged) over the document digest, the analysis version, domain, side, model, output
language, a hash of the flags and a hash of the verified result. ``analysis_version`` hashes the
prompts, the schemas, the lexicons and the verification rules: it changes when any of them does.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from functools import cache
from pathlib import Path
from typing import Final

from app.ai.prompts import PromptTemplate
from app.analysis.schemas import OtherRatingOut, TopicRatingOut
from app.analysis.verify.lexicon import DEFAULT_LEXICON_DIR
from app.injection import PATTERNS_VERSION

__all__ = ["RULES_VERSION", "ResultSigner", "analysis_version"]

VERSION: Final = "v1"
# Bump when a verification rule or the event format changes in a way the files below do not show.
RULES_VERSION: Final = "rules-1"


def _lp(text: str) -> bytes:
    data = text.encode("utf-8")
    return len(data).to_bytes(4, "big") + data


@cache
def analysis_version() -> str:
    """``analysis-`` and 16 hex characters."""
    digest = hashlib.sha256()
    parts = [
        RULES_VERSION,
        PATTERNS_VERSION,
        PromptTemplate.RATE_TOPIC.value,
        PromptTemplate.RATE_OTHER.value,
        str(TopicRatingOut.model_json_schema()),
        str(OtherRatingOut.model_json_schema()),
    ]
    for part in parts:
        digest.update(_lp(part))
    for path in sorted(Path(DEFAULT_LEXICON_DIR).glob("*.json")):
        digest.update(_lp(path.name))
        digest.update(path.read_bytes())
    return "analysis-" + digest.hexdigest()[:16]


class ResultSigner:
    def __init__(self) -> None:
        self._key = secrets.token_bytes(32)

    def sign(  # noqa: PLR0913
        self,
        *,
        digest: str,
        version: str,
        domain: str,
        side: str,
        model: str,
        language: str,
        flags_hash: str,
        result_hash: str,
    ) -> str:
        parts = (VERSION, digest, version, domain, side, model, language, flags_hash, result_hash)
        return hmac.new(self._key, b"".join(_lp(p) for p in parts), hashlib.sha256).hexdigest()
