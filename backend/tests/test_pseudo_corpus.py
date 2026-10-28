"""S5b-T1 AC8: every S5b-T0 corpus fixture gives exactly the expected result.

Format (see ``fixtures/pseudo/README.md``): ``blocks`` and ``expected`` =
``entities`` [{class, precision, value_forms, spans}], ``requisites``
[{block, line_text_starts_with, action}], ``neutralized`` spans, ``warnings``
codes, ``must_not_mask`` strings. Entities are compared as sets.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.pseudo_helpers import detect_blocks

CORPUS_DIR = Path(__file__).resolve().parent / "fixtures" / "pseudo"
PATHS = sorted(CORPUS_DIR.glob("[0-9][0-9]_*.json"))
IDS = [p.stem for p in PATHS]

Make = Callable[..., TestClient]
Span = tuple[int, int, int]

pytestmark = pytest.mark.skipif(not PATHS, reason="S5b-T0 corpus not present")


def _load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _spans(raw: list[list[int]]) -> tuple[Span, ...]:
    return tuple(sorted((int(b), int(s), int(e)) for b, s, e in raw))


def _entity_set(entities: list[dict[str, Any]]) -> set[tuple[str, str, tuple[Span, ...]]]:
    return {(e["class"], e["precision"], _spans(e["spans"])) for e in entities}


def test_corpus_has_at_least_25_fixtures() -> None:
    assert len(PATHS) >= 25


@pytest.mark.parametrize("path", PATHS, ids=IDS)
def test_corpus_fixture_spans_are_value_forms_in_the_input(path: Path) -> None:
    fixture = _load(path)
    for entity in fixture["expected"]["entities"]:
        for b, s, e in entity["spans"]:
            assert fixture["blocks"][b]["text"][s:e] in entity["value_forms"], (entity, b, s, e)


@pytest.mark.parametrize("path", PATHS, ids=IDS)
def test_corpus_entities_match_class_precision_spans_and_grouping(
    make_client: Make, path: Path
) -> None:
    fixture = _load(path)

    data = detect_blocks(make_client(), fixture["blocks"])

    got = _entity_set(data.get("entities", []))
    want = _entity_set(fixture["expected"]["entities"])
    assert got == want, {"missing": sorted(want - got), "unexpected": sorted(got - want)}


@pytest.mark.parametrize("path", PATHS, ids=IDS)
def test_corpus_requisites_decisions_match(make_client: Make, path: Path) -> None:
    fixture = _load(path)
    expected = fixture["expected"].get("requisites", [])
    data = detect_blocks(make_client(), fixture["blocks"])

    lines = [
        (
            line["span"][0],
            data["blocks"][line["span"][0]]["text"][line["span"][1] : line["span"][2]].strip(),
            line["action"],
        )
        for item in data.get("requisites", [])
        for line in item["lines"]
    ]
    for record in expected:
        found = [
            action
            for b, text, action in lines
            if b == record["block"] and text.startswith(record["line_text_starts_with"])
        ]
        assert found == [record["action"]], record
    assert len(lines) == len(expected)


@pytest.mark.parametrize("path", PATHS, ids=IDS)
def test_corpus_neutralized_spans_match(make_client: Make, path: Path) -> None:
    fixture = _load(path)
    data = detect_blocks(make_client(), fixture["blocks"])

    got = {_spans([s])[0] for s in data.get("neutralized", [])}
    want = {_spans([s])[0] for s in fixture["expected"].get("neutralized", [])}
    assert got == want


@pytest.mark.parametrize("path", PATHS, ids=IDS)
def test_corpus_warning_codes_match(make_client: Make, path: Path) -> None:
    fixture = _load(path)
    data = detect_blocks(make_client(), fixture["blocks"])

    detector_codes = {"requisites_condition", "placeholder_lookalike", "masked_next_to_amount"}
    got = {w["code"] for w in data["warnings"]} & detector_codes
    assert got == set(fixture["expected"].get("warnings", []))


@pytest.mark.parametrize("path", PATHS, ids=IDS)
def test_corpus_must_not_mask_strings_are_outside_every_entity_span(
    make_client: Make, path: Path
) -> None:
    fixture = _load(path)
    data = detect_blocks(make_client(), fixture["blocks"])
    spans = [tuple(sp) for e in data.get("entities", []) for sp in e["spans"]]

    for value in fixture["expected"].get("must_not_mask", []):
        for b, block in enumerate(data["blocks"]):
            start = block["text"].find(value)
            while start != -1:
                end = start + len(value)
                assert not any(sb == b and ss < end and start < se for sb, ss, se in spans), (
                    value,
                    b,
                    start,
                )
                start = block["text"].find(value, start + 1)
