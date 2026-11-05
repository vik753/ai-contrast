"""S8-T4: tagging eval in recorded mode (ADR 0018 point 9). No network, no key.

STUB NUMBERS: the only recording today is ``stub__oracle-v1`` (``stub: true``), made by a
deterministic local oracle (``eval/tagging/oracle.py``), not by a model. ``kw.*`` metrics
(keyword tags alone) and ``adversarial.*`` counts do not depend on a model and are gated.
``all.*`` metrics (keyword + model + check) are informational while the recording is a stub.

- No gated metric drops more than 0.01 below ``eval/tagging/baseline.json``; counts
  (``adversarial.*``, ``*.missing.false_positives``) may not rise, and a count below the
  baseline fails too ("tighten the baseline").
- Hidden-clause, leak, cap-violation and lost-deductible counts are 0 in every baseline.
- A recording whose template, schema, model or call inputs changed fails with a message.
"""

from __future__ import annotations

import copy
import json
from functools import cache
from typing import Any

import pytest

from eval.tagging.run_eval import (
    BASELINE_PATH,
    RECORDINGS,
    RecordingError,
    evaluate,
    improvements,
    informational,
    main,
    regressions,
)

BASELINE: dict[str, Any] = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
NAMES = sorted(BASELINE)
ZERO_COUNTS = (
    "adversarial.hidden_clauses",
    "adversarial.leaks",
    "adversarial.skip_me.hidden_clauses:recorded",
    "adversarial.skip_me.hidden_clauses:fixed",
    "adversarial.skip_me.deductible_missing:recorded",
    "adversarial.skip_me.deductible_missing:fixed",
    "adversarial.skip_me.leaks:recorded",
    "adversarial.skip_me.leaks:fixed",
    "adversarial.flood.hidden_clauses:recorded",
    "adversarial.flood.hidden_clauses:fixed",
    "adversarial.flood.deductible_missing:recorded",
    "adversarial.flood.deductible_missing:fixed",
    "adversarial.flood.cap_violations:recorded",
    "adversarial.flood.cap_violations:fixed",
    "adversarial.flood.not_dropped:fixed",
    "adversarial.flood.leaks:recorded",
    "adversarial.flood.leaks:fixed",
)


def _id(name: str) -> str:
    return f"{name}[STUB]" if BASELINE[name]["stub"] else name


@cache
def _result(name: str) -> tuple[dict[str, float], dict[str, Any]]:
    return evaluate(name)


def _recording(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((RECORDINGS / f"{name}.json").read_text(encoding="utf-8"))
    return data


def test_every_recording_has_a_baseline() -> None:
    assert sorted(p.stem for p in RECORDINGS.glob("*.json")) == NAMES


@pytest.mark.parametrize("name", NAMES, ids=_id)
def test_stub_is_labelled(name: str) -> None:
    data = _recording(name)
    assert data["stub"] is BASELINE[name]["stub"]
    if data["stub"]:
        assert data["about"].startswith("STUB")
        assert data["provider"] == "stub"


@pytest.mark.parametrize("name", NAMES, ids=_id)
def test_no_regression_against_baseline(name: str) -> None:
    metrics, _ = _result(name)
    found = regressions(metrics, BASELINE[name]["metrics"], stub=BASELINE[name]["stub"])
    assert found == [], f"{_id(name)}: " + "; ".join(found)


@pytest.mark.parametrize("name", NAMES, ids=_id)
def test_baseline_is_tight(name: str) -> None:
    metrics, _ = _result(name)
    assert improvements(metrics, BASELINE[name]["metrics"]) == []


@pytest.mark.parametrize("name", NAMES, ids=_id)
@pytest.mark.parametrize("metric", ZERO_COUNTS)
def test_adversarial_counts_are_zero(name: str, metric: str) -> None:
    assert BASELINE[name]["metrics"][metric] == 0
    metrics, _ = _result(name)
    assert metrics[metric] == 0, f"{_id(name)}: {metric} = {metrics[metric]}"


@pytest.mark.parametrize("name", NAMES, ids=_id)
def test_gated_metrics_are_present(name: str) -> None:
    metrics, _ = _result(name)
    for prefix in ("kw", "all"):
        for metric in ("recall", "precision", "other.recall", "risk.recall", "other.share"):
            assert f"{prefix}.{metric}" in metrics
        assert f"{prefix}.recall:kasko/deductible" in metrics
        assert f"{prefix}.precision:lease/deposit" in metrics
    for scope in ("en", "uk", "ru", "kasko", "osago", "property_insurance", "lease"):
        assert f"kw.precision:{scope}" in metrics


def test_model_metrics_are_informational_only_for_a_stub() -> None:
    assert informational("all.recall", stub=True)
    assert not informational("all.recall", stub=False)
    assert not informational("kw.recall", stub=True)
    assert informational("kw.other.share", stub=False)
    assert informational("kw.other.share:uk", stub=False)
    base = {"all.recall": 0.9, "kw.recall": 0.8}
    worse = {"all.recall": 0.1, "kw.recall": 0.8}
    assert regressions(worse, base, stub=True) == []
    assert regressions(worse, base, stub=False) != []


def test_counts_are_lower_is_better() -> None:
    base = {"adversarial.hidden_clauses": 0.0, "kw.missing.false_positives": 4.0}
    assert regressions({"adversarial.hidden_clauses": 1.0, "kw.missing.false_positives": 4.0}, base)
    assert improvements(
        {"adversarial.hidden_clauses": 0.0, "kw.missing.false_positives": 3.0}, base
    )


def test_changed_template_key_fails() -> None:
    name = NAMES[0]
    data = copy.deepcopy(_recording(name))
    data["keys"]["TAG_CLAUSES"] = "0" * 64
    with pytest.raises(RecordingError, match="TAG_CLAUSES"):
        evaluate(name, data)


def test_changed_input_fails() -> None:
    name = NAMES[0]
    data = copy.deepcopy(_recording(name))
    data["cases"]["kasko_en_a"]["calls"][0]["input"] = "0" * 64
    with pytest.raises(RecordingError, match="kasko_en_a"):
        evaluate(name, data)


def test_missing_or_extra_calls_fail() -> None:
    name = NAMES[0]
    fewer = copy.deepcopy(_recording(name))
    fewer["cases"]["flood"]["calls"].pop()
    with pytest.raises(RecordingError, match="more calls than recorded"):
        evaluate(name, fewer)
    more = copy.deepcopy(_recording(name))
    calls = more["cases"]["kasko_en_a"]["calls"]
    calls.append(copy.deepcopy(calls[-1]))
    with pytest.raises(RecordingError, match="fewer calls than recorded"):
        evaluate(name, more)


def test_live_mode_needs_the_key_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AIC_EVAL_PROVIDER_KEY", raising=False)
    with pytest.raises(SystemExit, match="AIC_EVAL_PROVIDER_KEY"):
        main(["--live", "--provider", "anthropic"])


def test_recordings_hold_no_key_field() -> None:
    for name in NAMES:
        text = (RECORDINGS / f"{name}.json").read_text(encoding="utf-8").casefold()
        assert "api_key" not in text
        assert "x-provider-key" not in text
