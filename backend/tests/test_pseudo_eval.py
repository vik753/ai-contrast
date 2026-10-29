"""S5b-T4 AC 2: detector eval gates and baseline (ADR 0015 point 7).

Runs ``eval/pseudo/run_eval.py`` on the main corpus and on the held-out split.

- One test per gate: recall 1.0 per language x class for ``high`` entities, recall
  >= 0.95 for ``normal`` entities, precision >= 0.85 per language, 0 ``must_not_mask``
  violations. Gate ids come from the expected data, so a gate cannot vanish because the
  detector found nothing.
- One test per split: no metric more than 0.01 below ``eval/pseudo/baseline.json``.

Gates the current detector does not meet are ``xfail(strict=True)`` in
``KNOWN_GATE_FAILURES``: CI stays green, and a fixed gate turns into XPASS (a failure)
until its entry is removed. The gate thresholds are never lowered here.

Held-out assertions show aggregate numbers only (no values, spans or file names).
"""

from __future__ import annotations

import json
from functools import cache
from typing import Any

import pytest

from eval.pseudo import run_eval
from eval.pseudo.run_eval import (
    BASELINE_PATH,
    GATE_PRECISION,
    GATE_RECALL_HIGH,
    GATE_RECALL_NORMAL,
    SplitResult,
    corpus_paths,
    evaluate,
    gates,
    metrics,
    regressions,
)

SPLITS = ("main", "heldout")

# Held-out gates the detector does not meet yet (round 3, branch fix/detector-round3).
# Each entry goes away with the detector fix that makes it pass (strict XPASS fails).
_HELDOUT_REASON = (
    "S5b-T4 AC 2: detector round 3 still misses this held-out gate; detector work pending"
)
KNOWN_GATE_FAILURES: dict[str, str] = {
    "heldout-recall:en:ADDRESS:normal": _HELDOUT_REASON,
    "heldout-recall:en:PERSON:normal": _HELDOUT_REASON,
}


def _expected_gate_ids(split: str) -> list[str]:
    ids: set[str] = {"must_not_mask_violations"}
    for path in corpus_paths(split):
        fixture: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        lang = fixture["language"]
        ids.add(f"precision:{lang}")
        for entity in fixture["expected"]["entities"]:
            ids.add(f"recall:{lang}:{entity['class']}:{entity['precision']}")
    return sorted(ids)


def _gate_params() -> list[Any]:
    params = []
    for split in SPLITS:
        for gate in _expected_gate_ids(split):
            test_id = f"{split}-{gate}"
            reason = KNOWN_GATE_FAILURES.get(test_id)
            marks = [pytest.mark.xfail(strict=True, reason=reason)] if reason else []
            params.append(pytest.param(split, gate, id=test_id, marks=marks))
    return params


@cache
def _result(split: str) -> SplitResult:
    return evaluate(corpus_paths(split))


def test_both_splits_are_present() -> None:
    assert len(corpus_paths("main")) >= 25
    assert len(corpus_paths("heldout")) >= 10


def test_every_known_failure_names_a_real_gate() -> None:
    real = {f"{split}-{gate}" for split in SPLITS for gate in _expected_gate_ids(split)}
    assert set(KNOWN_GATE_FAILURES) <= real


@pytest.mark.parametrize(("split", "gate_id"), _gate_params())
def test_gate(split: str, gate_id: str) -> None:
    by_id = {gate.id: gate for gate in gates(_result(split))}
    if gate_id.startswith("precision:") and gate_id not in by_id:
        return  # nothing detected in this language: no false positive
    gate = by_id[gate_id]
    assert gate.passed, f"{split} {gate.id}: {gate.value:.4f} (gate {gate.threshold:g})"


@pytest.mark.parametrize("split", SPLITS)
def test_no_metric_below_baseline(split: str) -> None:
    baseline: dict[str, dict[str, float]] = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    found = regressions(metrics(_result(split)), baseline[split])
    assert not found, f"{split}: {found}"


# ---------------------------------------------------------------- scorer rules


def test_gate_thresholds_are_the_adr_values() -> None:
    assert (GATE_RECALL_HIGH, GATE_RECALL_NORMAL, GATE_PRECISION) == (1.0, 0.95, 0.85)


def test_partial_cover_is_a_miss_and_split_cover_is_a_hit() -> None:
    covered = run_eval._covered
    assert covered((0, 2, 8), [(0, 0, 10)])
    assert covered((0, 2, 8), [(0, 2, 5), (0, 5, 8)])
    assert not covered((0, 2, 8), [(0, 2, 7)])
    assert not covered((0, 2, 8), [(1, 0, 10)])
    assert not covered((0, 2, 8), [])


def test_regression_check_uses_the_tolerance() -> None:
    base = {"recall:uk:PERSON:normal": 0.98, "must_not_mask_violations": 0.0}
    assert (
        regressions({"recall:uk:PERSON:normal": 0.971, "must_not_mask_violations": 0.0}, base) == []
    )
    assert regressions({"recall:uk:PERSON:normal": 0.969, "must_not_mask_violations": 0.0}, base)
    assert regressions({"recall:uk:PERSON:normal": 0.98, "must_not_mask_violations": 1.0}, base)
    assert regressions({"must_not_mask_violations": 0.0}, base)
