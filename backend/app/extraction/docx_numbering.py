"""List numbering labels from ``numbering.xml`` (S3-T2b; threat model T5).

Clause numbers are often automatic: the person reads "3.1." although the text of the
paragraph does not contain it. This module parses the abstract definitions and the
``w:num`` instances, and keeps the counters while the walker meets numbered
paragraphs in document order.

Rules (ECMA-376 17.9):

- ``w:num`` instances that reference the same ``w:abstractNum`` continue one sequence,
  unless the ``w:num`` has a ``w:startOverride``: then it has its own sequence.
- A level restarts after a paragraph of a higher level (``w:lvlRestart`` 0 = never,
  *n* = only after level *n* or higher). ``w:isLgl`` shows the earlier levels in
  decimal. ``w:lvlOverride`` may replace a level definition or its start.
- A format we do not know becomes decimal and the walker warns
  ``numbering_approximate``.

Caps fail closed with ``suspicious_package``: at most 9 levels, ``MAX_DEFINITIONS``
abstract definitions and ``MAX_DEFINITIONS`` instances.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Final
from xml.etree.ElementTree import Element

from app.extraction.docx_styles import VAL, W
from app.extraction.docx_xml import END, START, suspicious

MAX_LEVELS: Final = 9
MAX_DEFINITIONS: Final = 10_000
APPROXIMATE: Final = "numbering_approximate"

_W: Final = "{" + W + "}"
_PLACEHOLDER: Final = re.compile(r"%([1-9])")
_MAX_ROMAN: Final = 3999
_MAX_COUNTER: Final = 1_000_000

# Alphabets of Word's Cyrillic counting (letters Word does not use are left out).
_RUSSIAN: Final = "абвгдежзиклмнопрстуфхцчшщэюя"
_UKRAINIAN: Final = "абвгдежзиклмнопрстуфхцчшщюя"
_LATIN: Final = "abcdefghijklmnopqrstuvwxyz"
_ROMAN: Final = (
    (1000, "m"),
    (900, "cm"),
    (500, "d"),
    (400, "cd"),
    (100, "c"),
    (90, "xc"),
    (50, "l"),
    (40, "xl"),
    (10, "x"),
    (9, "ix"),
    (5, "v"),
    (4, "iv"),
    (1, "i"),
)
KNOWN_FORMATS: Final = frozenset(
    {
        "decimal",
        "decimalZero",
        "lowerLetter",
        "upperLetter",
        "lowerRoman",
        "upperRoman",
        "russianLower",
        "russianUpper",
        "ukrainianCounting",
        "bullet",
        "none",
    }
)


@dataclass(frozen=True)
class Level:
    start: int = 1
    fmt: str = "decimal"
    text: str = ""
    restart: int | None = None
    is_lgl: bool = False


@dataclass
class Instance:
    """A ``w:num``: its abstract definition and overrides."""

    abstract_id: str
    levels: dict[int, Level] = field(default_factory=dict)  # w:lvlOverride/w:lvl
    starts: dict[int, int] = field(default_factory=dict)  # w:startOverride


@dataclass
class Numbering:
    abstracts: dict[str, dict[int, Level]] = field(default_factory=dict)
    nums: dict[str, Instance] = field(default_factory=dict)

    def level(self, num: Instance, ilvl: int) -> Level | None:
        override = num.levels.get(ilvl)
        if override is not None:
            return override
        return self.abstracts.get(num.abstract_id, {}).get(ilvl)


def _integer(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


class _LevelBuilder:
    def __init__(self) -> None:
        self.start = 1
        self.fmt = "decimal"
        self.text = ""
        self.restart: int | None = None
        self.is_lgl = False

    def set(self, tag: str, attrib: dict[str, str]) -> None:
        value = attrib.get(VAL)
        if tag == _W + "start":
            self.start = _integer(value, 1)
        elif tag == _W + "numFmt":
            self.fmt = value or "decimal"
        elif tag == _W + "lvlText":
            self.text = value or ""
        elif tag == _W + "lvlRestart":
            self.restart = _integer(value, 0)
        elif tag == _W + "isLgl":
            self.is_lgl = value not in ("0", "false", "off")

    def build(self) -> Level:
        return Level(self.start, self.fmt, self.text, self.restart, self.is_lgl)


def _ilvl(item: Element) -> int:
    value = _integer(item.get(_W + "ilvl"), -1)
    if not 0 <= value < MAX_LEVELS:
        raise suspicious()
    return value


def parse_numbering(events: Iterator[tuple[str, Any]]) -> Numbering:  # noqa: PLR0912, PLR0915 - one branch per element
    numbering = Numbering()
    stack: list[str] = []
    abstract: dict[int, Level] | None = None
    instance: Instance | None = None
    builder: _LevelBuilder | None = None
    ilvl = 0
    override_ilvl = 0
    for event, item in events:
        if event == START:
            stack.append(item.tag)
            depth = len(stack)
            tag = item.tag
            if depth == 2:  # noqa: PLR2004 - w:numbering/*
                if tag == _W + "abstractNum":
                    if len(numbering.abstracts) >= MAX_DEFINITIONS:
                        raise suspicious()
                    abstract = {}
                    numbering.abstracts.setdefault(item.get(_W + "abstractNumId") or "", abstract)
                elif tag == _W + "num":
                    if len(numbering.nums) >= MAX_DEFINITIONS:
                        raise suspicious()
                    instance = Instance("")
                    numbering.nums.setdefault(item.get(_W + "numId") or "", instance)
            elif depth == 3:  # noqa: PLR2004
                if abstract is not None and tag == _W + "lvl":
                    ilvl = _ilvl(item)
                    builder = _LevelBuilder()
                elif instance is not None and tag == _W + "abstractNumId":
                    instance.abstract_id = item.get(VAL) or ""
                elif instance is not None and tag == _W + "lvlOverride":
                    override_ilvl = _ilvl(item)
            elif depth == 4:  # noqa: PLR2004
                if abstract is not None and builder is not None:
                    builder.set(tag, item.attrib)
                elif instance is not None and stack[2] == _W + "lvlOverride":
                    if tag == _W + "startOverride":
                        instance.starts[override_ilvl] = _integer(item.get(VAL), 1)
                    elif tag == _W + "lvl":
                        ilvl = _ilvl(item)
                        builder = _LevelBuilder()
            elif depth == 5 and instance is not None and builder is not None:  # noqa: PLR2004
                builder.set(tag, item.attrib)
        elif event == END:
            depth = len(stack)
            if depth == 3 and abstract is not None and builder is not None:  # noqa: PLR2004
                abstract.setdefault(ilvl, builder.build())
                builder = None
            elif depth == 4 and instance is not None and builder is not None:  # noqa: PLR2004
                if stack[2] == _W + "lvlOverride":
                    instance.levels.setdefault(ilvl, builder.build())
                    builder = None
            elif depth == 2:  # noqa: PLR2004
                abstract = None
                instance = None
            stack.pop()
    return numbering


# --- Formats --------------------------------------------------------------------------------


def _alphabet(value: int, alphabet: str) -> str:
    """a, b, ... z, aa, bb, ... (Word repeats the letter)."""
    letters = len(alphabet)
    return alphabet[(value - 1) % letters] * ((value - 1) // letters + 1)


def _roman(value: int) -> str:
    out = ""
    for size, glyph in _ROMAN:
        while value >= size:
            out += glyph
            value -= size
    return out


def format_number(value: int, fmt: str) -> str:
    """The counter in a known format; callers check ``KNOWN_FORMATS`` first."""
    text = str(value)
    if value >= 1:
        if fmt == "decimalZero":
            text = f"{value:02d}"
        elif fmt in ("lowerLetter", "upperLetter"):
            text = _alphabet(value, _LATIN)
        elif fmt in ("lowerRoman", "upperRoman") and value <= _MAX_ROMAN:
            text = _roman(value)
        elif fmt in ("russianLower", "russianUpper"):
            text = _alphabet(value, _RUSSIAN)
        elif fmt == "ukrainianCounting":
            text = _alphabet(value, _UKRAINIAN)
    return text.upper() if fmt.endswith("Upper") or fmt.startswith("upper") else text


_BULLETS: Final = {"": "•", "": "▪", "": "➢", "": "❖"}


def _bullet(text: str) -> str:
    out = []
    for char in text:
        if "" <= char <= "":  # private use: a symbol-font glyph
            out.append(_BULLETS.get(char, "•"))
        else:
            out.append(char)
    return "".join(out)


# --- Counters -------------------------------------------------------------------------------


class Counters:
    """Counters per sequence, in document order."""

    def __init__(self, numbering: Numbering) -> None:
        self.numbering = numbering
        self.sequences: dict[tuple[str, str], list[int | None]] = {}
        self.approximate = False

    def label(self, num_id: str, ilvl: int) -> str | None:
        """Count one numbered paragraph and return its label (``None``: no label)."""
        if not 0 <= ilvl < MAX_LEVELS:
            raise suspicious()
        numbering = self.numbering
        num = numbering.nums.get(num_id)
        if num is None or num.abstract_id not in numbering.abstracts:
            return None
        level = numbering.level(num, ilvl)
        if level is None:
            return None
        key = ("n", num_id) if num.starts else ("a", num.abstract_id)
        values = self.sequences.setdefault(key, [None] * MAX_LEVELS)
        for deeper in range(ilvl + 1, MAX_LEVELS):
            definition = numbering.level(num, deeper)
            restart = definition.restart if definition is not None else None
            threshold = deeper if restart is None else restart
            if ilvl <= threshold - 1:
                values[deeper] = None
        current = values[ilvl]
        values[ilvl] = self._start(num, ilvl, level) if current is None else current + 1
        if (values[ilvl] or 0) > _MAX_COUNTER:
            raise suspicious()
        return self._text(num, level, values)

    def _start(self, num: Instance, ilvl: int, level: Level) -> int:
        return num.starts.get(ilvl, level.start)

    def _format(self, value: int, fmt: str, *, legal: bool) -> str:
        if legal and fmt not in ("bullet", "none"):
            fmt = "decimal"
        if fmt not in KNOWN_FORMATS:
            self.approximate = True
            fmt = "decimal"
        return format_number(value, fmt)

    def _text(self, num: Instance, level: Level, values: list[int | None]) -> str:
        if level.fmt == "bullet":
            return _bullet(level.text)
        if level.fmt == "none":
            return ""

        def substitute(match: re.Match[str]) -> str:
            index = int(match.group(1)) - 1
            other = self.numbering.level(num, index)
            if other is None:
                return ""
            value = values[index]
            if value is None:
                value = self._start(num, index, other)
            return self._format(value, other.fmt, legal=level.is_lgl)

        return _PLACEHOLDER.sub(substitute, level.text)
