# ruff: noqa: B007
"""S5-T1 AC6, AC10: pattern policy for ``app/segment/`` (ADR 0009, ADR 0014 point 3).

Patterns must be linear-time: no nested quantifiers, and patterns are applied
per line with ``match``/``fullmatch``, never ``search``/``findall``/``finditer``/
``sub``/``split`` over text. The detector is checked on known good and bad
patterns first, then applied to every pattern found in the package: string
constants in the source and patterns passed to ``re`` at import time.
"""

from __future__ import annotations

import ast
import importlib
import re
import sys
import warnings
from pathlib import Path

import pytest

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import re._constants as _c
    import re._parser as _p

SEGMENT_DIR = Path(__file__).resolve().parents[1] / "app" / "segment"
FORBIDDEN_CALLS = {"search", "findall", "finditer", "sub", "subn", "split"}
REPEATS = (_c.MAX_REPEAT, _c.MIN_REPEAT, getattr(_c, "POSSESSIVE_REPEAT", _c.MAX_REPEAT))


def _repeats(parsed: object) -> list[tuple[int, int, object]]:
    """All repeats in a parsed pattern as (min, max, body); recursive."""
    found: list[tuple[int, int, object]] = []

    def walk(items: object) -> None:
        for op, arg in items:  # type: ignore[attr-defined]
            if op in REPEATS:
                lo, hi, body = arg
                found.append((lo, hi, body))
                walk(body)
            elif op is _c.SUBPATTERN:
                walk(arg[-1])
            elif op is _c.BRANCH:
                for branch in arg[1]:
                    walk(branch)
            elif op in (_c.ASSERT, _c.ASSERT_NOT):
                walk(arg[1])
            elif op is _c.ATOMIC_GROUP:
                walk(arg)
            elif op is _c.GROUPREF_EXISTS:
                for part in arg[1:]:
                    if part is not None:
                        walk(part)

    walk(parsed)
    return found


def nested_quantifier_problem(pattern: str) -> str | None:
    try:
        parsed = _p.parse(pattern)
    except (re.error, RecursionError, OverflowError):
        return None
    for lo, hi, body in _repeats(parsed):
        inner = _repeats(body)
        if not inner:
            continue
        outer_unbounded = hi == _c.MAXREPEAT
        for ilo, ihi, _ in inner:
            inner_unbounded = ihi == _c.MAXREPEAT
            if outer_unbounded or inner_unbounded:
                return f"nested quantifier in {pattern!r}"
            if hi > 1 and ihi > 1 and hi * ihi > 100:
                return f"large bounded nesting in {pattern!r}"
    return None


@pytest.mark.parametrize(
    "pattern", [r"(a+)+", r"(\d+\.?)*", r"(?:\s*\w+)*$", r"(a*)*", r"(?:a{1,5})+", r"(?:x+y?){2,}"]
)
def test_policy_detector_flags_nested_quantifiers(pattern: str) -> None:
    assert nested_quantifier_problem(pattern) is not None


@pytest.mark.parametrize(
    "pattern",
    [
        r"^\d{1,3}(?:\.\d{1,3}){0,3}[.)]?\s",
        r"^(?:Стаття|Статья|Article)\s{1,3}\d{1,4}",
        r"^\(?[a-z]\)",
        r"^[IVXLC]{1,8}\.",
        r"^\s{0,10}\S",
    ],
)
def test_policy_detector_accepts_bounded_patterns(pattern: str) -> None:
    assert nested_quantifier_problem(pattern) is None


def _sources() -> list[Path]:
    return sorted(SEGMENT_DIR.glob("*.py"))


def test_policy_segment_package_exists_with_segmenter_module() -> None:
    assert (SEGMENT_DIR / "segmenter.py").is_file()


def _string_constants(tree: ast.AST) -> list[str]:
    return [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and len(n.value) >= 3
    ]


def test_policy_no_nested_quantifiers_in_source_string_constants() -> None:
    assert _sources(), "app/segment/ has no modules"
    problems: list[str] = []
    for path in _sources():
        for text in _string_constants(ast.parse(path.read_text(encoding="utf-8"))):
            problem = nested_quantifier_problem(text)
            if problem:
                problems.append(f"{path.name}: {problem}")

    assert problems == []


def test_policy_no_nested_quantifiers_in_patterns_compiled_at_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []
    real_compile = re._compile  # type: ignore[attr-defined]

    def recording(pattern: object, flags: int) -> object:
        if isinstance(pattern, str):
            seen.append(pattern)
        return real_compile(pattern, flags)

    monkeypatch.setattr(re, "_compile", recording)
    for name in [m for m in sys.modules if m == "app.segment" or m.startswith("app.segment.")]:
        monkeypatch.delitem(sys.modules, name)
    importlib.import_module("app.segment.segmenter")

    assert [p for p in seen if nested_quantifier_problem(p)] == []


def test_policy_no_whole_text_regex_calls_in_segment_package() -> None:
    assert _sources(), "app/segment/ has no modules"
    problems: list[str] = []
    for path in _sources():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in FORBIDDEN_CALLS
            ):
                # str.split / str.splitlines style helpers are fine on plain strings; the
                # policy forbids the regex methods, so any such call needs a line-level review.
                if node.func.attr == "split" and not _looks_like_regex_receiver(node.func.value):
                    continue
                problems.append(f"{path.name}:{node.lineno} .{node.func.attr}(")

    assert problems == []


def _looks_like_regex_receiver(value: ast.expr) -> bool:
    name = ast.unparse(value).lower()
    return "re" in name.split(".")[0] or "pattern" in name or name.endswith("_re")


def test_policy_no_regex_backreferences_or_lookbehind_in_source_patterns() -> None:
    assert _sources(), "app/segment/ has no modules"
    problems: list[str] = []
    for path in _sources():
        for text in _string_constants(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                re.search(r"\(\?<[=!]|\\[1-9]|\(\?P=", text)
                and nested_quantifier_problem(text) is None
            ):
                try:
                    _p.parse(text)
                except re.error:
                    continue
                problems.append(f"{path.name}: {text!r}")

    assert problems == []
