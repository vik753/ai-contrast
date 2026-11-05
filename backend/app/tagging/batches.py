"""Batches and the worst-case cost of the tagging calls (ADR 0018 points 3 and 5).

A batch holds at most 40 clauses and 12,000 characters of clause text (a longer single clause
is a batch of its own: nothing is cut). A request has at most 60 batches. The worst case of a
batch is one tagging call and one check call, each with one repair call.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from app.ai.prompts import PromptTemplate
from app.limits.free import topic_neurons
from app.pseudo.gate import ConfirmedTopic
from app.tagging.schemas import MAX_TAGS_PER_CLAUSE

__all__ = [
    "MAX_BATCHES",
    "MAX_BATCH_CHARS",
    "MAX_BATCH_CLAUSES",
    "WORST_CASE_CALLS_PER_BATCH",
    "check_max_tokens",
    "plan_batches",
    "tag_max_tokens",
    "worst_case",
]

MAX_BATCH_CHARS: Final = 12_000
MAX_BATCH_CLAUSES: Final = 40
MAX_BATCHES: Final = 60
# Tagging call and check call, each followed by one repair call.
WORST_CASE_CALLS_PER_BATCH: Final = 4
_OVERHEAD_CHARS: Final = 600  # delimiters, schema line breaks, repair note
_CLAUSE_OVERHEAD_CHARS: Final = 12  # "[c1234]" line and the blank line
_PAIR_CHARS: Final = 12  # "c1234 T12" and the newline
_TOPIC_OVERHEAD_CHARS: Final = 12  # "T12: " and " - "
# ``topic_neurons`` counts 3 characters per token; Cyrillic needs about 2 (as in the topic jobs).
_CYRILLIC_NUM: Final = 3
_CYRILLIC_DEN: Final = 2


def plan_batches(lengths: Sequence[int]) -> list[tuple[int, int]]:
    """Consecutive ``(start, end)`` index ranges over clause lengths, in order."""
    batches: list[tuple[int, int]] = []
    start = 0
    chars = 0
    for index, length in enumerate(lengths):
        count = index - start
        if count and (count >= MAX_BATCH_CLAUSES or chars + length > MAX_BATCH_CHARS):
            batches.append((start, index))
            start, chars = index, 0
        chars += length
    if lengths:
        batches.append((start, len(lengths)))
    return batches


def tag_max_tokens(clauses: int) -> int:
    """Output cap of a tagging call for ``clauses`` clauses."""
    return min(4096, 512 + 60 * clauses)


def check_max_tokens(pairs: int) -> int:
    """Output cap of a check call for ``pairs`` asked pairs."""
    return min(4096, 256 + 24 * pairs)


def _neurons(chars: int, max_tokens: int) -> int:
    scaled = -(-chars * _CYRILLIC_NUM // _CYRILLIC_DEN)
    return topic_neurons(scaled, max_tokens, repair=True)


def worst_case(
    batches: Sequence[tuple[int, int]], lengths: Sequence[int], topics: Sequence[ConfirmedTopic]
) -> tuple[int, int]:
    """``(calls, Neurons)`` if every batch needs a tagging call, a check call and a repair for
    each (a check call may ask five pairs per clause)."""
    topics_chars = sum(
        len(topic.title) + len(topic.description) + _TOPIC_OVERHEAD_CHARS for topic in topics
    )
    tag_base = len(PromptTemplate.TAG_CLAUSES.value) + topics_chars + _OVERHEAD_CHARS
    check_base = len(PromptTemplate.CHECK_TAGS.value) + topics_chars + _OVERHEAD_CHARS
    neurons = 0
    for start, end in batches:
        count = end - start
        text = sum(lengths[start:end]) + count * _CLAUSE_OVERHEAD_CHARS
        pairs = count * min(MAX_TAGS_PER_CLAUSE, len(topics))
        neurons += _neurons(tag_base + text, tag_max_tokens(count))
        neurons += _neurons(check_base + text + pairs * _PAIR_CHARS, check_max_tokens(pairs))
    return len(batches) * WORST_CASE_CALLS_PER_BATCH, neurons
