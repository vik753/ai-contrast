"""Calls into the S3-T2 public interface for the DOCX tests.

``app.extraction.docx`` is imported inside the helpers, so that before the
implementation exists every test fails on its own with ``ModuleNotFoundError``.

Assumed beyond the public interface (see the test report): ``extract_docx``
raises ``ExtractionError`` (``app.extraction.model``) whose ``code`` is one of the
contract codes, including ``archive_rejected`` and ``unsupported_type``.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.extraction.model import ExtractionError, ExtractionResult

MIB = 1024 * 1024
DEFAULT_LIMITS: dict[str, int] = {
    "max_part_bytes": 32 * MIB,
    "max_total_bytes": 100 * MIB,
    "max_xml_depth": 256,
    "max_elements": 2_000_000,
}
DEFAULT_MAX_CHARS = 1_000_000
DEFAULT_MAX_BLOCKS = 20_000


def limits(**overrides: int) -> Any:
    from app.extraction.docx import DocxLimits  # noqa: PLC0415 - fail per test

    return DocxLimits(**{**DEFAULT_LIMITS, **overrides})


def extract(
    data: bytes,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    max_blocks: int = DEFAULT_MAX_BLOCKS,
    **limit_overrides: int,
) -> ExtractionResult:
    from app.extraction.docx import extract_docx  # noqa: PLC0415 - fail per test

    return extract_docx(
        data, max_chars=max_chars, max_blocks=max_blocks, limits=limits(**limit_overrides)
    )


def code(data: bytes, **kwargs: int) -> str:
    with pytest.raises(ExtractionError) as info:
        extract(data, **kwargs)
    return info.value.code


def texts(result: ExtractionResult, part: str | None = None) -> list[str]:
    return [b.text for b in result.blocks if part is None or b.part == part]


def joined(result: ExtractionResult) -> str:
    return "\n\n".join(b.text for b in result.blocks)


def reasons(result: ExtractionResult) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in result.removed:
        out[item.reason] = out.get(item.reason, 0) + item.count
    return out


def warning_codes(result: ExtractionResult) -> list[str]:
    return [w.code for w in result.warnings]
