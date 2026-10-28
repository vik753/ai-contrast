# ruff: noqa: RUF001
"""S5b-T1 AC5: the reply at the caps (1,000,000 characters, 2,000 clauses, 5,000 entities,
50,000 spans) fits the 4 MiB result cap."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from tests.segment_helpers import block, post_blocks

MIB = 1024 * 1024
CLAUSES = 2000
ENTITIES = 5000
SPANS = 50_000
BLOCK_CHARS = 1_000_000 // 20_000


def _base36(number: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    return digits[number // 1296 % 36] + digits[number // 36 % 36] + digits[number % 36]


def _blocks() -> list[dict[str, Any]]:
    """20,000 blocks of 50 characters in 2,000 clauses; 25 identifier spans per clause."""
    blocks: list[dict[str, Any]] = []
    email = 0
    for clause in range(1, CLAUSES + 1):
        for part in range(10):
            head = f"{clause}. " if part == 0 else ""
            # Each block is 50 characters; five blocks per clause carry five emails.
            if part < 5:
                tokens = []
                for _ in range(5):
                    # 2,000 x 25 = 50,000 spans; the first 5,000 values are distinct.
                    tokens.append(f"{_base36(email % ENTITIES)}@b.co")
                    email += 1
                blocks.append(block((head + " ".join(tokens)).ljust(BLOCK_CHARS, " ")))
            else:
                body = head + "Сторони домовилися про виконання "
                blocks.append(block(body[:BLOCK_CHARS].ljust(BLOCK_CHARS, "а")))
    return blocks


def test_size_reply_at_all_caps_fits_the_result_cap(make_client: Callable[..., TestClient]) -> None:
    blocks = _blocks()
    assert len(blocks) == 20_000
    assert sum(len(b["text"]) for b in blocks) == 1_000_000

    response = post_blocks(make_client(), blocks)

    assert response.status_code == 200, response.text[:100]
    assert len(response.content) < 4 * MIB
    data = response.json()
    assert len(data["entities"]) == ENTITIES
    assert sum(len(e["spans"]) for e in data["entities"]) == SPANS
