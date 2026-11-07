"""Verification by code (Layer 4, ADR 0019 points 3 and 4). Pure; offsets and codes out."""

from app.analysis.verify.index import DocumentIndex, build_document_index
from app.analysis.verify.lexicon import LEXICON, Lexicon, LexiconError, load_lexicon
from app.analysis.verify.model import (
    Clause,
    ClosureEntry,
    Completeness,
    DocFlag,
    DocumentContext,
    Evidence,
    Finding,
    MissingTopicFinding,
    NumericValue,
    QuoteCheck,
    RatedFinding,
    Rating,
    Reason,
    Span,
    TaggingState,
    TopicInfo,
    TopicState,
    ValueIn,
    ValueOut,
    ValueStatus,
)
from app.analysis.verify.quote import expand_quote, verify_quote
from app.analysis.verify.refs import find_references, reference_closure
from app.analysis.verify.rules import apply_green_rules, verify_value
from app.analysis.verify.topics import (
    document_completeness,
    missing_topic_findings,
    other_clause_ids,
)

__all__ = [
    "LEXICON",
    "Clause",
    "ClosureEntry",
    "Completeness",
    "DocFlag",
    "DocumentContext",
    "DocumentIndex",
    "Evidence",
    "Finding",
    "Lexicon",
    "LexiconError",
    "MissingTopicFinding",
    "NumericValue",
    "QuoteCheck",
    "RatedFinding",
    "Rating",
    "Reason",
    "Span",
    "TaggingState",
    "TopicInfo",
    "TopicState",
    "ValueIn",
    "ValueOut",
    "ValueStatus",
    "apply_green_rules",
    "build_document_index",
    "document_completeness",
    "expand_quote",
    "find_references",
    "load_lexicon",
    "missing_topic_findings",
    "other_clause_ids",
    "reference_closure",
    "verify_quote",
    "verify_value",
]
