"""Contact rules over the whole view: emails, URLs, domains, handles, phones.

Every scan is anchored (``find`` on a fixed anchor, bounded walks left and right) or uses
``match`` at one position with bounded repetition, so the time is linear in the text.
"""

from __future__ import annotations

import re
from typing import Final

from app.pseudo.hits import EMAIL, HIGH, NORMAL, PHONE, URL, Hits
from app.pseudo.lexicon import TLDS

_LOCAL: Final = frozenset("abcdefghijklmnopqrstuvwxyz0123456789._%+-'")
_DOMAIN: Final = frozenset("abcdefghijklmnopqrstuvwxyz0123456789.-")
_HANDLE: Final = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")
_MAX_LOCAL: Final = 64
_MAX_DOMAIN: Final = 255
_MAX_URL: Final = 2048
_AT_ANCHORS: Final = ("@", "(at)", "[at]", "{at}", "(@)")
_SCHEMES: Final = frozenset({"http", "https", "ftp", "ftps"})
_URL_STOP: Final = frozenset('<>"\u00ab\u00bb\n\t \u00a0')
_URL_TRAIL: Final = ".,;:!?)]}'"
_MIN_HANDLE: Final = 4
_MAX_HANDLE: Final = 32
_MIN_LABELS_TLD: Final = 2
_PLUS_PHONE: Final = re.compile(r"\+[0-9(][0-9 ()\-.]{5,24}")
_PAREN_PHONE: Final = re.compile(r"\([0-9]{3,5}\)[ \-]?[0-9]{2,4}(?:[ \-]?[0-9]{2,4}){1,2}")
_MIN_PHONE_DIGITS: Final = 9
_MAX_PHONE_DIGITS: Final = 15
_MAX_PAREN_DIGITS: Final = 12
_ISD_LENGTHS: Final = (("380", 12), ("7", 11), ("1", 11))


def scan_all(low: str, hits: Hits) -> None:
    _emails(low, hits)
    _urls(low, hits)
    _domains(low, hits)
    _phones(low, hits)


def _valid_host(host: str) -> bool:
    """A dotted host name: no empty label, no label edge hyphen, alphabetic last label."""
    if ".." in host or host.startswith((".", "-")) or ".-" in host or "-." in host:
        return False
    head, dot, tail = host.rpartition(".")
    return bool(dot and head) and tail.isalpha() and len(tail) >= _MIN_LABELS_TLD


def _emails(low: str, hits: Hits) -> None:
    size = len(low)
    for anchor in _AT_ANCHORS:
        width = len(anchor)
        position = low.find(anchor)
        while position != -1:
            begin = position
            while begin > 0 and position - begin < _MAX_LOCAL and low[begin - 1] in _LOCAL:
                begin -= 1
            while begin < position and low[begin] in ".-'+%":
                begin += 1
            right = position + width
            end = right
            while end < size and end - right < _MAX_DOMAIN and low[end] in _DOMAIN:
                end += 1
            while end > right and low[end - 1] in ".-":
                end -= 1
            if begin < position and _valid_host(low[right:end]):
                hits.add(EMAIL, HIGH, begin, end, low[begin:position] + "@" + low[right:end])
            elif anchor == "@" and begin == position:
                _handle(low, position, hits)
            position = low.find(anchor, position + 1)


def _handle(low: str, position: int, hits: Hits) -> None:
    end = position + 1
    size = len(low)
    while end < size and end - position <= _MAX_HANDLE and low[end] in _HANDLE:
        end += 1
    if end - position - 1 < _MIN_HANDLE or (end < size and low[end].isalnum()):
        return
    hits.add(URL, NORMAL, position, end, low[position:end])


def _urls(low: str, hits: Hits) -> None:
    size = len(low)
    position = low.find("://")
    while position != -1:
        begin = position
        while begin > 0 and position - begin < 6 and low[begin - 1].isalpha():  # noqa: PLR2004
            begin -= 1
        if low[begin:position] in _SCHEMES:
            end = _url_end(low, position + 3, size)
            if end > position + 3 and low[position + 3].isalnum():
                key = low[position + 3 : end].removeprefix("www.").rstrip("/")
                hits.add(URL, HIGH, begin, end, key)
        position = low.find("://", position + 3)
    position = low.find("www.")
    while position != -1:
        previous = low[position - 1] if position else " "
        if not (previous.isalnum() or previous in "./-@:_"):
            end = _url_end(low, position, size)
            host = low[position:end]
            for stop in "/?#:":
                host = host.partition(stop)[0]
            if _valid_host(host) and len(host) > len("www.a.bc") - 1:
                key = low[position + 4 : end].rstrip("/")
                hits.add(URL, HIGH, position, end, key)
        position = low.find("www.", position + 4)


