# ruff: noqa: RUF001, PT018
"""S5-T1 AC6, AC10: linear time at the caps (T5, T6).

Adversarial inputs of the maximum size must finish inside the child's CPU
limit (default 20 s). A request that ends in ``segment_timeout`` or
``segment_failed`` fails the test. Where the spec allows a fail-closed cap
error (``too_many_clauses``, ``clause_too_long``) the test accepts it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.segment_helpers import block, cover_problems, post_blocks

CAP_CHARS = 1_000_000
CPU_LIMIT_SECONDS = 20
FAIL_CLOSED = {"too_many_clauses", "clause_too_long"}


def _run(
    client: TestClient, blocks: list[dict[str, Any]], *, allow: set[str] | None = None
) -> dict[str, Any] | None:
    start = time.monotonic()
    response = post_blocks(client, blocks)
    elapsed = time.monotonic() - start
    assert elapsed < CPU_LIMIT_SECONDS + 5, f"took {elapsed:.1f} s"
    if response.status_code == 200:
        data: dict[str, Any] = response.json()
        assert cover_problems(data) == []
        return data
    assert response.status_code == 422, (response.status_code, response.text[:100])
    assert allow and response.json()["error"] in allow, response.json()
    return None


def _total(blocks: list[dict[str, Any]]) -> int:
    return sum(len(b["text"]) for b in blocks)


def test_segment_one_line_of_digits_and_dots_at_cap_finishes(
    make_client: Callable[..., TestClient],
) -> None:
    text = ("1." * (CAP_CHARS // 2))[:CAP_CHARS]

    _run(make_client(), [block(text)], allow=FAIL_CLOSED)


def test_segment_one_line_of_nested_numbers_at_cap_finishes(
    make_client: Callable[..., TestClient],
) -> None:
    text = ("1.1.1.1." * (CAP_CHARS // 8))[:CAP_CHARS]

    _run(make_client(), [block(text)], allow=FAIL_CLOSED)


def test_segment_digits_and_dots_in_many_lines_at_cap_finishes(
    make_client: Callable[..., TestClient],
) -> None:
    text = "\n".join(["1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1.1"] * 18_000)

    _run(make_client(), [block(text[:CAP_CHARS])], allow=FAIL_CLOSED)


def test_segment_thousands_of_lettered_items_in_one_block_finish(
    make_client: Callable[..., TestClient],
) -> None:
    text = "1. Parent clause\n" + "а) пункт\n" * 100_000

    data = _run(make_client(), [block(text[:CAP_CHARS])])

    assert data is not None
    assert {c["number"] for c in data["clauses"]} == {"1"}


def test_segment_thousands_of_lettered_items_in_many_blocks_finish(
    make_client: Callable[..., TestClient],
) -> None:
    blocks = [block("1. Parent clause")] + [
        block(f"{chr(0x430 + n % 20)}) item") for n in range(19_999)
    ]

    data = _run(make_client(), blocks)

    assert data is not None
    assert {c["number"] for c in data["clauses"]} == {"1"}


def test_segment_long_all_caps_lines_finish(make_client: Callable[..., TestClient]) -> None:
    blocks = [block(("ABCDEF GHIJ " * 420)[:5000]) for _ in range(200)]

    data = _run(make_client(), blocks)

    assert data is not None
    assert _total(blocks) == 1_000_000
    assert len(data["clauses"]) == 200


def test_segment_one_all_caps_line_at_cap_finishes(
    make_client: Callable[..., TestClient],
) -> None:
    text = ("ЗАКРИТТЯ ДОГОВОРУ " * 60_000)[:CAP_CHARS]

    _run(make_client(), [block(text)], allow=FAIL_CLOSED)


def test_segment_20000_tiny_blocks_finish(make_client: Callable[..., TestClient]) -> None:
    blocks = [block("x") for _ in range(20_000)]

    _run(make_client(), blocks, allow=FAIL_CLOSED)


def test_segment_20000_tiny_blocks_under_one_clause_finish(
    make_client: Callable[..., TestClient],
) -> None:
    blocks = [block("1. Start")] + [block("x.") for _ in range(19_999)]

    data = _run(make_client(), blocks)

    assert data is not None
    assert {c["number"] for c in data["clauses"]} == {"1"}


def test_segment_20000_tiny_numbered_blocks_fail_closed_or_finish(
    make_client: Callable[..., TestClient],
) -> None:
    blocks = [block(f"{n}.") for n in range(1, 20_001)]

    _run(make_client(), blocks, allow={"too_many_clauses"})


@pytest.mark.parametrize("repeat", ["a ", "а) ", "(i) ", "I. ", "§ "])
def test_segment_repeated_short_tokens_in_one_line_at_cap_finish(
    make_client: Callable[..., TestClient], repeat: str
) -> None:
    text = (repeat * (CAP_CHARS // len(repeat) + 1))[:CAP_CHARS]

    _run(make_client(), [block(text)], allow=FAIL_CLOSED)


def test_segment_100_pages_20000_blocks_with_running_lines_finish(
    make_client: Callable[..., TestClient],
) -> None:
    blocks: list[dict[str, Any]] = []
    for page in range(1, 101):
        blocks.append(block("Confidential draft.", page=page))
        blocks.extend(block(f"Line {page}-{n} of the page text.", page=page) for n in range(198))
        blocks.append(block("Page footer line.", page=page))
    blocks[1] = block("1. Opening clause.", page=1)
    assert len(blocks) == 20_000

    data = _run(make_client(max_pdf_pages=100), blocks)

    assert data is not None
    running = [c for c in data["clauses"] if c["part"] == "running"]
    assert sorted(len(c["pages"]) for c in running) == [100, 100]


def test_segment_100_pages_with_unique_lines_have_no_running_clause(
    make_client: Callable[..., TestClient],
) -> None:
    blocks: list[dict[str, Any]] = []
    for page in range(1, 101):
        blocks.extend(block(f"Unique line {page}-{n}.", page=page) for n in range(200))
    blocks[0] = block("1. Start of the contract.", page=1)

    data = _run(make_client(max_pdf_pages=100), blocks)

    assert data is not None
    assert [c for c in data["clauses"] if c["part"] == "running"] == []
