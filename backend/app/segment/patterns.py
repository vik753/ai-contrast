"""Line patterns of the segmenter (ADR 0014 points 3 and 6).

Every pattern is anchored, has bounded repetition and no nested quantifier, and is
applied to one line with ``match`` only (never ``search`` over a text), so the time is
linear in the line length (ADR 0009). A line is at most one block line; very long
lines are cut by the callers before they reach the expensive parts.
"""

from __future__ import annotations

import re
from typing import Final, NamedTuple

MAX_HEADING_CHARS: Final = 150
MAX_RUNNING_CHARS: Final = 120
_FINAL_PUNCTUATION: Final = ".,;:!?…"

# Decimal: `1.`, `1.2.`, `1.2.3`, `1)`, `1.2)`. Up to six levels; the first of up to four digits.
_DECIMAL: Final = re.compile(r"([0-9]{1,4}(?:\.[0-9]{1,3}){0,5})([.)]?)(?=\s|\Z)")
# Article words and the paragraph sign. The word forms need a delimiter (or the line end),
# so that "Section 5 of this agreement" is not a clause start.
_WORD: Final = re.compile(
    r"(?:стаття|статья|article|section|розділ|раздел|пункт)\s{1,3}"
    r"([0-9]{1,4}(?:\.[0-9]{1,3}){0,4})(?:[.):](?=\s|\Z)|\Z)",
    re.IGNORECASE,
)
_PARAGRAPH: Final = re.compile(r"§\s{0,2}([0-9]{1,4}(?:\.[0-9]{1,3}){0,4})(?:[.):])?(?=\s|\Z)")
_ROMAN: Final = re.compile(r"([IVX]{1,6})\.(?=\s|\Z)")
_ROMAN_VALUES: Final = {"I": 1, "V": 5, "X": 10}

# Closed list of requisites headings (ADR 0008 point 2), compared with the whole heading
# line, case-insensitively (casefold), after the optional number prefix.
REQUISITES_HEADINGS: Final = frozenset(
    {
        "реквізити та підписи сторін",
        "реквизиты и подписи сторон",
        "реквізити сторін",
        "реквизиты сторон",
        "підписи сторін",
        "подписи сторон",
        "адреси та реквізити сторін",
        "адреса та реквізити сторін",
        "адреса и реквизиты сторон",
        "юридичні адреси та реквізити сторін",
        "юридические адреса и реквизиты сторон",
        "signatures",
        "signatures of the parties",
        "details of the parties",
        "party details",
        "parties' details",
    }
)
# An all-capitals heading that starts with one of these opens a new numbering scope.
ANNEX_WORDS: Final = (
    "ANNEX",
    "APPENDIX",
    "SCHEDULE",
    "EXHIBIT",
    "ДОДАТОК",
    "ДОДАТКИ",
    "ПРИЛОЖЕНИЕ",
    "ПРИЛОЖЕНИЯ",
)

STYLE_ARABIC: Final = "a"
STYLE_ROMAN: Final = "r"
HEADING_NONE: Final = 0
HEADING_CAPS: Final = 1
HEADING_REQUISITES: Final = 2


class Start(NamedTuple):
    """A clause start line: the number as written, its parts, and where the title begins."""

    number: str
    parts: tuple[int, ...]
    style: str
    title_offset: int


def _title_offset(line: str, end: int) -> int:
    rest = line[end:]
    return end + len(rest) - len(rest.lstrip())


def _arabic(line: str, number: str, end: int) -> Start:
    return Start(
        number,
        tuple(int(part) for part in number.split(".")),
        STYLE_ARABIC,
        _title_offset(line, end),
    )


def _decimal(line: str) -> Start | None:
    match = _DECIMAL.match(line)
    if match is None:
        return None
    number, delimiter = match.group(1), match.group(2)
    if not delimiter and "." not in number:
        return None
    return _arabic(line, number, match.end())


def _roman(line: str) -> Start | None:
    match = _ROMAN.match(line)
    if match is None:
        return None
    number = match.group(1)
    return Start(number, (roman_value(number),), STYLE_ROMAN, _title_offset(line, match.end()))


def _word_or_paragraph(line: str) -> Start | None:
    match = _PARAGRAPH.match(line) if line[0] == "§" else _WORD.match(line)
    return None if match is None else _arabic(line, match.group(1), match.end())


def parse_start(line: str) -> Start | None:
    """The clause start that ``line`` (stripped, not empty) begins with, or ``None``."""
    first = line[0]
    if "0" <= first <= "9":
        return _decimal(line)
    if first in "IVX":
        return _roman(line)
    if first == "§" or first.isalpha():
        return _word_or_paragraph(line)
    return None


def roman_value(number: str) -> int:
    total = 0
    previous = 0
    for char in reversed(number):
        value = _ROMAN_VALUES[char]
        total += -value if value < previous else value
        previous = max(previous, value)
    return total


def is_title(line: str, title: str) -> bool:
    """A section title: short, not empty, no final punctuation."""
    return bool(title) and len(line) <= MAX_HEADING_CHARS and title[-1] not in _FINAL_PUNCTUATION


def is_requisites_title(title: str) -> bool:
    return title.casefold() in REQUISITES_HEADINGS


def unnumbered_heading(line: str) -> int:
    """`HEADING_CAPS`, `HEADING_REQUISITES` or `HEADING_NONE` for an unnumbered line."""
    if len(line) > MAX_HEADING_CHARS or line[-1] in _FINAL_PUNCTUATION:
        return HEADING_NONE
    if is_requisites_title(line):
        return HEADING_REQUISITES
    return HEADING_CAPS if line.isupper() else HEADING_NONE


def opens_clause_text(line: str) -> bool:
    """A numbered start that carries clause text (not a section title)."""
    start = parse_start(line)
    return start is not None and not is_title(line, line[start.title_offset :])


def is_structural(line: str) -> bool:
    """Clause start or heading line (never collapsed into a running clause)."""
    return parse_start(line) is not None or unnumbered_heading(line) != HEADING_NONE
