"""Linear-time phrase index over word stems (ADR 0018 point 2).

An entry is a sequence of words with the separators between them. A word matches a clause
word that starts with it (a stem); in risk mode a word followed by ``$`` matches the whole
word only. Whitespace runs are one flexible separator; any other separator text is
literal. A match never starts mid-word. Entries are data: no regex is built from them.

Cost: one pass over the clause words; per word at most the longest stem in character steps
and the live partial matches (bounded by the size of the entry set), so time grows
linearly with the text.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Final

from app.pseudo.matching import fold

__all__ = ["PhraseIndex", "folded_view"]

_WORD: Final = re.compile(r"[^\W_]+")
_SPACE: Final = re.compile(r"\s+")
_Key = tuple[str | None, int]


def folded_view(text: str) -> tuple[str, list[int] | None]:
    """The folded view (NFKC, skeleton, lower case) and, when its length differs from
    ``text``, the source index of every view character."""
    view = fold(text)
    if len(view) == len(text):
        return view, None
    pieces: list[str] = []
    cache: dict[str, str] = {}
    for char in text:
        piece = cache.get(char)
        if piece is None:
            piece = cache[char] = fold(char)
        pieces.append(piece)
    view = "".join(pieces)
    source: list[int] = []
    for index, piece in enumerate(pieces):
        source.extend([index] * len(piece))
    return view, source


class _Stem:
    __slots__ = ("next", "stem")

    def __init__(self) -> None:
        self.next: dict[str, _Stem] = {}
        self.stem: int | None = None


def _parse(entry: str, *, exact_marker: bool) -> tuple[list[tuple[str, bool]], list[str]]:
    view = fold(entry)
    words: list[tuple[str, bool]] = []
    seps: list[str] = []
    previous_end = -1
    for match in _WORD.finditer(view):
        end = match.end()
        exact = exact_marker and view[end : end + 1] == "$"
        if previous_end >= 0:
            seps.append(_SPACE.sub(" ", view[previous_end : match.start()]))
        words.append((match.group(), exact))
        previous_end = end + 1 if exact else end
    return words, seps


class PhraseIndex:
    """Entries ``(key, text)``; ``find`` returns ``(key, start, end)`` into the view."""

    def __init__(self, entries: Iterable[tuple[str, str]], *, exact_marker: bool = False) -> None:
        self._root = _Stem()
        self._exact: dict[str, int] = {}
        self._ids: dict[tuple[str, bool], int] = {}
        self._children: list[dict[_Key, int]] = [{}]
        self._keys: list[list[str]] = [[]]
        for key, text in entries:
            words, seps = _parse(text, exact_marker=exact_marker)
            if not words:
                continue
            node = 0
            for index, (word, exact) in enumerate(words):
                sid = self._stem_id(word, exact)
                edge: _Key = (seps[index - 1] if index else None, sid)
                child = self._children[node].get(edge)
                if child is None:
                    child = len(self._children)
                    self._children.append({})
                    self._keys.append([])
                    self._children[node][edge] = child
                node = child
            if key not in self._keys[node]:
                self._keys[node].append(key)

    def _stem_id(self, word: str, exact: bool) -> int:
        known = self._ids.get((word, exact))
        if known is not None:
            return known
        sid = len(self._ids)
        self._ids[(word, exact)] = sid
        if exact:
            self._exact[word] = sid
        else:
            node = self._root
            for char in word:
                node = node.next.setdefault(char, _Stem())
            node.stem = sid
        return sid

    def _stems_of(self, word: str) -> list[int]:
        found: list[int] = []
        node = self._root
        for char in word:
            nxt = node.next.get(char)
            if nxt is None:
                break
            node = nxt
            if node.stem is not None:
                found.append(node.stem)
        exact = self._exact.get(word)
        if exact is not None:
            found.append(exact)
        return found

    def find(self, view: str) -> list[tuple[str, int, int]]:
        out: list[tuple[str, int, int]] = []
        active: dict[int, int] = {}  # node -> start of the match
        previous_end = 0
        children = self._children
        for match in _WORD.finditer(view):
            start, end = match.span()
            ids = self._stems_of(match.group())
            reached: dict[int, int] = {}
            if ids:
                if active:
                    sep = _SPACE.sub(" ", view[previous_end:start])
                    for node, begun in active.items():
                        kids = children[node]
                        for sid in ids:
                            child = kids.get((sep, sid))
                            if child is not None:
                                reached[child] = begun
                for sid in ids:
                    child = children[0].get((None, sid))
                    if child is not None:
                        reached.setdefault(child, start)
            active = {}
            for node, begun in reached.items():
                out.extend((key, begun, end) for key in self._keys[node])
                if children[node]:
                    active[node] = begun
            previous_end = end
        return out
