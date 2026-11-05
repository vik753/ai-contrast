"""Risk terms (ADR 0018 point 4): a checked-in EN/UK/RU stem list.

Entries are word stems on the skeleton view. ``word$`` matches the whole word only.
The scan is a hint for ordering "Other" clauses; it never rates anything.
"""

from __future__ import annotations

import hashlib
from typing import Final

from app.tagging.phrases import PhraseIndex, view_with_source

__all__ = ["RISK_TERMS", "RISK_TERMS_VERSION", "scan_risk"]

RISK_TERMS: Final[tuple[str, ...]] = (
    # English
    "penalt",
    "fine$",
    "fines$",
    "fined$",
    "forfeit",
    "exclusion",
    "exclude",
    "excluded",
    "excluding",
    "not$ covered",
    "not$ cover$",
    "waive",
    "waiver",
    "unilateral",
    "terminat",
    "indemn",
    "liquidated damages",
    "sole$ discretion",
    "at$ its$ discretion",
    # Ukrainian
    "штраф",
    "пеня$",
    "пені$",
    "пеню$",
    "пенею$",
    "пенями$",
    "пень$",
    "неустойк",
    "не$ відшкодов",
    "не$ покрива",
    "не$ підляга відшкодуван",
    "без$ відшкодуван",
    "виключен",
    "в$ односторонн",
    "відмов",
    "розірва",
    # Russian
    "пени$",
    "пеней$",
    "пеням$",
    "пенях$",
    "не$ возмеща",
    "не$ возмести",
    "не$ покрыва",
    "не$ подлежит возмещен",
    "без$ возмещен",
    "исключен",
    "в$ одностороннем",
    "отказ",
    "расторж",
)

RISK_TERMS_VERSION: Final = (
    "risk-" + hashlib.sha256("\n".join(RISK_TERMS).encode()).hexdigest()[:12] + "-1"
)

_INDEX: Final = PhraseIndex(((term, term) for term in RISK_TERMS), exact_marker=True)


def scan_risk(text: str) -> list[tuple[int, int]]:
    """``[start, end)`` offsets into ``text`` of every hit, sorted; each starts at a word."""
    if not text:
        return []
    view, source = view_with_source(text)
    spans: set[tuple[int, int]] = set()
    for _, start, end in _INDEX.find(view):
        if source is None:
            spans.add((start, end))
        else:
            spans.add((source[start], source[end - 1] + 1))
    return sorted(spans)
