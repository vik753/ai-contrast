"""Plain-text extraction (S3-T1 AC4, AC6; threat model T4).

``extract_text_file`` is pure and runs inside the parsing child (ADR 0011).

1. Decoding, strict: a UTF-16 BOM → UTF-16 of that byte order (odd length fails);
   a UTF-8 BOM → UTF-8; otherwise UTF-8, then CP1251. Failure →
   ``text_decoding_failed``.
2. More decoded characters than ``max_chars`` → ``too_much_text``.
3. The control-character rule of detection runs again on the whole text: any NUL,
   or more than 1 % C0 controls other than TAB, LF, FF and CR →
   ``text_decoding_failed`` (fail closed; detection saw only the first 64 KiB).
4. Newlines (CR LF, CR, NEL U+0085, LS U+2028, PS U+2029) are normalized to
   ``\\n``. Other control characters (Unicode category Cc, TAB and LF excepted) are
   removed and reported in ``removed`` (reason ``control_characters``, with a sample
   of their code points such as ``U+0001``).
5. Blocks are split at blank lines (lines with
   only whitespace) and trimmed; empty blocks are dropped. More blocks than
   ``max_blocks`` → ``too_much_text``; no block → ``no_text_extracted``.

Errors carry codes only, never text.
"""

from __future__ import annotations

import re
from typing import Final

from app.extraction.language import detect_language
from app.extraction.model import (
    DEFAULT_MAX_BLOCKS,
    DEFAULT_MAX_TEXT_CHARS,
    NO_TEXT_EXTRACTED,
    TEXT_DECODING_FAILED,
    TOO_MUCH_TEXT,
    Block,
    ExtractionError,
    ExtractionResult,
    Removed,
)

UTF8_BOM: Final = b"\xef\xbb\xbf"
UTF16_LE_BOM: Final = b"\xff\xfe"
UTF16_BE_BOM: Final = b"\xfe\xff"

MAX_CONTROL_PERCENT: Final = 1
# C0 controls except NUL (any NUL fails), TAB, LF, FF and CR; the same rule as detection.
_CONTROL_CHARS: Final = tuple(
    chr(c) for c in range(0x20) if c not in {0x00, 0x09, 0x0A, 0x0C, 0x0D}
)

# Cc characters that are kept: TAB and LF. CR, NEL, LS and PS become LF first.
_LINE_BREAKS: Final = re.compile(r"\r\n|[\r\u0085\u2028\u2029]")
_REMOVED_CONTROLS: Final = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
CONTROL_CHARACTERS: Final = "control_characters"
# How many distinct code points the sample lists (each ``U+XXXX`` is 6 characters).
_SAMPLE_CODE_POINTS: Final = 16

# A blank line: a line break, then lines that hold only whitespace, then a line break.
_BLANK_LINES: Final = re.compile(r"\n(?:[^\S\n]*\n)+")


def _decode(data: bytes) -> str:
    try:
        if data.startswith(UTF16_LE_BOM):
            return data[len(UTF16_LE_BOM) :].decode("utf-16-le")
        if data.startswith(UTF16_BE_BOM):
            return data[len(UTF16_BE_BOM) :].decode("utf-16-be")
        if data.startswith(UTF8_BOM):
            return data[len(UTF8_BOM) :].decode("utf-8")
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode("cp1251")
    except UnicodeDecodeError:
        # `from None`: the decode error holds the input bytes.
        raise ExtractionError(TEXT_DECODING_FAILED) from None


def _check_controls(text: str) -> None:
    if "\x00" in text:
        raise ExtractionError(TEXT_DECODING_FAILED)
    controls = sum(text.count(char) for char in _CONTROL_CHARS)
    if controls * 100 > len(text) * MAX_CONTROL_PERCENT:
        raise ExtractionError(TEXT_DECODING_FAILED)


def _remove_controls(text: str) -> tuple[str, list[Removed]]:
    found: set[str] = set()
    count = 0

    def note(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        if len(found) < _SAMPLE_CODE_POINTS:
            found.add(match.group())
        return ""

    cleaned = _REMOVED_CONTROLS.sub(note, text)
    if not count:
        return cleaned, []
    sample = " ".join(f"U+{ord(char):04X}" for char in sorted(found))
    return cleaned, [Removed(reason=CONTROL_CHARACTERS, count=count, sample=sample)]


def _split_blocks(text: str, max_blocks: int) -> list[Block]:
    blocks: list[Block] = []

    def add(raw: str) -> None:
        block = raw.strip()
        if not block:
            return
        if len(blocks) >= max_blocks:
            raise ExtractionError(TOO_MUCH_TEXT)
        blocks.append(Block(text=block, part="body", page=None))

    start = 0
    for match in _BLANK_LINES.finditer(text):
        add(text[start : match.start()])
        start = match.end()
    add(text[start:])
    return blocks


def extract_text_file(
    data: bytes,
    *,
    max_chars: int = DEFAULT_MAX_TEXT_CHARS,
    max_blocks: int = DEFAULT_MAX_BLOCKS,
) -> ExtractionResult:
    text = _decode(data)
    if len(text) > max_chars:
        raise ExtractionError(TOO_MUCH_TEXT)
    _check_controls(text)
    text, removed = _remove_controls(_LINE_BREAKS.sub("\n", text))
    blocks = _split_blocks(text, max_blocks)
    if not blocks:
        raise ExtractionError(NO_TEXT_EXTRACTED)
    return ExtractionResult(
        kind="text",
        bytes=len(data),
        language=detect_language(text),
        pages=None,
        blocks=blocks,
        ocr_pages=[],
        removed=removed,
        warnings=[],
    )
