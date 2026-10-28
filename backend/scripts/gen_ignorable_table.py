"""Generate ``app/textclean/ignorable_table.py`` (ADR 0009 Layer 1, S5-T1b).

Run from ``backend/``:  ``uv run --locked python scripts/gen_ignorable_table.py``
(writes the file) or with ``--check`` (exit 1 if the checked-in file differs).

Source of truth: Python's ``unicodedata`` (its Unicode version is recorded in the
table). ``Default_Ignorable_Code_Point`` is not exposed by ``unicodedata``, so it is
derived from its definition (UAX #44, DerivedCoreProperties.txt):

    Other_Default_Ignorable_Code_Point (listed below) + Cf + Variation_Selector
    - White_Space - U+FFF9..U+FFFB - U+13430..U+1343F - Prepended_Concatenation_Mark

The table is that set united with the categories Cs, Co, Cn and Cc and with the code
points that ADR 0009 names (U+2800, U+180E, U+FFF9..U+FFFB), minus TAB, LF and CR.
Cf is in the table whole, so the subtractions above change nothing in the result;
they are kept so that the derivation matches the definition. White space that is not
a control character (U+0020, U+00A0, U+2000..U+200A, ...) is never in the table.
"""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path
from typing import Final

TABLE_FILE: Final = (
    Path(__file__).resolve().parent.parent / "app" / "textclean" / "ignorable_table.py"
)

# Unicode 15.1 PropList.txt, Other_Default_Ignorable_Code_Point.
OTHER_DEFAULT_IGNORABLE: Final = (
    (0x034F, 0x034F),
    (0x115F, 0x1160),
    (0x17B4, 0x17B5),
    (0x2065, 0x2065),
    (0x3164, 0x3164),
    (0xFFA0, 0xFFA0),
    (0xFFF0, 0xFFF8),
    (0xE0000, 0xE0FFF),
)
# Unicode 15.1 PropList.txt, Variation_Selector.
VARIATION_SELECTOR: Final = (
    (0x180B, 0x180D),
    (0x180F, 0x180F),
    (0xFE00, 0xFE0F),
    (0xE0100, 0xE01EF),
)
# Unicode 15.1 PropList.txt, White_Space.
WHITE_SPACE: Final = (
    (0x0009, 0x000D),
    (0x0020, 0x0020),
    (0x0085, 0x0085),
    (0x00A0, 0x00A0),
    (0x1680, 0x1680),
    (0x2000, 0x200A),
    (0x2028, 0x2029),
    (0x202F, 0x202F),
    (0x205F, 0x205F),
    (0x3000, 0x3000),
)
# Unicode 15.1 PropList.txt, Prepended_Concatenation_Mark.
PREPENDED_CONCATENATION_MARK: Final = (
    (0x0600, 0x0605),
    (0x06DD, 0x06DD),
    (0x070F, 0x070F),
    (0x0890, 0x0891),
    (0x08E2, 0x08E2),
    (0x110BD, 0x110BD),
    (0x110CD, 0x110CD),
)
# Subtracted by the definition (they are Cf, so the table keeps them anyway).
NOT_DEFAULT_IGNORABLE: Final = ((0xFFF9, 0xFFFB), (0x13430, 0x1343F))
# Named in ADR 0009 Layer 1 although they are not (or not only) default ignorable.
NAMED: Final = ((0x180E, 0x180E), (0x2800, 0x2800), (0xFFF9, 0xFFFB))
# Categories removed whole. Cc minus TAB, LF, CR (below).
CATEGORIES: Final = frozenset({"Cc", "Cf", "Co", "Cs", "Cn"})
KEPT_CONTROLS: Final = frozenset({0x09, 0x0A, 0x0D})
MAX_CODE_POINT: Final = 0x10FFFF


def _expand(ranges: tuple[tuple[int, int], ...]) -> set[int]:
    return {cp for low, high in ranges for cp in range(low, high + 1)}


def default_ignorable() -> set[int]:
    out = _expand(OTHER_DEFAULT_IGNORABLE) | _expand(VARIATION_SELECTOR)
    out |= {cp for cp in range(MAX_CODE_POINT + 1) if unicodedata.category(chr(cp)) == "Cf"}
    out -= _expand(WHITE_SPACE)
    out -= _expand(NOT_DEFAULT_IGNORABLE)
    out -= _expand(PREPENDED_CONCATENATION_MARK)
    return out


def removed_code_points() -> set[int]:
    out = default_ignorable() | _expand(NAMED)
    out |= {cp for cp in range(MAX_CODE_POINT + 1) if unicodedata.category(chr(cp)) in CATEGORIES}
    out |= _expand(PREPENDED_CONCATENATION_MARK)  # Cf
    return out - KEPT_CONTROLS


def ranges() -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for cp in sorted(removed_code_points()):
        if merged and merged[-1][1] + 1 == cp:
            merged[-1] = (merged[-1][0], cp)
        else:
            merged.append((cp, cp))
    return merged


def render_table() -> str:
    lines = [
        '"""Code points removed by Layer 1 cleaning (ADR 0009). GENERATED, do not edit.',
        "",
        "Made by ``backend/scripts/gen_ignorable_table.py``; a test fails if this file differs",
        "from the generator output. Sorted, non-overlapping, inclusive ``(low, high)`` pairs.",
        '"""',
        "",
        "from typing import Final",
        "",
        f'UNICODE_VERSION: Final = "{unicodedata.unidata_version}"',
        "RANGES: Final[tuple[tuple[int, int], ...]] = (",
    ]
    lines += [f"    (0x{low:04X}, 0x{high:04X})," for low, high in ranges()]
    lines += [")", ""]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    rendered = render_table()
    if "--check" in argv:
        return 0 if TABLE_FILE.read_text(encoding="utf-8") == rendered else 1
    TABLE_FILE.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
