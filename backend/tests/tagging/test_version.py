"""S8-T1 AC5: tagging_version (ADR 0018 point 1)."""
# ruff: noqa: PLC0415

from __future__ import annotations

import re

import pytest

from app.tagging import keywords, risk_terms
from app.tagging.version import tagging_version


def test_tagging_version_has_a_safe_format_and_is_deterministic() -> None:
    v = tagging_version()
    assert re.fullmatch(r"[a-z0-9-]{1,64}", v)
    assert tagging_version() == v


@pytest.mark.parametrize(
    ("module", "name"),
    [
        (keywords, "KEYWORD_RULES_VERSION"),
        (risk_terms, "RISK_TERMS_VERSION"),
    ],
)
def test_tagging_version_changes_with_each_rule_version(
    monkeypatch: pytest.MonkeyPatch, module: object, name: str
) -> None:
    before = tagging_version()
    monkeypatch.setattr(module, name, "changed-" + getattr(module, name))
    assert tagging_version() != before


def test_tagging_version_changes_with_patterns_version(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.injection import patterns

    before = tagging_version()
    monkeypatch.setattr(patterns, "PATTERNS_VERSION", "changed-" + patterns.PATTERNS_VERSION)
    assert tagging_version() != before


def test_tagging_version_returns_to_original_after_patch_is_undone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = tagging_version()
    with monkeypatch.context() as m:
        m.setattr(risk_terms, "RISK_TERMS_VERSION", "x")
    assert tagging_version() == before
