"""Stage 3 response contract of ``POST /api/extract`` (docs/agent/TASKS.md, Stage 3).

The models are strict and forbid unknown keys: the parent validates every result
of the parsing child with them (ADR 0011), so anything outside the contract fails
closed with ``extraction_failed``.

``ExtractionError`` carries a fixed code only. Its message never holds input bytes
or text, so it is safe to log and to return.
"""

from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, PositiveInt

MIB: Final = 1024 * 1024

# Defaults of the caps: the one source for the settings, the sandbox limits and the
# DOCX limits.
DEFAULT_MAX_TEXT_CHARS: Final = 1_000_000
DEFAULT_MAX_BLOCKS: Final = 20_000
DEFAULT_MAX_ZIP_UNCOMPRESSED_BYTES: Final = 100 * MIB
DEFAULT_MAX_DOCX_PART_BYTES: Final = 32 * MIB
DEFAULT_MAX_DOCX_XML_DEPTH: Final = 256
DEFAULT_MAX_DOCX_ELEMENTS: Final = 2_000_000

MAX_SAMPLE_CHARS: Final = 200

Kind = Literal["pdf", "docx", "text"]
Language = Literal["uk", "ru", "en", "mixed", "unknown"]
Part = Literal["body", "footnote", "endnote", "header", "footer", "textbox"]
# Reasons and warning codes are fixed identifiers, never free text.
Code = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")]

# Error codes of stage 3 (422 in the API).
EXTRACTION_FAILED: Final = "extraction_failed"
EXTRACTION_TIMEOUT: Final = "extraction_timeout"
TOO_MANY_PAGES: Final = "too_many_pages"
TOO_MUCH_TEXT: Final = "too_much_text"
ENCRYPTED_UNSUPPORTED: Final = "encrypted_unsupported"
NO_TEXT_EXTRACTED: Final = "no_text_extracted"
TEXT_DECODING_FAILED: Final = "text_decoding_failed"
SUSPICIOUS_PACKAGE: Final = "suspicious_package"
DOCX_STRICT_UNSUPPORTED: Final = "docx_strict_unsupported"
PDF_DAMAGED: Final = "pdf_damaged"

# Codes that the parsing child may report. The parent's own codes (timeout and
# failure) are not in this list: a child cannot claim them.
ChildErrorCode = Literal[
    "archive_rejected",
    "unsupported_type",
    "too_many_pages",
    "too_much_text",
    "encrypted_unsupported",
    "no_text_extracted",
    "text_decoding_failed",
    "suspicious_package",
    "docx_strict_unsupported",
    "pdf_damaged",
]


class ExtractionError(Exception):
    """Extraction failed. ``code`` is one of the stage 3 error codes."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class Block(_Strict):
    text: str
    part: Part
    page: PositiveInt | None


class Removed(_Strict):
    reason: Code
    count: PositiveInt
    sample: Annotated[str, Field(max_length=MAX_SAMPLE_CHARS)]


class Warning(_Strict):
    code: Code
    page: PositiveInt | None


class ExtractionResult(_Strict):
    kind: Kind
    bytes: NonNegativeInt
    language: Language
    pages: PositiveInt | None
    blocks: list[Block]
    ocr_pages: list[PositiveInt]
    removed: list[Removed]
    warnings: list[Warning]
