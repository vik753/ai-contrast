"""``tagging_version``: changes with the keyword rules, the risk terms, Layer 2 patterns or the
tagging prompts (ADR 0018 point 1)."""

from __future__ import annotations

import hashlib

from app.ai.prompts import PromptTemplate
from app.injection import patterns
from app.tagging import keywords, risk_terms

__all__ = ["tagging_version"]


def tagging_version() -> str:
    """``tag-`` and 16 hex characters; read at call time."""
    parts = (
        keywords.KEYWORD_RULES_VERSION,
        risk_terms.RISK_TERMS_VERSION,
        patterns.PATTERNS_VERSION,
        PromptTemplate.TAG_CLAUSES.value,
        PromptTemplate.CHECK_TAGS.value,
    )
    return "tag-" + hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:16]
