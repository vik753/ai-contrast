"""Calls into the S3-T3 public interface for the PDF tests.

``app.extraction.pdf`` is imported inside the helpers, so that before the
implementation exists every test fails on its own with ``ModuleNotFoundError``.

Assumed beyond the public interface (see the test report): ``extract_pdf`` raises
``ExtractionError`` (``app.extraction.model``) with a contract code.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.extraction.model import ExtractionError, ExtractionResult

DEFAULT_LIMITS: dict[str, int] = {"max_pages": 100, "max_prev_chain": 32}
DEFAULT_MAX_CHARS = 1_000_000
DEFAULT_MAX_BLOCKS = 20_000


def limits(**overrides: int) -> Any:
    from app.extraction.pdf import PdfLimits  # noqa: PLC0415 - fail per test

    return PdfLimits(**{**DEFAULT_LIMITS, **overrides})


def extract(
    data: bytes,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    max_blocks: int = DEFAULT_MAX_BLOCKS,
    **limit_overrides: int,
) -> ExtractionResult:
    from app.extraction.pdf import extract_pdf  # noqa: PLC0415 - fail per test

    return extract_pdf(
        data, max_chars=max_chars, max_blocks=max_blocks, limits=limits(**limit_overrides)
    )


def code(data: bytes, **kwargs: int) -> str:
    with pytest.raises(ExtractionError) as info:
        extract(data, **kwargs)
    return info.value.code


def texts(result: ExtractionResult) -> list[str]:
    return [b.text for b in result.blocks]


def joined(result: ExtractionResult) -> str:
    return "\n\n".join(b.text for b in result.blocks)


def squashed(result: ExtractionResult) -> str:
    """All text without whitespace: robust to how lines are joined in a block."""
    return "".join(joined(result).split())


def reasons(result: ExtractionResult) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in result.removed:
        out[item.reason] = out.get(item.reason, 0) + item.count
    return out


def warning_codes(result: ExtractionResult) -> list[str]:
    return [w.code for w in result.warnings]


def warnings_of(result: ExtractionResult, warning: str) -> list[int | None]:
    return [w.page for w in result.warnings if w.code == warning]


def samples(result: ExtractionResult, reason: str) -> str:
    return "\n".join(item.sample for item in result.removed if item.reason == reason)
