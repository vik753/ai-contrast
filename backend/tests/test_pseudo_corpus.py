"""S5b-T1 AC8: every S5b-T0 corpus fixture gives exactly the expected result.

Loads whatever ``fixtures/pseudo/*.json`` exists (skipped when there is none).
Fixture: ``blocks`` and ``expected`` = ``entities`` (class, precision,
value_forms, spans), ``requisites``, ``neutralized``, ``warnings``,
``must_not_mask``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.pseudo_helpers import detect_blocks, span_text

CORPUS_DIR = Path(__file__).resolve().parent / "fixtures" / "pseudo"
PATHS = sorted(CORPUS_DIR.glob("*.json"))

Make = Callable[..., TestClient]


def _span(raw: Any) -> tuple[int, int, int]:
    b, s, e = raw
    return (int(b), int(s), int(e))


def _entity_key(item: dict[str, Any]) -> tuple[str, str, frozenset[tuple[int, int, int]]]:
    return (item["class"], item["precision"], frozenset(_span(s) for s in item["spans"]))


def _codes(items: list[Any]) -> list[str]:
    return sorted(i if isinstance(i, str) else i["code"] for i in items)


@pytest.mark.skipif(not PATHS, reason="S5b-T0 corpus not present yet")
@pytest.mark.parametrize("path", PATHS, ids=[p.stem for p in PATHS])
def test_corpus_fixture_gives_exactly_the_expected_result(make_client: Make, path: Path) -> None:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    expected = fixture["expected"]

    data = detect_blocks(make_client(), fixture["blocks"])

    got = sorted(map(_entity_key, data["entities"]), key=repr)
    want = sorted(map(_entity_key, expected["entities"]), key=repr)
    assert got == want

    if "warnings" in expected:
        assert _codes(expected["warnings"]) == sorted(w["code"] for w in data["warnings"]) or set(
            _codes(expected["warnings"])
        ) == {w["code"] for w in data["warnings"]}

    if "neutralized" in expected:
        assert sorted(_span(s) for s in expected["neutralized"]) == sorted(
            _span(s) for s in data["neutralized"]
        )

    if expected.get("requisites"):
        want_lines = {
            _span(line["span"]): line["action"]
            for item in expected["requisites"]
            for line in item["lines"]
        }
        got_lines = {
            _span(line["span"]): line["action"]
            for item in data["requisites"]
            for line in item["lines"]
        }
        assert got_lines == want_lines
    elif "requisites" in expected:
        assert data["requisites"] == []


@pytest.mark.skipif(not PATHS, reason="S5b-T0 corpus not present yet")
@pytest.mark.parametrize("path", PATHS, ids=[p.stem for p in PATHS])
def test_corpus_fixture_must_not_mask_values_stay_unmasked(make_client: Make, path: Path) -> None:
    fixture = json.loads(path.read_text(encoding="utf-8"))
    values = [
        v if isinstance(v, str) else v.get("value", v.get("text", ""))
        for v in fixture["expected"].get("must_not_mask", [])
    ]
    data = detect_blocks(make_client(), fixture["blocks"])
    masked = [span_text(data, sp) for e in data["entities"] for sp in e["spans"]]

    for value in filter(None, values):
        assert not any(value in m or m in value for m in masked), value


@pytest.mark.skipif(not PATHS, reason="S5b-T0 corpus not present yet")
def test_corpus_has_at_least_25_fixtures() -> None:
    assert len(PATHS) >= 25
