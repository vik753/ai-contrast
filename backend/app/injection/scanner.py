"""Layer 2 detector: text addressed to an AI, special tokens, look-alikes (ADR 0009, ADR 0017).

The input is Layer 1 clean text. Matching runs on a view of the text: NFKC, the confusable
skeleton and lower case (``app.pseudo.matching.fold``), so homoglyph and full-width variants
meet the same pattern. Every pattern is linear in the text: fixed strings are found with
``str.find``; a word rule looks at a window of at most ``WINDOW`` characters after an anchor
word; the placeholder and base64 patterns are single bounded repeats. Hit spans are offsets
into the input text. A text with more than ``MAX_HITS`` hits keeps the high ones first and is
still flagged (a cap fails closed). Nothing here logs or returns text.
"""

from __future__ import annotations

import re
from array import array
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from typing import Final, Literal

from app.injection import patterns as p
from app.pseudo.matching import fold

__all__ = ["WORD", "Hit", "WordSet", "colour_rating", "matching_view", "scan"]

WINDOW: Final = 200
FOLLOWWORDS: Final = 9
MAX_TARGET_DISTANCE: Final = 8
MAX_AS_DISTANCE: Final = 4
MAX_LINKS: Final = 2
MAX_BARE_FILLERS: Final = 3
MAX_TOKEN_CHARS: Final = 40
_PLACEHOLDER_MIN_LETTER_DOT: Final = 2

WORD: Final = re.compile(r"[^\W_]+")
_TOKEN_BODY: Final = re.compile(r"[a-z0-9_ -]{1,40}\|>")
_PLACEHOLDER: Final = re.compile(r"[^\[\]\s]{1,40}\]")
_BASE64: Final = re.compile(rf"[A-Za-z0-9+/]{{{p.BASE64_MIN_RUN},}}={{0,2}}")

Cls = Literal["heuristic", "high"]


@dataclass(frozen=True, slots=True)
class Hit:
    """A match: class and ``[start, end)`` offsets into the scanned text."""

    cls: Cls
    start: int
    end: int


class WordSet:
    """Folded whole words and folded stems."""

    def __init__(self, entries: tuple[str, ...]) -> None:
        self.exact = frozenset(fold(e) for e in entries if not e.endswith("*"))
        self.stems = tuple(fold(e[:-1]) for e in entries if e.endswith("*"))

    def __contains__(self, word: str) -> bool:
        return word in self.exact or word.startswith(self.stems)


_IGNORE = WordSet(p.IGNORE_VERBS)
_TARGETS = WordSet(p.INSTRUCTION_TARGETS)
_ALL = WordSet(p.ALL_WORDS)
_ABOVE = WordSet(p.ABOVE_WORDS)
_SYSTEM = WordSet(p.SYSTEM_WORDS)
_PROMPT = WordSet(p.PROMPT_WORDS)
_RATE = WordSet(p.RATE_VERBS)
_INSTRUCTION = WordSet(p.INSTRUCTION_WORDS)
_FOR = WordSet(p.FOR_WORDS)
_LINK = WordSet(p.LINK_WORDS)
_THE = WordSet(p.THE_WORDS)
_STRONG_AI = WordSet(p.AI_WORDS)
_LANGUAGE = WordSet(p.LANGUAGE_WORDS)
_MODEL = WordSet(p.MODEL_WORDS)
_WEAK_AI = WordSet(p.WEAK_AI_WORDS)
_HIDDEN = WordSet(p.HIDDEN_QUALIFIERS)
_BARE_EN = WordSet(p.BARE_VERBS_EN)
_BARE_UKRU = WordSet(p.BARE_VERBS_UKRU)
_FILLERS = WordSet(p.BARE_FILLERS)
_BARE_RATING_EN = WordSet(p.BARE_RATING_EN)
_BARE_RATING_UKRU = WordSet(p.BARE_RATING_UKRU)
_NEURAL = WordSet(p.NEURAL_WORDS)
_NET = WordSet(p.NET_WORDS)
_COLOUR = WordSet(p.COLOUR_WORDS)
_COLOUR_OBJECT = WordSet(p.COLOUR_OBJECT_WORDS)
_COLOUR_GIVE = WordSet(p.COLOUR_GIVE_VERBS)
_CARD = WordSet(p.CARD_WORDS)
_AS = WordSet(p.AS_WORDS)
_DEEMED = WordSet(p.DEEMED_WORDS)
_RATING = WordSet(p.RATING_WORDS)
_ANCHORS = WordSet(
    p.IGNORE_VERBS
    + p.SYSTEM_WORDS
    + p.RATE_VERBS
    + p.DEEMED_WORDS
    + p.INSTRUCTION_WORDS
    + p.BARE_VERBS_EN
    + p.BARE_VERBS_UKRU
    + p.COLOUR_WORDS
)
_FIXED = tuple(fold(token) for token in p.FIXED_TOKENS)
_ROLES = tuple(fold(label) for label in p.ROLE_LABELS)
_TAGS = tuple(fold(tag) for tag in p.TAG_PREFIXES)

