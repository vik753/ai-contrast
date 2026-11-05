"""``tagging_version``: changes with the keyword rules, the risk terms or Layer 2 patterns."""

from __future__ import annotations

import hashlib

from app.injection import patterns
from app.tagging import keywords, risk_terms

__all__ = ["tagging_version"]


def tagging_version() -> str:
    """``tag-`` and 16 hex characters; read at call time."""
    parts = (
        keywords.KEYWORD_RULES_VERSION,
        risk_terms.RISK_TERMS_VERSION,
        patterns.PATTERNS_VERSION,
    )
    return "tag-" + hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:16]
