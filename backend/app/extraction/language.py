# ruff: noqa: RUF002, RUF003 - Cyrillic letters are the point of this module
"""Rule-based language detection of extracted text (S3-T1 AC5; no dependency).

Only letters count: Latin ``A-Z a-z`` and Cyrillic (U+0400 to U+04FF).

1. Fewer than ``MIN_LETTERS`` letters → ``unknown``.
2. Latin letters are counted as English.
3. Cyrillic letters are shared between Ukrainian and Russian by their marker
   letters: Ukrainian-only ``і ї є ґ`` and Russian-only ``ы э ъ ё``. Each marker
   count is divided by the usual share of those letters in running text of that
   language (``UK_MARKER_RATE``, ``RU_MARKER_RATE``), which estimates how many letters
   of that language the text holds. Cyrillic text without a marker letter is not
   assigned to a language.
4. A language is significant when its estimated share of all letters is at least
   ``SIGNIFICANT_SHARE``. Two or more significant languages → ``mixed``; exactly
   one → that language; none (Cyrillic without markers) → ``unknown``.

So an English contract with one Ukrainian name stays ``en``, a Ukrainian contract
with a Latin product name stays ``uk``, and a bilingual contract is ``mixed``.
"""

from __future__ import annotations

from collections import Counter
from typing import Final

from app.extraction.model import Language

MIN_LETTERS: Final = 20
SIGNIFICANT_SHARE: Final = 0.2
# Usual share of the marker letters among all letters of a running text.
UK_MARKER_RATE: Final = 0.06  # і about 5.5 %, ї and є about 0.5 % each
RU_MARKER_RATE: Final = 0.022  # ы about 1.9 %, э, ё and ъ together about 0.3 %

UK_MARKERS: Final = frozenset("іїєґІЇЄҐ")
RU_MARKERS: Final = frozenset("ыэъёЫЭЪЁ")
_CYRILLIC_FIRST: Final = 0x0400
_CYRILLIC_LAST: Final = 0x04FF


def detect_language(text: str) -> Language:
    latin = cyrillic = uk_markers = ru_markers = 0
    for char, count in Counter(text).items():
        if not char.isalpha():
            continue
        if char.isascii():
            latin += count
        elif _CYRILLIC_FIRST <= ord(char) <= _CYRILLIC_LAST:
            cyrillic += count
            if char in UK_MARKERS:
                uk_markers += count
            elif char in RU_MARKERS:
                ru_markers += count
    letters = latin + cyrillic
    if letters < MIN_LETTERS:
        return "unknown"

    uk_score = uk_markers / UK_MARKER_RATE
    ru_score = ru_markers / RU_MARKER_RATE
    estimated: dict[Language, float] = {"en": latin}
    if uk_score + ru_score > 0:
        estimated["uk"] = cyrillic * uk_score / (uk_score + ru_score)
        estimated["ru"] = cyrillic * ru_score / (uk_score + ru_score)
    significant = [
        lang for lang, count in estimated.items() if count >= SIGNIFICANT_SHARE * letters
    ]
    unassigned_cyrillic = cyrillic if uk_score + ru_score == 0 else 0
    if len(significant) > 1 or (significant and unassigned_cyrillic >= SIGNIFICANT_SHARE * letters):
        return "mixed"
    if len(significant) == 1:
        return significant[0]
    return "unknown"