def _url_end(low: str, start: int, size: int) -> int:
    end = start
    while end < size and end - start < _MAX_URL and low[end] not in _URL_STOP:
        end += 1
    while end > start and low[end - 1] in _URL_TRAIL:
        end -= 1
    return end


def _domains(low: str, hits: Hits) -> None:
    """Bare domains: maximal runs of ``[a-z0-9.-]`` with a known top-level domain."""
    size = len(low)
    position = low.find(".")
    done = 0
    while position != -1:
        if position < done:
            position = low.find(".", done)
            continue
        begin = position
        while begin > done and low[begin - 1] in _DOMAIN:
            begin -= 1
        end = position
        while end < size and low[end] in _DOMAIN:
            end += 1
        done = end
        position = low.find(".", end)
        _bare_domain(low, begin, end, hits)


def _bare_domain(low: str, begin: int, end: int, hits: Hits) -> None:
    while begin < end and not low[begin].isalnum():
        begin += 1
    while end > begin and low[end - 1] in ".-":
        end -= 1
    if end - begin > _MAX_DOMAIN or end - begin < len("a.bc"):
        return
    before = low[max(0, begin - 4) : begin]
    if before.endswith(("@", "(at)", "[at]", "{at}", "(@)")) or (
        end < len(low) and low[end] == "@"
    ):
        return
    if (end < len(low) and low[end] in "(_") or before.endswith(("/", "_")):
        return
    host = low[begin:end]
    if not _valid_host(host) or host.rpartition(".")[2] not in TLDS:
        return
    hits.add(URL, HIGH, begin, end, host.removeprefix("www."))


def _phones(low: str, hits: Hits) -> None:
    position = low.find("+")
    while position != -1:
        _intl_phone(low, position, hits)
        position = low.find("+", position + 1)
    position = low.find("(")
    while position != -1:
        _paren_phone(low, position, hits)
        position = low.find("(", position + 1)


def _digit_count(text: str) -> int:
    return sum(1 for char in text if char.isdigit())


def _intl_phone(low: str, position: int, hits: Hits) -> None:
    previous = low[position - 1] if position else " "
    if previous.isalnum() or not (position + 1 < len(low) and low[position + 1] in "0123456789("):
        return
    matched = _PLUS_PHONE.match(low, position)
    if matched is None:
        return
    text = matched.group()
    limit = _MAX_PHONE_DIGITS
    digits_only = "".join(c for c in text[1:12] if c.isdigit())
    for prefix, length in _ISD_LENGTHS:
        if digits_only.startswith(prefix):
            limit = length
            break
    count = 0
    cut = len(text)
    for index, char in enumerate(text):
        if char.isdigit():
            count += 1
            if count == limit:
                cut = index + 1
                break
    text = text[:cut]
    while text and not (text[-1].isdigit() or text[-1] == ")"):
        text = text[:-1]
    count = _digit_count(text)
    end = position + len(text)
    if count < _MIN_PHONE_DIGITS or (end < len(low) and low[end].isalnum()):
        return
    hits.add(PHONE, HIGH, position, end, "".join(c for c in text if c.isdigit())[-9:])


def _paren_phone(low: str, position: int, hits: Hits) -> None:
    previous = low[position - 1] if position else " "
    if previous.isalnum():
        return
    matched = _PAREN_PHONE.match(low, position)
    if matched is None:
        return
    start = position
    # An optional trunk prefix: "8 (495)", "0 (44)".
    back = position
    if back > 0 and low[back - 1] in " -":
        back -= 1
    if back > 0 and low[back - 1] in "078" and (back < 2 or not low[back - 2].isalnum()):  # noqa: PLR2004
        start = back - 1
    text = low[start : matched.end()]
    count = _digit_count(text)
    end = matched.end()
    if not _MIN_PHONE_DIGITS <= count <= _MAX_PAREN_DIGITS or (
        end < len(low) and low[end].isalnum()
    ):
        return
    hits.add(PHONE, HIGH, start, end, "".join(c for c in text if c.isdigit())[-9:])
