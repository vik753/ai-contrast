"""Helpers of the S8-T1 tests (see README.md)."""

from __future__ import annotations

import random
from collections.abc import Sequence

from app.pseudo.gate import ConfirmedTopic, confirm_topic
from app.tagging.model import TagClause
from app.topics.model import TopicDefinition


def topic(
    n: int,
    en: Sequence[str] = (),
    uk: Sequence[str] = (),
    ru: Sequence[str] = (),
) -> ConfirmedTopic:
    return confirm_topic(
        TopicDefinition(
            origin="custom",
            domain="kasko",
            topic_id=f"custom_{n}",
            title=f"Subject number {n}",
            description="",
            side="insured",
            synonyms_en=tuple(en),
            synonyms_uk=tuple(uk),
            synonyms_ru=tuple(ru),
        )
    )


def clause(n: int, text: str, heading: str | None = None) -> TagClause:
    return TagClause(id=f"c{n}", text=text, heading=heading)


def clauses(n: int, text: str = "Plain words only.") -> list[TagClause]:
    return [clause(i, text) for i in range(1, n + 1)]


_SYL = ["ba", "ko", "ru", "mi", "ta", "se", "lo", "ni", "pa", "ve"]


def pseudo_word(rng: random.Random, syllables: int = 4) -> str:
    return "".join(rng.choice(_SYL) for _ in range(syllables))