# A raw hit in view coordinates: start, end, class, kind ("instruction" or "rating" take part
# in the combination rule).
_Raw = tuple[int, int, Cls, str]


def _view(text: str) -> tuple[str, array[int] | None]:
    """The matching view and, when its length differs from ``text``, the source offsets."""
    if text.isascii():
        return fold(text), None
    cache: dict[str, str] = {}
    pieces: list[str] = []
    for char in text:
        piece = cache.get(char)
        if piece is None:
            piece = cache[char] = fold(char)
        pieces.append(piece)
    view = "".join(pieces)
    if len(view) == len(text):
        return view, None
    source: array[int] = array("i")
    for index, piece in enumerate(pieces):
        source.extend([index] * len(piece))
    return view, source


def matching_view(text: str) -> str:
    """The folded matching view of ``text`` (NFKC, skeleton, lower case)."""
    return _view(text)[0]


def _find_all(view: str, needle: str) -> list[int]:
    found: list[int] = []
    position = view.find(needle)
    while position != -1:
        found.append(position)
        position = view.find(needle, position + 1)
    return found


def _fixed(view: str, out: list[_Raw]) -> None:
    for token in _FIXED:
        out.extend((i, i + len(token), "high", "token") for i in _find_all(view, token))
    for i in _find_all(view, "<|"):
        body = _TOKEN_BODY.match(view, i + 2, i + 2 + MAX_TOKEN_CHARS + 2)
        if body is not None:
            out.append((i, body.end(), "high", "token"))


def _role_labels(view: str, out: list[_Raw]) -> None:
    for label in _ROLES:
        for i in _find_all(view, label):
            end = i + len(label)
            stop = min(len(view), end + p.ROLE_BLANKS + 1)
            while end < stop and view[end] in " \t":
                end += 1
            if end >= len(view) or view[end] != ":":
                continue
            back = i
            while back > 0 and i - back < p.ROLE_BLANKS and view[back - 1] in " \t":
                back -= 1
            if back == 0 or view[back - 1] == "\n":
                out.append((i, end + 1, "high", "token"))


def _tags(view: str, out: list[_Raw]) -> None:
    for tag in _TAGS:
        for i in _find_all(view, tag):
            end = i + len(tag)
            if end < len(view) and view[end] in " \t\n\r>/":
                out.append((i, end, "high", "token"))


def _placeholders(view: str, out: list[_Raw]) -> None:
    for i in _find_all(view, "["):
        body = _PLACEHOLDER.match(view, i + 1)
        if body is None:
            continue
        content = body.group()[:-1]
        letter_dot = (
            len(content) >= _PLACEHOLDER_MIN_LETTER_DOT
            and content[0].isalpha()
            and content[1] == "."
        )
        if "_" in content or letter_dot:
            out.append((i, body.end(), "heuristic", "placeholder"))


