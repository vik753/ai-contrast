"""S8-T1: pattern policy for app/tagging/ (linear time, no regex built from synonyms)."""

from __future__ import annotations

import importlib
import pkgutil
import re
import sys

import pytest

from tests.test_segment_policy import nested_quantifier_problem


def test_policy_no_nested_quantifiers_in_tagging_patterns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    real_compile = re._compile  # type: ignore[attr-defined]

    def recording(pattern: object, flags: int) -> object:
        if isinstance(pattern, str):
            seen.append(pattern)
        return real_compile(pattern, flags)

    monkeypatch.setattr(re, "_compile", recording)
    for name in [m for m in sys.modules if m == "app.tagging" or m.startswith("app.tagging.")]:
        monkeypatch.delitem(sys.modules, name)
    package = importlib.import_module("app.tagging")
    for info in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"app.tagging.{info.name}")
    from app.tagging.risk_terms import scan_risk  # noqa: PLC0415

    scan_risk("penalty of 5%")
    assert seen, "no pattern compiled in app/tagging/"
    assert [p for p in seen if nested_quantifier_problem(p)] == []


def test_policy_tagging_never_compiles_a_pattern_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tagging.keywords import keyword_tags  # noqa: PLC0415

    from .helpers import clause, topic  # noqa: PLC0415

    seen: list[str] = []
    real_compile = re._compile  # type: ignore[attr-defined]

    def recording(pattern: object, flags: int) -> object:
        if isinstance(pattern, str):
            seen.append(pattern)
        return real_compile(pattern, flags)

    monkeypatch.setattr(re, "_compile", recording)
    before = len(seen)
    keyword_tags([clause(1, "a (b* c+")], [topic(1, en=["taxes.ides", "road side"])])
    assert len(seen) == before
