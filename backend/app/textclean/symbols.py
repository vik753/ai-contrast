"""Symbol-font checkbox glyphs (ADR 0009 Layer 1): one table for every input path.

Private-use code points of the Wingdings and Symbol fonts that mean a checkbox are
mapped to U+2610, U+2611 or U+2612 *before* private-use code points are removed, so
that "☒ covered" keeps its meaning. The DOCX walker uses the same table for
``w:sym`` elements.
"""

from __future__ import annotations

from typing import Final

CHECKED: Final = "☒"
UNCHECKED: Final = "☐"
CHECKBOX_GLYPHS: Final = "☐☑☒"
WINGDINGS: Final = {0xF0FE: "☑", 0xF0FD: "☒", 0xF0A8: "☐", 0xF06F: "☐", 0xF078: "☒"}
CHECKBOX_TABLE: Final = str.maketrans(WINGDINGS)