def _follow(view: str, start: int) -> list[tuple[str, int, int]]:
    """Up to ``FOLLOWWORDS`` words after ``start``, within ``WINDOW`` characters."""
    words: list[tuple[str, int, int]] = []
    for match in WORD.finditer(view, start, start + WINDOW):
        words.append((match.group(), match.start(), match.end()))
        if len(words) == FOLLOWWORDS:
            break
    return words


def _first(follow: list[tuple[str, int, int]], words: WordSet, limit: int) -> int | None:
    for index, (word, _, _) in enumerate(follow[:limit]):
        if word in words:
            return index
    return None


def _everything_above(follow: list[tuple[str, int, int]]) -> int | None:
    """End offset of "everything above" right after an ignore verb, else ``None``."""
    for index, (word, _, _) in enumerate(follow[:2]):
        if word in _ALL:
            for later, _, end in follow[index + 1 : index + 3]:
                if later in _ABOVE:
                    return end
    return None


Follow = list[tuple[str, int, int]]


def _strong_at(follow: Follow, index: int) -> int | None:
    """End offset of a strong AI word (or "language model") at ``follow[index]``."""
    if index >= len(follow):
        return None
    word = follow[index][0]
    if word in _STRONG_AI:
        return follow[index][2]
    pair = (word in _LANGUAGE and follow[index + 1 : index + 2]) or (
        word in _NEURAL and follow[index + 1 : index + 2]
    )
    if pair:
        second = pair[0][0]
        if (word in _LANGUAGE and second in _MODEL) or (word in _NEURAL and second in _NET):
            return pair[0][2]
    return None


def colour_rating(back: list[str], follow: Follow) -> bool:
    """A colour word near a quantifier, an object or a give verb; not "green card"."""
    if follow and follow[0][0] in _CARD:
        return False
    near = [*back[-3:], *(word for word, _, _ in follow[:3])]
    return any(word in _COLOUR_OBJECT or word in _COLOUR_GIVE for word in near)


def _ends_phrase(view: str, end: int) -> bool:
    """No word follows at ``end`` (only blanks, then punctuation, a line end or the end)."""
    position = end
    while position < len(view) and view[position] in " \t":
        position += 1
    return position >= len(view) or not view[position].isalnum()


def _addressed_to_ai(view: str, follow: Follow, hidden: bool) -> int | None:
    """End of "[linking words] for|to [articles] <AI word>" after an instruction word."""
    direct = _strong_at(follow, 0)
    if direct is not None:
        return direct
    index = 0
    while index < MAX_LINKS and index < len(follow) and follow[index][0] in _LINK:
        index += 1
    if index >= len(follow) or follow[index][0] not in _FOR:
        return None
    index += 1
    articles = 0
    while articles < MAX_LINKS and index < len(follow) and follow[index][0] in _THE:
        index += 1
        articles += 1
    strong = _strong_at(follow, index)
    if strong is not None:
        return strong
    if index < len(follow) and follow[index][0] in _WEAK_AI:
        end = follow[index][2]
        return end if hidden or _ends_phrase(view, end) else None
    return None


def _bare_rating(word: str, follow: Follow) -> int | None:
    """End of the rating word in "rate everything green": only linking words between."""
    if word in _BARE_EN:
        rating = _BARE_RATING_EN
    elif word in _BARE_UKRU:
        rating = _BARE_RATING_UKRU
    else:
        return None
    for found, _, end in follow[: MAX_BARE_FILLERS + 1]:
        if found in rating:
            return end
        if found not in _FILLERS:
            return None
    return None


def _instruction_rule(
    anchor: re.Match[str], back: list[str], follow: Follow, view: str
) -> _Raw | None:
    hidden = any(word in _HIDDEN for word in back[-2:])
    end = _addressed_to_ai(view, follow, hidden)
    if end is None and hidden:
        end = anchor.end()
    return None if end is None else (anchor.start(), end, "heuristic", "instruction")


