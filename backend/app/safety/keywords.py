"""Digit runs after a code keyword (ADR 0015 point 4, review of S5b-T2).

A run of three or more digits (digit groups joined by space, ``-`` or ``.``) within three
tokens after a code keyword (``ЄДРПОУ``, ``IBAN``, ``тел.``, ``№`` ...) is a value that was
not masked, unless it is an amount, a date, a percentage or a unit (the detector's amount
rule) or lies inside a placeholder. The scan returns offsets only and is linear.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Sequence
from typing import Final

from app.pseudo.lines import amount_or_date_follows
from app.pseudo.matching import fold
from app.safety.placeholders import Placeholder

KEYWORDS: Final = frozenset(
    {
        "єдрпоу", "код", "іпн", "рнокпп", "инн", "огрн", "окпо", "снилс", "iban", "рахунок",
        "счёт", "счет", "account", "tax", "паспорт", "passport", "тел", "phone", "vin", "№",
    }
)  # fmt: skip
WINDOW: Final = 3
MAX_POSITION: Final = 1 << 62
MIN_DIGITS: Final = 3
_TOKEN: Final = re.compile(r"[^\W_]+|№")
_GROUP_GAP: Final = frozenset(" -.")
_FRACTION: Final = re.compile(r",[0-9]{1,2}(?![0-9])")


def _in(position: int, ranges: Sequence[Placeholder]) -> bool:
    """``position`` is inside one of the sorted placeholder ``ranges``."""
    index = bisect_right(ranges, (position, MAX_POSITION, "")) - 1
    return index >= 0 and position < ranges[index][1]


def _group_end(text: str, tokens: list[re.Match[str]], first: int) -> tuple[int, int]:
    """End offset and last token index of the digit group that starts at token ``first``."""
    last = first
    while last + 1 < len(tokens):
        gap = text[tokens[last].end() : tokens[last + 1].start()]
        following = tokens[last + 1].group()
        if not (following.isdigit() and gap and set(gap) <= _GROUP_GAP):
            break
        last += 1
    return tokens[last].end(), last


def keyword_digit_spans(
    texts: Sequence[str], placeholders: Sequence[Sequence[Placeholder]]
) -> set[tuple[int, int, int]]:
    """Unmasked digit runs as ``(clause_index, start, end)``."""
    result: set[tuple[int, int, int]] = set()
    for index, (text, found) in enumerate(zip(texts, placeholders, strict=True)):
        tokens = list(_TOKEN.finditer(text))
        folded = fold(text)
        for number, token in enumerate(tokens):
            if token.group().lower() not in KEYWORDS or _in(token.start(), found):
                continue
            for look in range(number + 1, min(number + 1 + WINDOW, len(tokens))):
                candidate = tokens[look]
                if _in(candidate.start(), found) or not candidate.group().isdigit():
                    continue
                end, _ = _group_end(text, tokens, look)
                start = candidate.start()
                digits = sum(char.isdigit() for char in text[start:end])
                fraction = _FRACTION.match(text, end)
                after = fraction.end() if fraction else end
                if digits >= MIN_DIGITS and not amount_or_date_follows(
                    folded, start, after, len(text)
                ):
                    result.add((index, start, end))
                break
    return result
