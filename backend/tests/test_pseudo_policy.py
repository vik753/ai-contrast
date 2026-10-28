"""S5b-T1 AC6: pattern policy for ``app/pseudo/`` (same rules as ``app/segment/``)."""

from __future__ import annotations

import ast
import importlib
import pkgutil
import re
import sys
from pathlib import Path

import pytest

from tests.test_segment_policy import (
    FORBIDDEN_CALLS,
    _looks_like_regex_receiver,
    _string_constants,
    nested_quantifier_problem,
)

PSEUDO_DIR = Path(__file__).resolve().parents[1] / "app" / "pseudo"


def _sources() -> list[Path]:
    return sorted(PSEUDO_DIR.glob("*.py"))


def test_policy_pseudo_package_exists_with_modules() -> None:
    assert (PSEUDO_DIR / "__init__.py").is_file()
    assert len(_sources()) >= 2


def test_policy_no_nested_quantifiers_in_pseudo_source_string_constants() -> None:
    assert _sources(), "app/pseudo/ has no modules"
    problems = [
        f"{path.name}: {problem}"
        for path in _sources()
        for text in _string_constants(ast.parse(path.read_text(encoding="utf-8")))
        if (problem := nested_quantifier_problem(text))
    ]

    assert problems == []


def test_policy_no_nested_quantifiers_in_pseudo_patterns_compiled_at_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    real_compile = re._compile  # type: ignore[attr-defined]

    def recording(pattern: object, flags: int) -> object:
        if isinstance(pattern, str):
            seen.append(pattern)
        return real_compile(pattern, flags)

    monkeypatch.setattr(re, "_compile", recording)
    for name in [m for m in sys.modules if m == "app.pseudo" or m.startswith("app.pseudo.")]:
        monkeypatch.delitem(sys.modules, name)
    package = importlib.import_module("app.pseudo")
    for info in pkgutil.iter_modules(package.__path__):
        importlib.import_module(f"app.pseudo.{info.name}")

    assert seen, "no pattern compiled in app/pseudo/"
    assert [p for p in seen if nested_quantifier_problem(p)] == []


def test_policy_no_whole_text_regex_calls_in_pseudo_package() -> None:
    assert _sources(), "app/pseudo/ has no modules"
    problems: list[str] = []
    for path in _sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in FORBIDDEN_CALLS
            ):
                if node.func.attr == "split" and not _looks_like_regex_receiver(node.func.value):
                    continue
                problems.append(f"{path.name}:{node.lineno} .{node.func.attr}(")

    assert problems == []


def test_policy_no_backreferences_or_lookbehind_in_pseudo_patterns() -> None:
    assert _sources(), "app/pseudo/ has no modules"
    problems = [
        f"{path.name}: {text!r}"
        for path in _sources()
        for text in _string_constants(ast.parse(path.read_text(encoding="utf-8")))
        if re.search(r"\(\?<[=!]|\\[1-9]|\(\?P=", text) and nested_quantifier_problem(text) is None
    ]

    assert problems == []
