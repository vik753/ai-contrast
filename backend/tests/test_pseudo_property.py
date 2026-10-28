# ruff: noqa: RUF001, S311, E501
"""S5b-T1: seeded random inputs through the detector. For every input the detector does not
fail, every span lies inside its block, entity spans do not overlap (except the sanctioned
signature/sole-trader nesting), the reply is deterministic, and look-alikes are neutralized."""

from __future__ import annotations

import itertools
import random

import pytest

from app.pseudo.detector import TooManyIdentifiersError, detect
from app.segment.model import Clause

PIECES = [
    "Іваненко І.І.", "Петренка Ігоря Миколайовича", "ТОВ «Альфа»", "«Омега»", "ФОП Савченко В.А.",
    "ivan@example.com", "info(at)example.org", "+380 44 123 45 67", "(044) 555-01-23",
    "https://www.example.com/x", "example.com.ua", "ЄДРПОУ 21045679", "21045679", "3012345670",
    "IBAN UA863204782600123456789012345", "4111 1111 1111 1111", "№ 45/2024", "Договір № АВ 7654321",
    "Адреса: м. Одеса, вул. Тестова, 12.", "____ /Петренко О.М./", "[ORG_2]", "［A.PERSON_1］",
    "5 000 грн", "25 %", "30 днів", "Страховик", "Buyer", "Northwind Ltd.", "в особі директора",
    "(далі — «Альфа»)", "Іва-\nненко", "ﬁ№㎜", "\u200b", "—", "1.", "2.1.", "Реквізити та підписи сторін",
    "Тел.:", "VIN WVWZZZ3CZ9E123456", "АА 1234 ВК", "Паспорт серія АА № 123456", "діагноз цукровий діабет",
    "И.И. Иванов", "J. Testman", "Rose", "rose", "a@", "((", "«", "_", "/", ".", ",", " ", "\n",
]  # fmt: skip


def _text(rng: random.Random) -> str:
    return "".join(rng.choice(PIECES) + rng.choice([" ", "\n", ", ", ""]) for _ in range(40))


def _clauses() -> list[Clause]:
    return []


@pytest.mark.parametrize("seed", range(60))
def test_property_detector_output_is_valid_and_deterministic(seed: int) -> None:
    rng = random.Random(seed)
    texts = [_text(rng) for _ in range(rng.randint(1, 4))]

    try:
        first = detect(texts, _clauses())
        second = detect(texts, _clauses())
    except TooManyIdentifiersError:
        return

    assert [(e.cls, e.precision, e.spans) for e in first.entities] == [
        (e.cls, e.precision, e.spans) for e in second.entities
    ]
    assert first.texts == second.texts
    assert [len(t) for t in first.texts] == [len(t) for t in texts]
    for entity in first.entities:
        assert entity.spans
        for block, start, end in entity.spans:
            assert 0 <= start < end <= len(texts[block])
    flat = sorted(
        (block, start, end)
        for entity in first.entities
        if entity.cls not in ("SIGNATURE", "PERSON", "ORG")
        for block, start, end in entity.spans
    )
    for (b1, _, e1), (b2, s2, _) in itertools.pairwise(flat):
        assert b1 != b2 or e1 <= s2
    for text in first.texts:
        assert "[ORG_2]" not in text
