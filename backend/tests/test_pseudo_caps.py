# ruff: noqa: RUF001
"""S5b-T1 AC5, AC6: caps checked during detection, linear time at the caps (T5, T6)."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.segment_helpers import block, post_blocks

Make = Callable[..., TestClient]
CPU_LIMIT_SECONDS = 20
MAX_ENTITIES = 5_000
MAX_SPANS = 50_000
FAIL_CLOSED = {"too_many_identifiers", "too_many_clauses", "clause_too_long"}


def _chunks(items: list[str], per: int = 40) -> list[dict[str, Any]]:
    """One numbered clause per ``per`` items (a clause has a size limit)."""
    return [
        block(f"{k + 1}. " + " ".join(items[i : i + per]))
        for k, i in enumerate(range(0, len(items), per))
    ]


def _emails(n: int) -> list[dict[str, Any]]:
    return _chunks([f"u{i}@example.com" for i in range(n)])


def test_caps_exactly_5000_entities_is_accepted(make_client: Make) -> None:
    response = post_blocks(make_client(), _emails(MAX_ENTITIES))

    assert response.status_code == 200, response.text[:100]
    assert len(response.json()["entities"]) == MAX_ENTITIES


def test_caps_5001_entities_returns_422_too_many_identifiers(make_client: Make) -> None:
    response = post_blocks(make_client(), _emails(MAX_ENTITIES + 1))

    assert response.status_code == 422
    assert response.json() == {"error": "too_many_identifiers"}


def test_caps_exactly_50000_spans_is_accepted(make_client: Make) -> None:
    response = post_blocks(make_client(), _chunks(["a@example.com"] * MAX_SPANS))

    assert response.status_code == 200, response.text[:100]
    assert sum(len(e["spans"]) for e in response.json()["entities"]) == MAX_SPANS


def test_caps_50001_spans_in_one_entity_returns_422_too_many_identifiers(make_client: Make) -> None:
    response = post_blocks(make_client(), _chunks(["a@example.com"] * (MAX_SPANS + 1)))

    assert response.status_code == 422
    assert response.json() == {"error": "too_many_identifiers"}


def test_caps_are_checked_during_detection_far_above_the_cap_fails_fast(make_client: Make) -> None:
    blocks = _chunks([f"u{i}@example.com" for i in range(40_000)])  # about 1 M characters
    start = time.monotonic()

    response = post_blocks(make_client(), blocks)

    assert response.status_code == 422
    assert response.json()["error"] in FAIL_CLOSED
    assert time.monotonic() - start < CPU_LIMIT_SECONDS


def test_caps_result_at_the_entity_cap_stays_inside_the_result_size_limit(
    make_client: Make,
) -> None:
    blocks = [block(f"{i}. u{i}@example.com paid.") for i in range(MAX_ENTITIES)]

    response = post_blocks(make_client(), blocks)

    assert response.status_code in (200, 422)
    if response.status_code == 422:
        assert response.json()["error"] in FAIL_CLOSED | {"too_many_clauses", "result_too_large"}
    else:
        assert len(response.content) <= 4 * 1024 * 1024


# ------------------------------------------------------------- linear time

ADVERSARIAL: dict[str, str] = {
    "at-signs": "a@" * 500_000,
    "dotted-labels": "a." * 500_000,
    "digits-run": "1" * 1_000_000,
    "digits-spaces": "1 " * 500_000,
    "iban-prefix": "UA" * 500_000,
    "legal-form-quotes": "ТОВ «" * 200_000,
    "open-guillemets": "«" * 1_000_000,
    "context-keywords": "ЄДРПОУ " * 140_000,
    "at-paren": "(at)" * 250_000,
    "letters-dashes": "ab-" * 330_000,
    "address-keyword": "Адреса: " * 120_000,
    "represented-by": "в особі " * 120_000,
    "slashes-underscores": "_ /" * 330_000,
    "initials": "А.Б. " * 200_000,
    "www-dots": "www." * 250_000,
    "hyphen-newlines": "ab-\n" * 250_000,
    "ligatures": "ﬁ" * 500_000,
    "fullwidth-digits": "１" * 500_000,
}


@pytest.mark.parametrize("name", sorted(ADVERSARIAL))
def test_linear_time_adversarial_input_at_cap_finishes_within_cpu_limit(
    make_client: Make, name: str
) -> None:
    start = time.monotonic()

    response = post_blocks(make_client(), [block(ADVERSARIAL[name][:1_000_000])])

    assert time.monotonic() - start < CPU_LIMIT_SECONDS + 5
    if response.status_code != 200:
        assert response.status_code == 422, (response.status_code, response.text[:100])
        assert response.json()["error"] in FAIL_CLOSED, response.json()
    else:
        data: dict[str, Any] = response.json()
        assert len(data["entities"]) <= MAX_ENTITIES


def test_linear_time_many_lines_of_context_and_digits_finish(make_client: Make) -> None:
    text = "\n".join(["Код ЄДРПОУ 3200012 12345678 абв"] * 30_000)
    start = time.monotonic()

    response = post_blocks(make_client(), [block(text[:1_000_000])])

    assert time.monotonic() - start < CPU_LIMIT_SECONDS + 5
    assert response.status_code in (200, 422)
    if response.status_code == 422:
        assert response.json()["error"] in FAIL_CLOSED
