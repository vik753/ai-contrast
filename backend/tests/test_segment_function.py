"""S5-T1 AC1: the pure function ``segment`` (deterministic, raises ``SegmentError``).

Assumed public names (see the test report): ``app.segment.segmenter`` exports
``segment``, ``SegmentLimits(max_clauses=..., max_clause_chars=...)``,
``SegmentError`` (attribute ``code``) and ``InputBlock(text=, part=, page=)``;
the result has ``clauses``, ``blocks``, ``removed``, ``warnings``.
"""

from __future__ import annotations

import importlib
import inspect
from typing import Any

import pytest


class _Lazy:
    def __getattr__(self, name: str) -> Any:
        return getattr(importlib.import_module("app.segment.segmenter"), name)


segmenter = _Lazy()
DEFAULT = {"max_clauses": 2000, "max_clause_chars": 20_000}


def _blocks(*texts: str) -> list[Any]:
    return [segmenter.InputBlock(text=t, part="body", page=None) for t in texts]


def _limits(**changes: int) -> Any:
    return segmenter.SegmentLimits(**{**DEFAULT, **changes})


def test_segment_function_is_deterministic() -> None:
    blocks = _blocks("PREAMBLE", "1. First.", "a) item", "2. Second.", "5. Gap.")

    first = segmenter.segment(blocks, limits=_limits())
    second = segmenter.segment(blocks, limits=_limits())

    assert first == second


def test_segment_function_takes_limits_as_keyword_only() -> None:
    parameters = inspect.signature(segmenter.segment).parameters

    assert parameters["limits"].kind is inspect.Parameter.KEYWORD_ONLY


def test_segment_function_does_not_modify_its_input() -> None:
    blocks = _blocks("1. A\u200bB.", "2. C.")
    before = [(b.text, b.part, b.page) for b in blocks]

    segmenter.segment(blocks, limits=_limits())

    assert [(b.text, b.part, b.page) for b in blocks] == before


def test_segment_function_raises_segment_error_with_code_for_too_many_clauses() -> None:
    with pytest.raises(segmenter.SegmentError) as info:
        segmenter.segment(_blocks("1. a.", "2. b.", "3. c."), limits=_limits(max_clauses=2))

    assert info.value.code == "too_many_clauses"


def test_segment_function_raises_segment_error_with_code_for_clause_too_long() -> None:
    with pytest.raises(segmenter.SegmentError) as info:
        segmenter.segment(_blocks("1. " + "a" * 200), limits=_limits(max_clause_chars=100))

    assert info.value.code == "clause_too_long"


def test_segment_function_accepts_a_tuple_of_blocks() -> None:
    result = segmenter.segment(tuple(_blocks("1. a.", "2. b.")), limits=_limits())

    assert len(result.clauses) == 2