def _ignore_rule(anchor: re.Match[str], follow: Follow) -> _Raw | None:
    target = _first(follow, _TARGETS, MAX_TARGET_DISTANCE)
    if target is not None:
        return (anchor.start(), follow[target][2], "heuristic", "instruction")
    above = _everything_above(follow)
    return None if above is None else (anchor.start(), above, "heuristic", "instruction")


def _rate_rule(anchor: re.Match[str], word: str, follow: Follow) -> _Raw | None:
    at = _first(follow, _AS, MAX_AS_DISTANCE)
    if at is not None and at + 1 < len(follow) and follow[at + 1][0] in _RATING:
        return (anchor.start(), follow[at + 1][2], "heuristic", "rating")
    bare = _bare_rating(word, follow)
    return None if bare is None else (anchor.start(), bare, "heuristic", "rating")


def _word_rules(view: str, out: list[_Raw]) -> None:
    back: list[str] = []
    for anchor in WORD.finditer(view):
        word = anchor.group()
        if word in _ANCHORS:
            follow = _follow(view, anchor.end())
            found: list[_Raw | None] = []
            if word in _INSTRUCTION:
                found.append(_instruction_rule(anchor, back, follow, view))
            if word in _IGNORE:
                found.append(_ignore_rule(anchor, follow))
            if word in _SYSTEM and follow and follow[0][0] in _PROMPT:
                found.append((anchor.start(), follow[0][2], "heuristic", "instruction"))
            if word in _RATE or word in _BARE_EN or word in _BARE_UKRU:
                found.append(_rate_rule(anchor, word, follow))
            if word in _COLOUR and colour_rating(back, follow):
                found.append((anchor.start(), anchor.end(), "heuristic", "rating"))
            if word in _DEEMED and follow and follow[0][0] in _RATING:
                found.append((anchor.start(), follow[0][2], "heuristic", "rating"))
            out.extend(item for item in found if item is not None)
        back = [*back[-2:], word]


def _combine(raw: list[_Raw]) -> list[_Raw]:
    """An instruction to an AI near a rating command: both become high class."""
    ratings = sorted(start for start, _, _, kind in raw if kind == "rating")
    if not ratings:
        return raw
    near: set[int] = set()
    for start, end, _, kind in raw:
        if kind != "instruction":
            continue
        low = bisect_left(ratings, start - p.COMBINE_DISTANCE)
        high = bisect_right(ratings, end + p.COMBINE_DISTANCE)
        if low < high:
            near.add(start)
            near.update(ratings[low:high])
    return [
        (s, e, "high" if kind in {"instruction", "rating"} and s in near else cls, kind)
        for s, e, cls, kind in raw
    ]


def scan(text: str) -> list[Hit]:
    """All Layer 2 hits of ``text``, sorted by start. Empty list: no hit."""
    view, source = _view(text)
    raw: list[_Raw] = []
    _fixed(view, raw)
    _role_labels(view, raw)
    _tags(view, raw)
    _placeholders(view, raw)
    _word_rules(view, raw)
    raw = _combine(raw)
    if len(raw) > p.MAX_HITS:
        # A cap never lowers the class: keep the high hits first.
        raw = sorted(raw, key=lambda item: item[2] != "high")[: p.MAX_HITS]
    hits: set[Hit] = set()
    for start, end, cls, _ in raw:
        if source is None:
            hits.add(Hit(cls, start, end))
        else:
            hits.add(Hit(cls, source[start], source[end - 1] + 1))
    for match in _BASE64.finditer(text):
        # A blob mixes many characters; a run of one repeated letter is not one.
        if len(set(match.group())) >= p.BASE64_MIN_DISTINCT:
            hits.add(Hit("heuristic", match.start(), match.end()))
            if len(hits) >= p.MAX_HITS:
                break
    return sorted(hits, key=lambda h: (h.start, h.end, h.cls))
