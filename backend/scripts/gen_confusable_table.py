# ruff: noqa: RUF001
"""Generate ``app/pseudo/confusable_table.py`` (ADR 0015 point 2, ADR 0009).

Run from ``backend/``:  ``uv run --locked python scripts/gen_confusable_table.py``
(writes the file) or with ``--check`` (exit 1 if the checked-in file differs).

Provenance. The table is a hand-written subset of the Unicode security
confusables (UTS #39, ``confusables.txt``, "MA" mappings), limited to the scripts that
matter for UK, RU and EN contracts: Latin, Cyrillic, Greek and decimal digits. The
build environment has no network access, so ``confusables.txt`` was not downloaded:
the pairs below are written by hand from the published mapping (visually identical
letters; the prototype is the Latin letter) and are the single source of truth. Digits
of other scripts map to ASCII digits by ``unicodedata.decimal`` (derived, deterministic
for the recorded Unicode version). Letters that look like digits (O and 0, l and 1) are
not here: UTS #39 maps digits to letters, which would break numeric matching; the
detector handles those pairs in its numeric validators.

Direction: the skeleton of a character is its Latin prototype, if it has one. NFKC runs
before the skeleton, so full-width and ligature forms are already folded.
"""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path
from typing import Final

TABLE_FILE: Final = (
    Path(__file__).resolve().parent.parent / "app" / "pseudo" / "confusable_table.py"
)

# (source code point, Latin prototype), sorted by the generator.
CYRILLIC: Final = (
    ("А", "A"), ("В", "B"), ("Е", "E"), ("К", "K"), ("М", "M"), ("Н", "H"), ("О", "O"),
    ("Р", "P"), ("С", "C"), ("Т", "T"), ("Х", "X"), ("У", "Y"), ("І", "I"), ("Ј", "J"),
    ("Ѕ", "S"), ("Ԛ", "Q"), ("Ԝ", "W"), ("Ү", "Y"), ("Ӏ", "I"), ("Ꭺ", "A"),
    ("а", "a"), ("с", "c"), ("е", "e"), ("о", "o"), ("р", "p"), ("х", "x"), ("у", "y"),
    ("і", "i"), ("ј", "j"), ("ѕ", "s"), ("ԁ", "d"), ("ԛ", "q"), ("ԝ", "w"), ("һ", "h"),
    ("ӏ", "l"), ("ɡ", "g"),
)  # fmt: skip
GREEK: Final = (
    ("Α", "A"), ("Β", "B"), ("Ε", "E"), ("Ζ", "Z"), ("Η", "H"), ("Ι", "I"), ("Κ", "K"),
    ("Μ", "M"), ("Ν", "N"), ("Ο", "O"), ("Ρ", "P"), ("Τ", "T"), ("Υ", "Y"), ("Χ", "X"),
    ("α", "a"), ("γ", "y"), ("ι", "i"), ("κ", "k"), ("ν", "v"), ("ο", "o"), ("ρ", "p"),
    ("υ", "u"), ("χ", "x"),
)  # fmt: skip
LATIN: Final = (("ı", "i"), ("İ", "I"), ("ǀ", "l"), ("ſ", "f"))
# First code point of each block of ten decimal digits (value 0..9).
DIGIT_BLOCKS: Final = (
    0x0660, 0x06F0, 0x07C0, 0x0966, 0x09E6, 0x0A66, 0x0AE6, 0x0B66, 0x0BE6, 0x0C66,
    0x0CE6, 0x0D66, 0x0E50, 0x0ED0, 0x0F20, 0x1040, 0x17E0, 0x1810, 0xFF10,
)  # fmt: skip


def pairs() -> list[tuple[int, int]]:
    result: dict[int, int] = {}
    for source, prototype in (*CYRILLIC, *GREEK, *LATIN):
        result[ord(source)] = ord(prototype)
    for first in DIGIT_BLOCKS:
        for offset in range(10):
            char = chr(first + offset)
            if unicodedata.decimal(char) != offset:
                msg = f"not digit {offset}: U+{first + offset:04X}"
                raise SystemExit(msg)
            result[first + offset] = ord("0") + offset
    return sorted(result.items())


def render() -> str:
    lines = [
        '"""Confusable skeleton table (ADR 0015 point 2). GENERATED, do not edit.',
        "",
        "Made by ``backend/scripts/gen_confusable_table.py`` (see its docstring for the",
        "provenance); a test fails if this file differs from the generator output.",
        "Sorted ``(code point, prototype code point)`` pairs.",
        '"""',
        "",
        "from typing import Final",
        "",
        f'UNICODE_VERSION: Final = "{unicodedata.unidata_version}"',
        "PAIRS: Final[tuple[tuple[int, int], ...]] = (",
    ]
    lines.extend(f"    (0x{source:04X}, 0x{target:04X})," for source, target in pairs())
    lines.append(")")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    content = render()
    if "--check" in argv:
        if not TABLE_FILE.is_file() or TABLE_FILE.read_text(encoding="utf-8") != content:
            sys.stderr.write("confusable_table.py differs from the generator output\n")
            return 1
        return 0
    TABLE_FILE.write_text(content, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
