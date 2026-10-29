# ruff: noqa: RUF001
"""Folded forms of the checked-in tables and the word helpers (ADR 0015 point 2).

Every table entry is folded with ``matching.fold`` (NFKC, skeleton, lower case), the same
function the detector applies to the text. The hash of the raw tables is the detector
version.
"""

from __future__ import annotations

import hashlib
import unicodedata
from functools import lru_cache
from typing import Final

from app.pseudo import tables
from app.pseudo.confusable_table import UNICODE_VERSION
from app.pseudo.matching import LATIN_TO_CYRILLIC, SKELETON, fold

RULES_VERSION: Final = "7"


def _runs(text: str) -> tuple[str, ...]:
    """Fold ``text`` and cut it into letter/digit runs."""
    folded = fold(text)
    runs: list[str] = []
    current: list[str] = []
    for char in folded:
        if char.isalnum():
            current.append(char)
        elif current:
            runs.append("".join(current))
            current = []
    if current:
        runs.append("".join(current))
    return tuple(runs)


def _keyword(entry: str | tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(entry, str):
        return _runs(entry)
    return tuple(part for item in entry for part in _runs(item))


def _build_context() -> dict[tuple[str, ...], frozenset[str]]:
    kinds: dict[tuple[str, ...], set[str]] = {}
    for kind, entries in tables.CONTEXT.items():
        for entry in entries:
            kinds.setdefault(_keyword(entry), set()).add(kind)
    return {key: frozenset(value) for key, value in kinds.items()}


CONTEXT_KINDS: Final = _build_context()
MAX_KEYWORD_RUNS: Final = max(len(key) for key in CONTEXT_KINDS)


def skeleton(text: str) -> str:
    """NFKC and skeleton, case kept (legal forms are case-sensitive)."""
    return unicodedata.normalize("NFKC", text).translate(SKELETON)


LEGAL_PREFIX: Final = frozenset(
    skeleton(form) for name in tables.LEGAL_FORMS_PREFIX for form in (name, name.upper())
)
LEGAL_SUFFIX: Final = frozenset(
    skeleton(form) for name in tables.LEGAL_FORMS_SUFFIX for form in (name, name.upper())
)
SOLE_TRADER: Final = frozenset(skeleton(form) for form in tables.SOLE_TRADER_FORMS)
ORG_NOUNS: Final = frozenset(fold(word) for word in tables.ORG_NOUNS)
ROLE_STEMS: Final = tuple(sorted({fold(word) for word in tables.ROLE_WORDS}, key=len))
NOT_NAMES: Final = frozenset(fold(word) for word in tables.NOT_NAMES)
# Words that begin a new item or a condition, never the rest of a wrapped address. The words
# of an address itself ("область", "район", "місто") are left out.
_ADDRESS_WORDS: Final = frozenset(
    fold(word)
    for word in (
        *("місто", "город", "city", "область", "oblast", "район"),
        *("територія", "територия", "territory"),
    )
)
WRAP_STOP_WORDS: Final = NOT_NAMES - _ADDRESS_WORDS
PERSON_ROLE_STEMS: Final = tuple(sorted({fold(word) for word in tables.PERSON_ROLE_WORDS}, key=len))
STREET_SUFFIXES: Final = frozenset(fold(word) for word in tables.STREET_SUFFIXES)
MONTHS: Final = frozenset(fold(word) for word in tables.MONTHS)
SOLE_TRADER_LEADS: Final = tuple(fold(word) for word in tables.SOLE_TRADER_LEADS)
SOLE_TRADER_NOUNS: Final = tuple(fold(word) for word in tables.SOLE_TRADER_NOUNS)
TITLE_STEMS: Final = tuple(sorted({fold(word) for word in tables.TITLE_WORDS}, key=len))
DOCUMENT_STEMS: Final = frozenset(fold(word) for word in tables.DOCUMENT_WORDS)
PERSON_TRIGGERS: Final = frozenset(_keyword(t) for t in tables.PERSON_TRIGGERS)
PERSON_LEADINS: Final = frozenset(_keyword(t) for t in tables.PERSON_LEADINS)
PERSON_VERBS: Final = frozenset(fold(word) for word in tables.PERSON_VERBS)
UNIT_PREFIXES: Final = frozenset(fold(word) for word in tables.UNIT_PREFIXES)
COUNTRIES: Final = tuple(sorted(tables.COUNTRIES, key=len, reverse=True))
LEGAL_FORMS_LONG: Final = tuple(
    tuple(fold(word) for word in form) for form in tables.LEGAL_FORMS_LONG
)
DEFINITION_OPENERS: Final = frozenset(_keyword(t) for t in tables.DEFINITION_OPENERS)
DEFINITION_FILLERS: Final = frozenset(fold(word) for word in tables.DEFINITION_FILLERS)
_EXACT_MARKERS: Final = frozenset({"may", "will", "should", "must", "pays", "shall"})
_FOLDED_MARKERS: Final = tuple(fold(word) for word in tables.OBLIGATION_MARKERS)
# Short markers ("не", "no", "must") match the whole word; longer ones are stems.
OBLIGATION_WORDS: Final = frozenset(
    marker
    for marker in _FOLDED_MARKERS
    if len(marker) <= 3 or marker in _EXACT_MARKERS  # noqa: PLR2004
)
OBLIGATIONS: Final = tuple(marker for marker in _FOLDED_MARKERS if marker not in OBLIGATION_WORDS)
REQUISITES_LABELS: Final = frozenset(fold(word) for word in tables.REQUISITES_LABELS)
AMOUNT_WORDS: Final = frozenset(fold(word) for word in tables.AMOUNT_WORDS)
# Units that also appear in plain addresses ("12 кв. 5"); they do not count as an amount there.
_AMBIGUOUS_UNITS: Final = frozenset(
    fold(word) for word in ("кв", "л", "k", "м2", "m2", "м3", "m3", "куб", "мм", "см", "mm", "cm")
)
STRONG_AMOUNT_WORDS: Final = AMOUNT_WORDS - _AMBIGUOUS_UNITS
ABBREVIATIONS: Final = frozenset(fold(word) for word in tables.ADDRESS_ABBREVIATIONS)
ADDRESS_STARTS: Final = frozenset(fold(word) for word in tables.ADDRESS_STARTS)
TLDS: Final = frozenset(fold(tld) for tld in tables.TLDS)
PATRONYMICS: Final = tuple(sorted({e.lower() for e in tables.PATRONYMIC_ENDINGS}, key=len))
STEM_ENDINGS: Final = tuple(
    sorted({e.replace("y", "i") for e in tables.STEM_ENDINGS}, key=len, reverse=True)
)
_CACHE: Final = 8192
_MAX_SUFFIX: Final = 4
_MAX_DOCUMENT_SUFFIX: Final = 6
_MIN_STEM: Final = 3
_MIN_PATRONYMIC_WORD: Final = 5


@lru_cache(maxsize=_CACHE)
def is_role(word: str) -> bool:
    """``word`` (folded) is a role word, also in a case form."""
    return any(
        word.startswith(stem) and len(word) - len(stem) <= _MAX_SUFFIX
        for stem in ROLE_STEMS
        if stem[0] == word[:1]
    )


@lru_cache(maxsize=_CACHE)
def is_person_role(word: str) -> bool:
    """``word`` (folded) is a role of a natural person, also in a case form."""
    return any(
        word.startswith(stem) and len(word) - len(stem) <= _MAX_SUFFIX
        for stem in PERSON_ROLE_STEMS
        if stem[0] == word[:1]
    )


@lru_cache(maxsize=_CACHE)
def is_title(word: str) -> bool:
    return any(
        word.startswith(stem) and len(word) - len(stem) <= _MAX_SUFFIX
        for stem in TITLE_STEMS
        if stem[0] == word[:1]
    )


@lru_cache(maxsize=_CACHE)
def is_document_word(word: str) -> bool:
    return any(
        word.startswith(stem) and len(word) - len(stem) <= _MAX_DOCUMENT_SUFFIX
        for stem in DOCUMENT_STEMS
        if stem[0] == word[:1]
    )


@lru_cache(maxsize=_CACHE)
def is_not_name(word: str) -> bool:
    return word in NOT_NAMES or is_role(word) or is_title(word)


@lru_cache(maxsize=_CACHE)
def is_obligation(word: str) -> bool:
    return word in OBLIGATION_WORDS or any(
        word.startswith(marker) for marker in OBLIGATIONS if marker[0] == word[:1]
    )


@lru_cache(maxsize=_CACHE)
def is_patronymic(word: str) -> bool:
    """A patronymic (any case form), Cyrillic or Latin; ``word`` is NFKC, any case."""
    lower = word.lower()
    return len(lower) >= _MIN_PATRONYMIC_WORD and any(
        lower.endswith(ending) for ending in PATRONYMICS
    )


def stem_key(word: str) -> str:
    """Key of a name word: equal for case forms and for Cyrillic and Latin spellings.

    A word with a Cyrillic letter has its Latin look-alike letters turned into Cyrillic;
    then it is transliterated, lower-cased and cut at a known case ending.
    """
    lower = word.lower().replace("’", "'")
    if lower.endswith("'s") and len(lower) > _MIN_STEM + 2:
        lower = lower[:-2]  # possessive: Smith's
    if any("Ѐ" <= char <= "ӿ" for char in lower):
        lower = "".join(chr(LATIN_TO_CYRILLIC.get(ord(c), ord(c))) for c in lower)
    latin = "".join(tables.TRANSLITERATION.get(char, char) for char in lower)
    latin = latin.replace("y", "i")
    for ending in STEM_ENDINGS:
        if latin.endswith(ending) and len(latin) - len(ending) >= _MIN_STEM:
            return latin[: -len(ending)]
    return latin


def _version() -> str:
    digest = hashlib.sha256()
    digest.update(RULES_VERSION.encode())
    digest.update(UNICODE_VERSION.encode())
    for name in sorted(vars(tables)):
        if name.isupper():
            digest.update(name.encode())
            digest.update(repr(getattr(tables, name)).encode())
    return "pseudo-" + digest.hexdigest()[:16]


DETECTOR_VERSION: Final = _version()
