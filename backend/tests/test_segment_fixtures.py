# ruff: noqa: PLC0415
"""S5-T1 AC8, AC3, AC2: every S5-T0 fixture gives exactly the expected clauses.

Black-box through ``POST /api/segment``. Clause boundaries are checked with
``starts_with`` on the text rebuilt from spans and the returned blocks.
Tech lead decisions on fixture ambiguities are treated as spec (see the
fixtures README).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.segment_helpers import (
    clause_text,
    contract_problems,
    cover_problems,
    fixture_paths,
    heading_text,
    load_fixture,
    post_blocks,
    warning_codes,
)

PATHS = fixture_paths()
IDS = [p.stem for p in PATHS]


@pytest.fixture(scope="module")
def replies() -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    """Run every fixture once (module cache): name -> (fixture, 200 reply)."""
    from app.main import create_app
    from app.settings import Settings

    client = TestClient(create_app(Settings()), raise_server_exceptions=False)
    out: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for path in PATHS:
        fx = load_fixture(path)
        response = post_blocks(client, fx["blocks"])
        assert response.status_code == 200, (path.name, response.text[:200])
        out[path.stem] = (fx, response.json())
    return out


def test_segment_fixture_folder_has_at_least_30_files() -> None:
    assert len(PATHS) >= 30


@pytest.mark.parametrize("name", IDS)
def test_segment_fixture_reply_follows_output_contract(
    replies: dict[str, tuple[dict[str, Any], dict[str, Any]]], name: str
) -> None:
    _, data = replies[name]

    assert contract_problems(data) == []


@pytest.mark.parametrize("name", IDS)
def test_segment_fixture_clause_count_matches(
    replies: dict[str, tuple[dict[str, Any], dict[str, Any]]], name: str
) -> None:
    fx, data = replies[name]

    assert len(data["clauses"]) == len(fx["expected"]["clauses"])


@pytest.mark.parametrize("name", IDS)
def test_segment_fixture_numbers_parts_and_section_kinds_match(
    replies: dict[str, tuple[dict[str, Any], dict[str, Any]]], name: str
) -> None:
    fx, data = replies[name]

    got = [(c["number"], c["part"], c["section_kind"]) for c in data["clauses"]]
    want = [(c["number"], c["part"], c["section_kind"]) for c in fx["expected"]["clauses"]]
    assert got == want


@pytest.mark.parametrize("name", IDS)
def test_segment_fixture_headings_match(
    replies: dict[str, tuple[dict[str, Any], dict[str, Any]]], name: str
) -> None:
    fx, data = replies[name]

    got = [heading_text(c, data["blocks"]) for c in data["clauses"]]
    want = [c["heading"] for c in fx["expected"]["clauses"]]
    assert got == want


@pytest.mark.parametrize("name", IDS)
def test_segment_fixture_clause_boundaries_match_starts_with(
    replies: dict[str, tuple[dict[str, Any], dict[str, Any]]], name: str
) -> None:
    fx, data = replies[name]

    got = [clause_text(c, data["blocks"]) for c in data["clauses"]]
    for index, (text, want) in enumerate(zip(got, fx["expected"]["clauses"], strict=True)):
        assert text.startswith(want["starts_with"]), (index, text[:60], want["starts_with"])


@pytest.mark.parametrize("name", IDS)
def test_segment_fixture_warning_codes_match(
    replies: dict[str, tuple[dict[str, Any], dict[str, Any]]], name: str
) -> None:
    fx, data = replies[name]

    assert warning_codes(data) == sorted(fx["expected"]["warnings"])


@pytest.mark.parametrize("name", IDS)
def test_segment_fixture_spans_cover_every_character_exactly_once(
    replies: dict[str, tuple[dict[str, Any], dict[str, Any]]], name: str
) -> None:
    _, data = replies[name]

    assert cover_problems(data) == []


@pytest.mark.parametrize("name", IDS)
def test_segment_fixture_clean_input_is_returned_unchanged_in_blocks(
    replies: dict[str, tuple[dict[str, Any], dict[str, Any]]], name: str
) -> None:
    fx, data = replies[name]

    assert data["blocks"] == fx["blocks"]
    assert data["removed"] == []


@pytest.mark.parametrize("name", IDS)
def test_segment_fixture_heading_stays_inside_exactly_one_clause(
    replies: dict[str, tuple[dict[str, Any], dict[str, Any]]], name: str
) -> None:
    _, data = replies[name]

    for clause in data["clauses"]:
        if clause["heading_span"] is None:
            continue
        hi, hs, he = clause["heading_span"]
        owners = [
            c["id"]
            for c in data["clauses"]
            if any(i == hi and s <= hs and he <= e for i, s, e in c["spans"])
        ]
        assert len(owners) == 1, (clause["id"], owners)


@pytest.mark.parametrize("name", IDS)
def test_segment_fixture_pages_empty_without_page_numbers(
    replies: dict[str, tuple[dict[str, Any], dict[str, Any]]], name: str
) -> None:
    fx, data = replies[name]
    if any(b["page"] is not None for b in fx["blocks"]):
        pytest.skip("paged fixture")

    assert all(c["pages"] == [] for c in data["clauses"])


@pytest.mark.parametrize("name", IDS)
def test_segment_fixture_non_body_blocks_give_one_clause_each(
    replies: dict[str, tuple[dict[str, Any], dict[str, Any]]], name: str
) -> None:
    fx, data = replies[name]
    non_body = [b for b in fx["blocks"] if b["part"] != "body"]
    if not non_body:
        pytest.skip("no non-body blocks")

    got = [c for c in data["clauses"] if c["part"] not in ("body", "preamble", "running")]
    assert len(got) == len(non_body)
    assert all(c["number"] is None and c["level"] == 0 for c in got)
    assert all(len(c["spans"]) == 1 for c in got)


def test_segment_pdf_running_fixture_lists_all_pages_of_the_running_clause(
    replies: dict[str, tuple[dict[str, Any], dict[str, Any]]],
) -> None:
    fx, data = replies["15_uk_pdf_running"]

    running = [c for c in data["clauses"] if c["part"] == "running"]
    assert running
    pages_in_file = sorted({b["page"] for b in fx["blocks"]})
    for clause in running:
        assert clause["pages"] == pages_in_file
        assert len(clause["spans"]) == len(pages_in_file)


def test_segment_no_numbering_fixture_has_no_preamble_clause(
    replies: dict[str, tuple[dict[str, Any], dict[str, Any]]],
) -> None:
    _, data = replies["18_uk_no_numbering"]

    assert all(c["part"] == "body" and c["level"] == 0 for c in data["clauses"])


def test_segment_decimal_fixture_levels_follow_depth(
    replies: dict[str, tuple[dict[str, Any], dict[str, Any]]],
) -> None:
    _, data = replies["01_uk_insurance_decimal3"]

    depth = {c["number"]: c["level"] for c in data["clauses"] if c["number"]}
    assert depth["1.1.1"] > depth["1.1"] > depth["1"] >= 1


def test_segment_numbering_warning_names_an_existing_clause(
    replies: dict[str, tuple[dict[str, Any], dict[str, Any]]],
) -> None:
    _, data = replies["19_en_numbering_gap"]

    ids = {c["id"] for c in data["clauses"]}
    assert [w["clause"] in ids for w in data["warnings"]] == [True]


def test_segment_same_request_gives_identical_reply_bytes(
    make_client: Callable[..., TestClient],
) -> None:
    fx = load_fixture(Path(PATHS[0]))
    client = make_client()

    first = post_blocks(client, fx["blocks"])
    second = post_blocks(client, fx["blocks"])

    assert first.status_code == 200
    assert first.content == second.content
