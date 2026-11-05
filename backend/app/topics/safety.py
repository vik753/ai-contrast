"""Topic text safety pass (ADR 0017 point 3; threat model T5, T11).

Every topic text that did not come from a trusted source goes through ``check_topic_text``
before it is used anywhere. Order: length, Layer 1 (clean and NFC, never fixed silently),
grammar, placeholder look-alikes on the skeleton, the identifier detector (ADR 0015), Layer 2.
The text of a refusal never leaves this module: ``TopicTextError`` holds a code, offsets and
a field name only.
"""

from __future__ import annotations

import enum
import unicodedata
from typing import Final

from app.injection import scan
from app.injection.meta import has_meta_word
from app.pseudo.detector import TooManyIdentifiersError, detect
from app.pseudo.matching import SKELETON
from app.segment.model import Clause
from app.textclean import TextCleaner
from app.topics.stopwords import STOP_WORDS

__all__ = ["TextKind", "TopicTextError", "check_topic_text"]

INVALID: Final = "invalid_topic_text"
IDENTIFIER: Final = "topic_contains_identifier"
FLAGGED: Final = "topic_flagged"
MIN_SYNONYM_LETTERS: Final = 3
_PUNCTUATION: Final = frozenset(" -'\u2019.,()/%\u2116")
_DIGITS: Final = frozenset("0123456789")
_SCRIPTS: Final = ("LATIN ", "CYRILLIC ")


class TextKind(enum.StrEnum):
    NAME = "name"
    DESCRIPTION = "description"
    LABEL = "label"
    VALUE = "value"
    SYNONYM = "synonym"


MAX_CHARS: Final = {
    TextKind.NAME: 80,
    TextKind.DESCRIPTION: 200,
    TextKind.LABEL: 200,
    TextKind.VALUE: 60,
    TextKind.SYNONYM: 60,
}


class TopicTextError(Exception):
    """A topic text is refused. ``str(error)`` is the code; it never holds the text."""

    def __init__(
        self,
        code: str,
        spans: tuple[tuple[int, int], ...] = (),
        field: str | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.spans = spans
        self.field = field


def _letter_of_allowed_script(char: str) -> bool:
    return char.isalpha() and unicodedata.name(char, "").startswith(_SCRIPTS)


def _grammar_ok(text: str) -> bool:
    """Letters of Latin or Cyrillic, marks after a letter, ASCII digits, a few punctuation marks."""
    after_letter = False
    for char in text:
        if char in _DIGITS or char in _PUNCTUATION:
            after_letter = False
        elif _letter_of_allowed_script(char):
            after_letter = True
        elif unicodedata.category(char).startswith("M") and after_letter:
            continue
        else:
            return False
    return True


def _skeleton_has_bracket(text: str) -> bool:
    view = unicodedata.normalize("NFKC", text).translate(SKELETON)
    return any(char in view for char in "[]⟦⟧")


def _clause(text: str) -> Clause:
    return Clause(
        id="c1",
        number=None,
        level=0,
        part_index=0,
        section_kind=None,
        part="body",
        pages=[],
        spans=[(0, 0, len(text))],
        heading_span=None,
    )


def _identifier_spans(text: str) -> tuple[tuple[int, int], ...]:
    try:
        detection = detect([text], [_clause(text)])
    except TooManyIdentifiersError:
        raise TopicTextError(INVALID) from None
    spans = {
        (start, end)
        for entity in detection.entities
        for block, start, end in entity.spans
        if block == 0
    }
    return tuple(sorted(spans))


def _synonym_ok(text: str, lang: str | None) -> bool:
    if sum(char.isalpha() for char in text) < MIN_SYNONYM_LETTERS:
        return False
    word = text.strip().lower()
    lists = STOP_WORDS.values() if lang is None else (STOP_WORDS.get(lang, frozenset()),)
    return not any(word in stop for stop in lists)


def _flagged(text: str) -> bool:
    """A Layer 2 hit (any class) or a meta word (topics only)."""
    return bool(scan(text)) or has_meta_word(text)


def check_topic_text(text: str, kind: TextKind, lang: str | None = None) -> None:
    """Return ``None`` if the text is accepted; raise ``TopicTextError`` otherwise.

    ``lang`` (``en``, ``uk``, ``ru``) selects the stop-word list for a synonym; ``None``
    checks all three.
    """
    if not 1 <= len(text) <= MAX_CHARS[kind]:
        raise TopicTextError(INVALID)
    if TextCleaner().clean(text) != text:
        raise TopicTextError(INVALID)
    if not _grammar_ok(text):
        # A look-alike spelling (full-width, math letters) fails the grammar; if it also
        # holds a Layer 2 or meta-word hit, the more telling code wins.
        raise TopicTextError(
            FLAGGED if not _skeleton_has_bracket(text) and _flagged(text) else INVALID
        )
    if kind is TextKind.SYNONYM and not _synonym_ok(text, lang):
        raise TopicTextError(INVALID)
    if _skeleton_has_bracket(text):
        raise TopicTextError(INVALID)
    spans = _identifier_spans(text)
    if spans:
        raise TopicTextError(IDENTIFIER, spans)
    if _flagged(text):
        raise TopicTextError(FLAGGED)
