# ruff: noqa: RUF001
"""S5-T1 AC3: cover property on random inputs (seeded generator).

``hypothesis`` is not a dev dependency (checked in ``uv.lock``), so a seeded
``random.Random`` builds the inputs. For every input the spans of all clauses
cover every non-white-space character of the returned (cleaned) blocks exactly
once, in order; the reply follows the output contract; the result is
deterministic.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.segment_helpers import block, contract_problems, cover_problems, post_blocks

LINES = [
    "1. Предмет договору",
    "1.1. Виконавець зобов'язується надати послуги.",
    "1.2.3 Деталі виконання.",
    "2) Оплата здійснюється протягом 30 днів.",
    "Стаття 5. Відповідальність",
    "Статья 6. Ответственность сторон",
    "Article 7. Term",
    "Section 8. Fees",
    "§ 9 Notices",
    "IV. Final provisions",
    "а) перший пункт;",
    "(a) first item;",
    "(i) nested item;",
    "ВІДПОВІДАЛЬНІСТЬ СТОРІН",
    "PAYMENT TERMS",
    "Реквізити та підписи сторін",
    "Signatures",
    "Підписи сторін.",
    "Ordinary sentence without numbering. It goes on.",
    "Звичайне речення без нумерації.",
    "x",
    "  ",
    "",
    "\t",
    "Confidential draft.",
    "Page footer line.",
    "5. Repeated clause start line.",
    "1. 1. 1. 1.",
    "....",
    "1.1.1.1.1.1.1.1",
    "A" * 130,
    "Line with zero\u200bwidth and\x01control.",
    "Mixed ТЕКСТ and Text with 3.14 numbers 1) inline 2.",
]
PARTS = ["body"] * 8 + ["footnote", "endnote", "header", "footer", "textbox"]


def _random_blocks(rng: random.Random) -> list[dict[str, Any]]:
    paged = rng.random() < 0.5
    pages = rng.randint(1, 6)
    out: list[dict[str, Any]] = []
    for page in range(1, (pages if paged else 1) + 1):
        for _ in range(rng.randint(1, 14)):
            text = rng.choice(LINES)
            if rng.random() < 0.15:
                text = f"{text}\n{rng.choice(LINES)}"
            out.append(block(text, rng.choice(PARTS), page if paged else None))
        if paged and rng.random() < 0.7:
            out.insert(len(out) - rng.randint(0, 1), block("Confidential draft.", "body", page))
            out.append(block("Page footer line.", "body", page))
    if not any(b["text"].strip() and any(not c.isspace() for c in b["text"]) for b in out):
        out.append(block("1. Fallback text."))
    return out


SEEDS = list(range(40))


@pytest.mark.parametrize("seed", SEEDS)
def test_segment_random_input_cover_and_contract(
    make_client: Callable[..., TestClient], seed: int
) -> None:
    blocks = _random_blocks(random.Random(seed))  # noqa: S311

    response = post_blocks(make_client(max_pdf_pages=10), blocks)

    assert response.status_code == 200, response.text[:200]
    data = response.json()
    assert contract_problems(data) == []
    assert cover_problems(data) == []


@pytest.mark.parametrize("seed", SEEDS[:5])
def test_segment_random_input_is_deterministic(
    make_client: Callable[..., TestClient], seed: int
) -> None:
    blocks = _random_blocks(random.Random(seed))  # noqa: S311
    client = make_client(max_pdf_pages=10)

    first = post_blocks(client, blocks)
    second = post_blocks(client, blocks)

    assert first.status_code == 200
    assert first.content == second.content


@pytest.mark.parametrize("seed", SEEDS[:10])
def test_segment_random_input_blocks_keep_part_and_page_of_the_input(
    make_client: Callable[..., TestClient], seed: int
) -> None:
    blocks = _random_blocks(random.Random(seed))  # noqa: S311

    data = post_blocks(make_client(max_pdf_pages=10), blocks).json()

    assert [(b["part"], b["page"]) for b in data["blocks"]] == [
        (b["part"], b["page"]) for b in blocks
    ]
