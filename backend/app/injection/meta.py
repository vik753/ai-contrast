"""Topic meta-word rule (ADR 0017 point 3 rule 6). For topic texts only, never for clauses.

A single meta word never refuses a text. The rule looks for combinations that address an AI:
(a) an AI word with an instruction word, a rating verb or a colour, or an AI word right after
"for", "to" or "для"; (b) an instruction word with a hidden qualifier; (c) a rating verb with a
colour or favourable word, or a colour with a quantifier or object. Matching runs on the same
folded view as Layer 2. The text is short (the caller checks the length first). Layer 2 and this
rule are best effort; the guarantees are ratings by code, directions only from the catalog or
the client, and one document per call.
"""

from __future__ import annotations

from app.injection import patterns as p
from app.injection.scanner import WORD, WordSet, colour_rating, matching_view

__all__ = ["has_meta_word"]

_INSTRUCTION = WordSet(p.META_INSTRUCTION_WORDS)
_ADDRESS = WordSet(p.META_ADDRESS_WORDS)
_AI = WordSet(p.AI_WORDS)
_LANGUAGE = WordSet(p.LANGUAGE_WORDS)
_MODEL = WordSet(p.MODEL_WORDS)
_NEURAL = WordSet(p.NEURAL_WORDS)
_NET = WordSet(p.NET_WORDS)
_HIDDEN = WordSet(p.HIDDEN_QUALIFIERS)
_FOR = WordSet(p.FOR_WORDS)
_THE = WordSet(p.THE_WORDS)
_RATE = WordSet(p.META_RATE_VERBS)
_RATING_AS = WordSet(p.META_RATING_AS)
_AS = WordSet(p.AS_WORDS)
_COLOUR = WordSet(p.COLOUR_WORDS)
_RATING_WORD = WordSet(p.META_RATING_WORDS)
_FILLERS = WordSet(p.BARE_FILLERS)
_MAX_LINKS = 3


def _ai_end(words: list[str], index: int) -> int | None:
    """Index after an AI word (or a two-word AI name) at ``words[index]``, else ``None``."""
    word = words[index]
    if word in _AI:
        return index + 1
    second = words[index + 1] if index + 1 < len(words) else ""
    if word == "a" and second == "i":  # the spaced "a i"
        return index + 2
    if (word in _LANGUAGE and second in _MODEL) or (word in _NEURAL and second in _NET):
        return index + 2
    return None


def _address_next(words: list[str], index: int) -> bool:
    """A whole-word prompt or command is followed by "for", "to", "для" or an AI word."""
    if index + 1 >= len(words):
        return False
    return words[index + 1] in _FOR or _ai_end(words, index + 1) is not None


def _rated_with_colour(words: list[str], index: int) -> bool:
    """A rating verb (or "rating as") followed, after linking words only, by a colour word."""
    word = words[index]
    following = words[index + 1 : index + 2 + _MAX_LINKS]
    if word in _RATING_AS and (not following or following[0] not in _AS):
        return False
    for nxt in following:
        if nxt in _RATING_WORD:
            return True
        if nxt not in _FILLERS:
            break
    return False


def has_meta_word(text: str) -> bool:
    """``True`` if the text holds a refused combination (see the module docstring)."""
    words = [match.group() for match in WORD.finditer(matching_view(text))]
    ai = instruction = hidden = rating = False
    for index, word in enumerate(words):
        end = _ai_end(words, index)
        if end is not None:
            ai = True
            if index > 0 and (
                words[index - 1] in _FOR
                or (index > 1 and words[index - 1] in _THE and words[index - 2] in _FOR)
            ):
                return True
        if word in _INSTRUCTION or (word in _ADDRESS and _address_next(words, index)):
            instruction = True
        hidden = hidden or word in _HIDDEN
        if word in _RATE or word in _RATING_AS:
            if _rated_with_colour(words, index):
                return True
            rating = True
        if word in _COLOUR:
            if colour_rating(
                words[max(0, index - 3) : index], [(w, 0, 0) for w in words[index + 1 : index + 4]]
            ):
                return True
            rating = True
    return (ai and (instruction or rating)) or (instruction and hidden)
