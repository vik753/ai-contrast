"""Loader of the checked-in lexicons (``shared/lexicon/``). Validated at import; fail closed.

Entries are literal words and phrases, never regular expressions. A bad file raises
``LexiconError`` and the application does not start.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final

__all__ = ["LANGS", "LEXICON", "Lexicon", "LexiconError", "load_lexicon"]

LANGS: Final = ("en", "uk", "ru")
DEFAULT_LEXICON_DIR: Final = Path(__file__).resolve().parents[4] / "shared" / "lexicon"
_VERSIONS: Final = frozenset({1, 2})
_MAX_ENTRIES: Final = 1000
_MAX_ENTRY_LEN: Final = 100
_MAX_FILE_BYTES: Final = 200_000
_UNITS: Final = (
    "UAH",
    "EUR",
    "USD",
    "days",
    "working_days",
    "months",
    "years",
    "hours",
    "percent_of_sum",
    "percent_of_loss",
)
_ATOMS: Final = frozenset(Decimal(i) for i in (*range(20), *range(20, 100, 10), 100))
_MAX_PHRASE_WORDS: Final = 6


class LexiconError(Exception):
    """A lexicon file is missing or malformed."""


Words = dict[str, tuple[str, ...]]  # language -> entries


@dataclass(frozen=True, slots=True)
class Lexicon:
    exception_markers: Words
    global_override_markers: Words
    ref_prefixes: Words
    ref_joiners: Words
    ref_range_words: Words
    ref_self: Words
    relative_references: Words
    percent_marks: Words
    units: dict[str, Words]
    number_words: dict[str, dict[Decimal, tuple[str, ...]]]
    scale_words: Words
    safe_after_number: Words
    never_end: frozenset[str]
    may_end: frozenset[str]


def _fail(file: str, why: str) -> LexiconError:
    return LexiconError(f"{file}: {why}")


def _read(directory: Path, name: str) -> dict[str, Any]:
    path = directory / name
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            raise _fail(name, "file too large")
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _fail(name, "cannot read or parse") from exc
    if not isinstance(data, dict) or data.get("version") not in _VERSIONS:
        raise _fail(name, "unknown version")
    return data


def _entries(file: str, raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list) or not raw or len(raw) > _MAX_ENTRIES:
        raise _fail(file, "entry list missing, empty or too long")
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip() or len(item) > _MAX_ENTRY_LEN:
            raise _fail(file, "bad entry")
        out.append(item)
    return tuple(out)


def _words(file: str, raw: object, *, allow_note: bool = False) -> Words:
    if not isinstance(raw, dict):
        raise _fail(file, "language map missing")
    keys = set(raw) - ({"note"} if allow_note else set())
    if keys != set(LANGS):
        raise _fail(file, "languages must be en, uk, ru")
    return {lang: _entries(file, raw[lang]) for lang in LANGS}


def _numbers(raw: object) -> dict[str, dict[Decimal, tuple[str, ...]]]:
    name = "number_words.json"
    if not isinstance(raw, dict):
        raise _fail(name, "missing")
    result: dict[str, dict[Decimal, tuple[str, ...]]] = {}
    for lang in LANGS:
        table = raw.get(lang)
        if not isinstance(table, dict):
            raise _fail(name, f"{lang} missing")
        parsed: dict[Decimal, tuple[str, ...]] = {}
        for key, value in table.items():
            try:
                number = Decimal(key)
            except (InvalidOperation, TypeError) as exc:
                raise _fail(name, "bad key") from exc
            if not number.is_finite() or number < 0:
                raise _fail(name, "bad key")
            parsed[number] = _entries(name, value)
        if not set(parsed) >= _ATOMS:
            raise _fail(name, f"{lang} atoms incomplete")
        for entries in parsed.values():
            if any(len(e.split()) > _MAX_PHRASE_WORDS for e in entries):
                raise _fail(name, "entry too long")
        result[lang] = parsed
    return result


def load_lexicon(directory: Path | None = None) -> Lexicon:
    """Read and validate every lexicon file."""
    base = directory if directory is not None else _default_dir()
    exc = _read(base, "exception_markers.json")
    glob = _read(base, "global_override_markers.json")
    refs = _read(base, "clause_references.json")
    rel = _read(base, "relative_references.json")
    units = _read(base, "unit_words.json")
    nums = _read(base, "number_words.json")
    abbr = _read(base, "sentence_abbreviations.json")
    unit_map = units.get("units")
    if not isinstance(unit_map, dict) or set(unit_map) != set(_UNITS):
        raise _fail("unit_words.json", "units must match the catalog")
    never = _words("sentence_abbreviations.json", abbr.get("never_end"))
    may = _words("sentence_abbreviations.json", abbr.get("may_end"), allow_note=True)
    return Lexicon(
        exception_markers=_words("exception_markers.json", {k: exc.get(k) for k in LANGS}),
        global_override_markers=_words(
            "global_override_markers.json", {k: glob.get(k) for k in LANGS}
        ),
        ref_prefixes=_words("clause_references.json", refs.get("prefixes")),
        ref_joiners=_words("clause_references.json", refs.get("joiners")),
        ref_range_words=_words("clause_references.json", refs.get("range_words")),
        ref_self=_words("clause_references.json", refs.get("self_reference")),
        relative_references=_words("relative_references.json", {k: rel.get(k) for k in LANGS}),
        percent_marks=_words("unit_words.json", units.get("percent_marks")),
        units={u: _words("unit_words.json", unit_map[u], allow_note=True) for u in _UNITS},
        number_words=_numbers({k: nums.get(k) for k in LANGS}),
        scale_words=_words("number_words.json", nums.get("scale_words")),
        safe_after_number=_words("number_words.json", nums.get("safe_after_number")),
        never_end=frozenset(e.lower() for lang in LANGS for e in never[lang]),
        may_end=frozenset(e.lower() for lang in LANGS for e in may[lang]),
    )


def _default_dir() -> Path:
    override = os.environ.get("LEXICON_DIR")
    return Path(override) if override else DEFAULT_LEXICON_DIR


LEXICON: Final = load_lexicon()
