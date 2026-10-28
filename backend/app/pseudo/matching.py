# ruff: noqa: RUF001, RUF002
"""The matching view of the document (ADR 0015 point 2, ADR 0009).

The cleaned blocks are joined with ``\\n`` into ``g``. The view is ``g`` without line-end
hyphens (a letter, a hyphen, a line break and a lower-case letter) and in NFKC; the skeleton
is the view with the confusable table applied (Latin prototypes), and ``low`` is the
skeleton in lower case. The three strings have the same length. ``src`` maps a view index to
the index in ``g`` of the source character it came from (``None`` means identity). A match
in the view maps back with ``g_start`` / ``g_end``; when a source character expands to
several view characters (``\\u2116`` becomes ``No``), a boundary inside it is snapped
outward to the whole source character. Masks always point to cleaned-block offsets.
"""

from __future__ import annotations

import unicodedata
from array import array
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Final

from app.pseudo.confusable_table import PAIRS

SKELETON: Final[dict[int, int]] = dict(PAIRS)
HYPHENS: Final = frozenset("-‐‑")
_CYRILLIC_LOW: Final = 0x0400
_CYRILLIC_HIGH: Final = 0x04FF


def _latin_to_cyrillic() -> dict[int, int]:
    table: dict[int, int] = {}
    for source, target in PAIRS:
        if _CYRILLIC_LOW <= source <= _CYRILLIC_HIGH and target not in table:
            table[target] = source
    return table


LATIN_TO_CYRILLIC: Final = _latin_to_cyrillic()


def lower_same_length(text: str) -> str:
    result = text.lower()
    if len(result) == len(text):
        return result
    return "".join(c.lower() if len(c.lower()) == 1 else c for c in text)


def upper_same_length(text: str) -> str:
    result = text.upper()
    if len(result) == len(text):
        return result
    return "".join(c.upper() if len(c.upper()) == 1 else c for c in text)


def fold_view(text: str) -> str:
    """Upper case, skeleton, lower case: capital Cyrillic look-alikes map to Latin before the
    case is dropped, so ``В`` and ``в`` both match ``B``/``b``. Same length as ``text``."""
    return lower_same_length(upper_same_length(text).translate(SKELETON))


def fold(text: str) -> str:
    """NFKC and ``fold_view``: the form in which table entries are compared."""
    return fold_view(unicodedata.normalize("NFKC", text))


@dataclass(slots=True)
class View:
    g: str
    bases: list[int]
    sizes: list[int]
    u: str  # NFKC view, case and scripts kept (names)
    s: str  # skeleton
    low: str  # lower-case skeleton
    src: array[int] | None
    extra: dict[int, int] = field(default_factory=dict)  # view index -> end after dropped marks

    def g_start(self, index: int) -> int:
        """Start in ``g`` of the view character ``index`` (``0 <= index < len(u)``)."""
        return index if self.src is None else self.src[index]

    def g_end(self, index: int) -> int:
        """Exclusive end in ``g`` of the view range that ends before ``index``.

        Precondition: ``index >= 1`` (the range is not empty). Combining marks that follow
        the last character are part of it.
        """
        if self.src is None:
            return index
        return self.extra.get(index - 1, self.src[index - 1] + 1)

    def spans(self, start: int, end: int) -> list[tuple[int, int, int]]:
        """``(block, start, end)`` pieces of the view range ``[start, end)``, snapped outward."""
        return self.g_pieces(self.g_start(start), self.g_end(end))

    def g_pieces(self, gs: int, ge: int) -> list[tuple[int, int, int]]:
        """``(block, start, end)`` pieces of the range ``[gs, ge)`` of ``g``."""
        block = bisect_right(self.bases, gs) - 1
        pieces: list[tuple[int, int, int]] = []
        while block < len(self.bases):
            block_end = self.bases[block] + self.sizes[block]
            if gs < block_end:
                piece_end = min(ge, block_end)
                pieces.append((block, gs - self.bases[block], piece_end - self.bases[block]))
            if ge <= block_end:
                break
            block += 1
            gs = max(gs, self.bases[block])
        return pieces

    def block_of(self, index: int) -> int:
        return bisect_right(self.bases, self.g_start(index)) - 1


def _joins(g: str) -> list[int]:
    """Indexes of hyphens that are line-end joins (letter, hyphen, LF, lower-case letter)."""
    found: list[int] = []
    position = g.find("\n")
    size = len(g)
    while position != -1:
        if (
            0 < position < size - 1
            and g[position - 1] in HYPHENS
            and position >= 2  # noqa: PLR2004 - a letter before the hyphen
            and g[position - 2].isalpha()
            and g[position + 1].islower()
        ):
            found.append(position - 1)
        position = g.find("\n", position + 1)
    return found


def _changes(g: str) -> dict[str, str]:
    """Characters that the view changes: NFKC expansions and dropped combining marks.

    One check per distinct character, not per position.
    """
    changes: dict[str, str] = {}
    for char in set(g):
        if char.isascii():
            continue
        if unicodedata.category(char) == "Mn":
            changes[char] = ""
            continue
        normal = unicodedata.normalize("NFKC", char)
        if normal != char:
            changes[char] = normal
    return changes


def build_view(texts: list[str]) -> View:
    bases: list[int] = []
    sizes: list[int] = []
    offset = 0
    for text in texts:
        bases.append(offset)
        sizes.append(len(text))
        offset += len(text) + 1
    g = "\n".join(texts)
    joins = _joins(g)
    changes = _changes(g)
    extra: dict[int, int] = {}
    if not joins and not changes and unicodedata.is_normalized("NFKC", g):
        view = g
        src = None
    else:
        pieces: list[str] = []
        src = array("i")
        previous = 0
        for hyphen in [*joins, len(g)]:
            _append_chunk(g[previous:hyphen], previous, changes, pieces, src, extra)
            previous = hyphen + 2  # the hyphen and the line break are dropped
        view = "".join(pieces)
    skeleton = view.translate(SKELETON)
    return View(g, bases, sizes, view, skeleton, fold_view(view), src, extra)


def _append_chunk(  # noqa: PLR0913, PLR0917
    chunk: str,
    first: int,
    changes: dict[str, str],
    pieces: list[str],
    src: array[int],
    extra: dict[int, int],
) -> None:
    """Append a chunk; a dropped mark extends the end of the character before it."""
    if not chunk:
        return
    if changes.keys().isdisjoint(chunk):
        pieces.append(chunk)
        src.extend(range(first, first + len(chunk)))
        return
    for index, char in enumerate(chunk):
        normal = changes.get(char, char)
        if normal:
            pieces.append(normal)
            src.extend([first + index] * len(normal))
        elif src:
            extra[len(src) - 1] = first + index + 1
