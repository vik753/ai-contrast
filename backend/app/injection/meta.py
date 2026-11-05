"""Topic meta-word rule (ADR 0017 point 3 rule 6). For topic texts only, never for clauses.

A topic name, label, value or synonym never needs to address an AI, so any word of the
checked-in meta lists (instruction words, assistant and AI words, "language model", a rating
verb followed by a colour or a favourable word) refuses the text. Matching runs on the same
folded view as Layer 2 (homoglyph, full-width and math-letter variants meet the same entry).
The text is short (the caller checks the length first), so the scan is linear and cheap.
"""

from __future__ import annotations

from app.injection import patterns as p
from app.injection.scanner import WORD, WordSet, matching_view

__all__ = ["has_meta_word"]

_INSTRUCTION = WordSet(p.INSTRUCTION_WORDS)
_STRONG_AI = WordSet(p.AI_WORDS)
_LANGUAGE = WordSet(p.LANGUAGE_WORDS)
_MODEL = WordSet(p.MODEL_WORDS)
_RATE = WordSet(p.META_RATE_VERBS + p.META_RATING_AS)
_COLOUR = WordSet(p.META_RATING_WORDS)
_FILLERS = WordSet(p.BARE_FILLERS)
_MAX_LINKS = 3


def has_meta_word(text: str) -> bool:
    """``True`` if the text holds a meta word (see the module docstring)."""
    words = [match.group() for match in WORD.finditer(matching_view(text))]
    for index, word in enumerate(words):
        if word in _INSTRUCTION or word in _STRONG_AI:
            return True
        following = words[index + 1 : index + 1 + _MAX_LINKS + 1]
        if word in _LANGUAGE and following[:1] and following[0] in _MODEL:
            return True
        if word in _RATE:
            for nxt in following:
                if nxt in _COLOUR:
                    return True
                if nxt not in _FILLERS:
                    break
    return False
