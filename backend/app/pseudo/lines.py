# ruff: noqa: RUF001
"""Line rules over the lower-case skeleton: codes with context, documents, addresses.

The matching view is cut into lines. A line is cut into runs (maximal letters and digits).
Keywords (``lexicon.CONTEXT_KINDS``) are remembered by run index; a code needs a keyword of
its kind within five runs, or the requisites section. Amounts never match a code rule.
Every rule is a bounded look-ahead from one run; the work per run is constant, so a line is
processed in linear time.
"""

from __future__ import annotations

import re
from array import array
from bisect import bisect_left
from collections.abc import Callable
from typing import Final

from app.pseudo import checksums
from app.pseudo.hits import (
    ACCOUNT,
    ADDRESS,
    DOC_NO,
    HEALTH,
    HIGH,
    NORMAL,
    PERSONAL_DOC,
    PHONE,
    SIGNATURE,
    TAX_ID,
    VEHICLE,
    Hits,
)
from app.pseudo.lexicon import (
    ABBREVIATIONS,
    ADDRESS_STARTS,
    AMOUNT_WORDS,
    CONTEXT_KINDS,
    DEFINITION_OPENERS,
    is_document_word,
)
from app.pseudo.matching import View, fold
from app.pseudo.tables import CURRENCY_SIGNS, IBAN_LENGTHS

_RUN: Final = re.compile(r"[^\W_]+")
_GAP: Final = re.compile(r"[\W_]+")
_DOC_VALUE: Final = re.compile(r"[^\W_](?:[^\W_]|[/\-.](?=[^\W_])){0,39}")
_PLATE_UA: Final = re.compile(r"[abcehkmoptxyавекмнопстух]{2}[0-9]{4}[abcehkmoptxyавекмнопстух]{2}")
_PLATE_RU: Final = re.compile(
    r"[abcehkmoptxyавекмнопстух][0-9]{3}[abcehkmoptxyавекмнопстух]{2}(?:[0-9]{2,3})?"
)
_PLATE_LETTERS: Final = frozenset("abcehkmoptxyавекмнопстух")
_HEX: Final = frozenset("0123456789abcdef")
_FILL_PASSPORT: Final = frozenset(
    fold(word)
    for word in (
        "серія",
        "серії",
        "серия",
        "серии",
        "series",
        "ser",
        "no",
        "номер",
        "number",
        "n",
        "nr",
    )
)
_FILL_NUMBER: Final = frozenset(
    fold(word) for word in ("no", "номер", "number", "n", "nr", "серія", "серия", "series")
)
_MULTI_LAST: Final = frozenset(key[-1] for key in CONTEXT_KINDS if len(key) > 1)
_STOP_KINDS: Final = frozenset({"phone", "email", "tax", "iban", "account", "swift", "mfo", "bik"})
_ADDRESS_STOP: Final = frozenset(
    key[0] for key, kinds in CONTEXT_KINDS.items() if len(key) == 1 and kinds & _STOP_KINDS
)
_OPENER_WORDS: Final = frozenset(key[0] for key in DEFINITION_OPENERS)
_MAX_ADDRESS: Final = 300
_MAX_HEALTH: Final = 80
_TAX_DISTANCE: Final = 5
_UA_SUBSTITUTE: Final = str.maketrans({"O": "0", "L": "1", "I": "1"})
_CARD_GROUP: Final = 4
_MIN_CARD: Final = 16
_MAX_CARD: Final = 19
_SERIAL_MIN: Final = 12
_SERIAL_MAX: Final = 64
_VIN: Final = 17
_MIN_IBAN_RUN: Final = 4
_SWIFT_SHORT: Final = 8
_SWIFT_LONG: Final = 11
_VAT_MIN: Final = 10
_VAT_MAX: Final = 14
_PHONE_LOCAL: Final = 10
_DAY_MAX: Final = 31
_MONTH_MAX: Final = 12


def runs_of(text: str, start: int, end: int) -> tuple[array[int], array[int]]:
    """Starts and ends of the letter/digit runs of ``text[start:end]``."""
    starts: array[int] = array("i")
    ends: array[int] = array("i")
    position = start
    while position < end:
        matched = _RUN.match(text, position, end)
        if matched is not None:
            starts.append(position)
            ends.append(matched.end())
            position = matched.end()
        else:
            gap = _GAP.match(text, position, end)
            position = gap.end() if gap is not None else position + 1
    return starts, ends


def scan_lines(view: View, hits: Hits, in_requisites: Callable[[int], bool]) -> None:
    low = view.low
    size = len(low)
    position = 0
    while position <= size:
        newline = low.find("\n", position)
        end = size if newline < 0 else newline
        if end > position:
            _Line(view, hits, in_requisites, position, end).run()
        position = end + 1


class _Line:
    def __init__(
        self,
        view: View,
        hits: Hits,
        in_requisites: Callable[[int], bool],
        start: int,
        end: int,
    ) -> None:
        self.low = view.low
        self.hits = hits
        self.in_requisites = in_requisites
        self.ls = start
        self.le = end
        self.st, self.en = runs_of(self.low, start, end)
        self.n = len(self.st)
        self.last: dict[str, int] = {}
        self.skip_to = -1

    # ------------------------------------------------------------------ helpers

    def text(self, index: int) -> str:
        return self.low[self.st[index] : self.en[index]]

    def gap(self, index: int) -> str:
        """Characters between run ``index`` and the next run."""
        if index + 1 >= self.n:
            return self.low[self.en[index] : self.le]
        return self.low[self.en[index] : self.st[index + 1]]

    def near(self, kind: str, index: int, distance: int = _TAX_DISTANCE) -> bool:
        seen = self.last.get(kind)
        return seen is not None and 0 < index - seen <= distance

    def context(self, kind: str, index: int) -> bool:
        return self.near(kind, index) or self.in_requisites(self.st[index])

    def is_amount(self, first: int, last: int) -> bool:
        """The runs ``first..last`` are next to a currency, a unit or a percent sign."""
        low = self.low
        after = low[self.en[last] : self.en[last] + 3].lstrip()
        if after and after[0] in CURRENCY_SIGNS:
            return True
        following = last + 1
        if following < self.n and len(self.gap(last)) <= 2:  # noqa: PLR2004
            word = self.text(following)
            if word in AMOUNT_WORDS:
                return True
            if word.isdigit() and len(word) == 3 and self.gap(last) == " ":  # noqa: PLR2004
                return True
        start = self.st[first]
        before = low[max(self.ls, start - 3) : start].rstrip()
        if before and before[-1] in CURRENCY_SIGNS:
            return True
        previous = first - 1
        return (
            previous >= 0
            and len(self.gap(previous)) <= 2  # noqa: PLR2004
            and self.text(previous) in AMOUNT_WORDS
        )

    def joined(self, index: int) -> bool:
        """The run is part of a longer number (``21.5``, ``1/2``, ``12-3``)."""
        low = self.low
        start, end = self.st[index], self.en[index]
        if start - 2 >= self.ls and low[start - 1] in ".,/-" and low[start - 2].isalnum():
            return True
        return end + 1 < self.le and low[end] in ".,/-" and low[end + 1].isalnum()

    # --------------------------------------------------------------------- main

    def run(self) -> None:
        index = 0
        low = self.low
        while index < self.n:
            word = low[self.st[index] : self.en[index]]
            self._keywords(index, word)
            if index > self.skip_to:
                if word.isdigit():
                    index = self._number(index, word)
                    continue
                self._word(index, word)
            index += 1

    def _keywords(self, index: int, word: str) -> None:
        kinds = CONTEXT_KINDS.get((word,))
        if kinds:
            self._mark(kinds, index)
        if word in _MULTI_LAST and index >= 1:
            second = CONTEXT_KINDS.get((self.text(index - 1), word))
            if second:
                self._mark(second, index)
            if index >= 2:  # noqa: PLR2004
                third = CONTEXT_KINDS.get((self.text(index - 2), self.text(index - 1), word))
                if third:
                    self._mark(third, index)

    def _mark(self, kinds: frozenset[str], index: int) -> None:
        for kind in kinds:
            self.last[kind] = index
            if kind in _LABELS and index > self.skip_to:
                _LABELS[kind](self, index)

    # ------------------------------------------------------------------ numbers

    def _number(self, index: int, word: str) -> int:
        length = len(word)
        # Multi-run structures first.
        consumed = self._structured(index, word, length)
        if consumed:
            return consumed
        if self.joined(index) or self.is_amount(index, index):
            return index + 1
        self._code(index, word, length)
        return index + 1

    def _structured(self, index: int, word: str, length: int) -> int:  # noqa: PLR0911
        n = self.n
        if length == 10 and index + 3 < n and self._lens(index, (10, 2, 3, 4), ":"):  # noqa: PLR2004
            return self._add_range(ADDRESS, NORMAL, index, index + 3)
        if length == 8 and index + 1 < n and self.gap(index) == "-" and self._lens(index, (8, 5)):  # noqa: PLR2004
            if self.near("unzr", index):
                return self._add_range(TAX_ID, NORMAL, index, index + 1)
            return 0
        if length == 3 and index + 3 < n and self._lens(index, (3, 3, 3, 2)):  # noqa: PLR2004
            return self._snils(index)
        if length == 2 and index + 2 < n and self._lens(index, (2, 2, 4), "."):  # noqa: PLR2004
            if self.near("dob", index, 8):
                return self._add_range(PERSONAL_DOC, NORMAL, index, index + 2)
            return index + 3
        if length == 2 and index + 1 < n and self.gap(index) == "-" and self._lens(index, (2, 7)):  # noqa: PLR2004
            if self.near("ein", index, 4):
                return self._add_range(TAX_ID, NORMAL, index, index + 1)
            return 0
        if length == _CARD_GROUP and index + 3 < n and self._lens(index, (4, 4, 4, 4), " -"):
            return self._card(index, index + 3)
        return 0

    def _lens(self, index: int, lengths: tuple[int, ...], seps: str = " -") -> bool:
        for offset, length in enumerate(lengths):
            current = index + offset
            word = self.text(current)
            if len(word) != length or not word.isdigit():
                return False
            if offset < len(lengths) - 1:
                gap = self.gap(current)
                if gap == "" or any(char not in seps for char in gap) or len(gap) > 2:  # noqa: PLR2004
                    return False
        return True

    def _add_range(self, cls: str, precision: str, first: int, last: int) -> int:
        start, end = self.st[first], self.en[last]
        key = "".join(c for c in self.low[start:end] if c.isalnum())
        self.hits.add(cls, precision, start, end, key)
        return last + 1

    def _snils(self, index: int) -> int:
        digits = "".join(self.text(index + k) for k in range(4))
        if not self.near("snils", index) and not self.in_requisites(self.st[index]):
            return 0
        precision = HIGH if checksums.snils_valid(digits) else NORMAL
        start, end = self.st[index], self.en[index + 3]
        self.hits.add(TAX_ID, precision, start, end, digits)
        return index + 4

    def _card(self, first: int, last: int) -> int:
        digits = "".join(self.text(k) for k in range(first, last + 1))
        if self.is_amount(first, last):
            return last + 1
        luhn = checksums.luhn_valid(digits)
        near = self.near("card", first)
        if luhn or near:
            self.hits.add(
                ACCOUNT,
                HIGH if luhn and near else NORMAL,
                self.st[first],
                self.en[last],
                digits,
            )
        return last + 1

    def _code(self, index: int, word: str, length: int) -> None:  # noqa: PLR0912
        start, end = self.st[index], self.en[index]
        add = self.hits.add
        if length == 8:  # noqa: PLR2004
            if checksums.edrpou_valid(word):
                add(TAX_ID, HIGH if self.context("tax", index) else NORMAL, start, end, word)
            elif self.near("tax", index):
                add(TAX_ID, NORMAL, start, end, word)
        elif length == _PHONE_LOCAL:
            valid = checksums.rnokpp_valid(word) or checksums.inn10_valid(word)
            if word[0] == "0" and not valid:
                add(PHONE, HIGH if self.near("phone", index) else NORMAL, start, end, word[-9:])
            elif valid:
                add(TAX_ID, HIGH if self.context("tax", index) else NORMAL, start, end, word)
            elif self.near("tax", index):
                add(TAX_ID, NORMAL, start, end, word)
        elif length in (12, 13, 15):
            valid = {
                12: checksums.inn12_valid,
                13: checksums.ogrn_valid,
                15: checksums.ogrnip_valid,
            }[length](word)
            if valid:
                add(TAX_ID, HIGH if self.context("tax", index) else NORMAL, start, end, word)
            elif self.near("tax", index):
                add(TAX_ID, NORMAL, start, end, word)
        elif length == 9:  # noqa: PLR2004
            if self.near("kpp", index, 3):
                add(TAX_ID, NORMAL, start, end, word)
            elif self.near("bik", index, 3):
                add(ACCOUNT, NORMAL, start, end, word)
        elif (length == 6 and self.near("mfo", index, 3)) or (  # noqa: PLR2004
            length == 20 and (self.near("account", index, 6) or self.near("bik", index, 6))  # noqa: PLR2004
        ):
            add(ACCOUNT, NORMAL, start, end, word)
        if _MIN_CARD <= length <= _MAX_CARD:
            self._card(index, index)

    # -------------------------------------------------------------------- words

    def _word(self, index: int, word: str) -> None:
        if word == "no" or (word.startswith("no") and word[2:3].isdigit()):
            self._doc_no(index, word)
            return
        if word == "n" and self.low[self.en[index] : self.en[index] + 1] in ("°", "º"):
            self._doc_no(index, word)
            return
        length = len(word)
        if (
            length >= _MIN_IBAN_RUN
            and word[:2].isalpha()
            and word[2:4].isdigit()
            and self._iban(index, word)
        ):
            return
        if (
            length == _VIN
            and word.isalnum()
            and not word.isdigit()
            and not word.isalpha()
            and not set(word) & set("ioq")
        ):
            self._add(VEHICLE, NORMAL, index, index, word)
            return
        self._plate(index, word, length)
        if (
            length in (_SWIFT_SHORT, _SWIFT_LONG)
            and word[:6].isalpha()
            and self.near("swift", index, 2)
        ):
            self._add(ACCOUNT, NORMAL, index, index, word)
        elif (
            _VAT_MIN <= length <= _VAT_MAX
            and word[:2].isalpha()
            and word[2:].isalnum()
            and self.near("vat", index, 3)
        ):
            self._add(TAX_ID, NORMAL, index, index, word)

    def _add(self, cls: str, precision: str, first: int, last: int, key: str) -> None:
        self.hits.add(cls, precision, self.st[first], self.en[last], key)

    def _plate(self, index: int, word: str, length: int) -> None:
        if length == 8 and _PLATE_UA.fullmatch(word):  # noqa: PLR2004
            self._add(VEHICLE, NORMAL, index, index, word)
            return
        if length == 2 and word[0] in _PLATE_LETTERS and word[1] in _PLATE_LETTERS:  # noqa: PLR2004
            second = index + 1
            third = index + 2
            if (
                third < self.n
                and self.gap(index) == " "
                and self.gap(second) == " "
                and len(self.text(second)) == 4  # noqa: PLR2004
                and self.text(second).isdigit()
                and len(self.text(third)) == 2  # noqa: PLR2004
                and set(self.text(third)) <= _PLATE_LETTERS
            ):
                self._add(
                    VEHICLE, NORMAL, index, third, word + self.text(second) + self.text(third)
                )
                self.skip_to = third
            return
        if length >= 6 and _PLATE_RU.fullmatch(word):  # noqa: PLR2004
            if length == 6:  # noqa: PLR2004
                following = index + 1
                if (
                    following < self.n
                    and self.gap(index) in ("", " ")
                    and self.text(following).isdigit()
                    and len(self.text(following)) in (2, 3)
                ):
                    self._add(VEHICLE, NORMAL, index, following, word + self.text(following))
                    self.skip_to = following
                return
            self._add(VEHICLE, NORMAL, index, index, word)

    def _iban(self, index: int, word: str) -> bool:
        country = word[:2].upper()
        expected = IBAN_LENGTHS.get(country)
        if expected is None or len(word) > expected:
            return False
        compact = word
        last = index
        while len(compact) < expected and last + 1 < self.n and self.gap(last) == " ":
            following = self.text(last + 1)
            if len(compact) + len(following) > expected or not following.isalnum():
                break
            compact += following
            last += 1
        if len(compact) != expected:
            return False
        upper = compact.upper()
        valid = checksums.iban_valid(upper)
        if not valid and country == "UA":
            substituted = upper[:4] + upper[4:].translate(_UA_SUBSTITUTE)
            if checksums.iban_valid(substituted):
                upper, valid = substituted, True
        if valid:
            self._add(ACCOUNT, HIGH, index, last, upper)
        elif self.near("iban", index, 3):
            self._add(ACCOUNT, NORMAL, index, last, upper)
        else:
            return False
        self.skip_to = last
        return True

    # ---------------------------------------------------------- document number

    def _doc_no(self, index: int, word: str) -> None:
        if not any(
            is_document_word(self.text(previous)) for previous in range(max(0, index - 3), index)
        ):
            return
        low = self.low
        if len(word) > 2:  # noqa: PLR2004 - "no45": the numero sign glued to the number
            position = self.st[index] + 2
        else:
            position = self.en[index] + (1 if word == "n" else 0)
        limit = position + 4
        while position < self.le and position < limit and low[position] in " .:":
            position += 1
        matched = _DOC_VALUE.match(low, position, self.le)
        if matched is None:
            return
        end = matched.end()
        value = low[position:end]
        if not any(char.isdigit() for char in value):
            # A series of letters, a space and the number: "AB 7654321".
            following = bisect_left(self.st, end + 1)
            if (
                not value.isalpha()
                or len(value) > 3  # noqa: PLR2004
                or low[end : end + 1] != " "
                or following >= self.n
                or self.st[following] != end + 1
                or not self.text(following).isdigit()
            ):
                return
            end = self.en[following]
            value = low[position:end]
        key = "".join(char for char in value if char.isalnum())
        self.hits.add(DOC_NO, NORMAL, position, end, key)

    # ------------------------------------------------------------------ labels

    def _passport(self, index: int) -> None:
        self._series_number(index, _FILL_PASSPORT, PERSONAL_DOC, (6, 9), True)

    def _idcard(self, index: int) -> None:
        self._series_number(index, _FILL_NUMBER, PERSONAL_DOC, (9, 9), False)

    def _driver(self, index: int) -> None:
        self._series_number(index, _FILL_NUMBER, PERSONAL_DOC, (6, 8), True)

    def _regcert(self, index: int) -> None:
        if self._series_number(index, _FILL_NUMBER, VEHICLE, (6, 8), True):
            return
        first = index + 1
        if (
            first + 2 < self.n
            and len(self.text(first)) == 2  # noqa: PLR2004
            and self.text(first).isdigit()
            and len(self.text(first + 1)) == 2  # noqa: PLR2004
            and self.text(first + 1).isalpha()
            and len(self.text(first + 2)) == 6  # noqa: PLR2004
            and self.text(first + 2).isdigit()
        ):
            self._add_range(VEHICLE, NORMAL, first, first + 2)
            self.skip_to = first + 2

    def _series_number(
        self,
        index: int,
        fillers: frozenset[str],
        cls: str,
        lengths: tuple[int, int],
        with_series: bool,
    ) -> bool:
        series: int | None = None
        position = index + 1
        limit = min(self.n, index + 6)
        while position < limit:
            word = self.text(position)
            if word in fillers:
                position += 1
                continue
            if (
                with_series
                and series is None
                and (
                    (word.isalpha() and 2 <= len(word) <= 3)  # noqa: PLR2004
                    or (word.isdigit() and len(word) == 4)  # noqa: PLR2004
                )
            ):
                series = position
                position += 1
                continue
            if word.isdigit() and lengths[0] <= len(word) <= lengths[1]:
                first = series if series is not None else position
                self._add_range(cls, NORMAL, first, position)
                self.skip_to = position
                return True
            return False
        return False

    def _address(self, index: int) -> None:
        low = self.low
        start = -1
        position = self.en[index]
        look = index
        for _ in range(3):
            following = look + 1
            gap_end = self.st[following] if following < self.n else self.le
            gap = low[position:gap_end]
            if ":" in gap:
                start = position + gap.index(":") + 1
                break
            if following >= self.n or gap.strip(" ") or not self.text(following).isalpha():
                break
            position = self.en[following]
            look = following
        if start < 0:
            following = index + 1
            if (
                following < self.n
                and self.text(following) in ADDRESS_STARTS
                and low[self.en[following] : self.en[following] + 1] == "."
            ):
                start = self.st[following]
            else:
                return
        while start < self.le and low[start] == " ":
            start += 1
        end = self._address_end(start)
        while end > start and low[end - 1] in " ,:":
            end -= 1
        if end - start < 3 or not any(c.isalnum() for c in low[start:end]):  # noqa: PLR2004
            return
        key = "".join(c for c in low[start:end] if c.isalnum())
        self.hits.add(ADDRESS, NORMAL, start, end, key)
        self.skip_to = max(self.skip_to, bisect_left(self.st, end) - 1)

    def _address_end(self, start: int) -> int:
        limit = min(self.le, start + _MAX_ADDRESS)
        for index in range(start, limit):
            if self._address_stops_at(index, start):
                return index
        return limit

    def _address_stops_at(self, index: int, start: int) -> bool:
        low = self.low
        char = low[index]
        if char == ";":
            return True
        if char == ".":
            return self._sentence_ends_at(index, start)
        if char in ",(":
            word_start = index + (2 if char == "," and low[index + 1 : index + 2] == " " else 1)
            if char == "," and low[index + 1 : index + 2] != " ":
                return False
            word_end = word_start
            while word_end < self.le and low[word_end].isalnum():
                word_end += 1
            word = low[word_start:word_end]
            return word in (_ADDRESS_STOP if char == "," else _OPENER_WORDS)
        return False

    def _sentence_ends_at(self, index: int, start: int) -> bool:
        low = self.low
        if index + 1 >= self.le:
            return True
        if low[index + 1] != " ":
            return False
        word_start = index
        while word_start > start and low[word_start - 1].isalnum():
            word_start -= 1
        word = low[word_start:index]
        if word in ABBREVIATIONS or len(word) <= 1:
            return False
        after = index + 1
        while after < self.le and low[after] == " ":
            after += 1
        return after >= self.le or not low[after].islower()

    def _health(self, index: int) -> None:
        low = self.low
        position = self.en[index]
        while position < self.le and low[position] in " :—-":
            position += 1
        limit = min(self.le, position + _MAX_HEALTH)
        end = position
        while end < limit:
            char = low[end]
            if char in ",;)" or (char == "." and (end + 1 >= self.le or low[end + 1] == " ")):
                break
            end += 1
        while end > position and low[end - 1] == " ":
            end -= 1
        if sum(1 for c in low[position:end] if c.isalpha()) < 3:  # noqa: PLR2004
            return
        self.hits.add(
            HEALTH, NORMAL, position, end, "".join(c for c in low[position:end] if c.isalnum())
        )
        self.skip_to = max(self.skip_to, bisect_left(self.st, end) - 1)

    def _serial(self, index: int) -> None:
        following = index + 1
        if following >= self.n:
            return
        word = self.text(following)
        if (
            _SERIAL_MIN <= len(word) <= _SERIAL_MAX
            and set(word) <= _HEX
            and any(c.isdigit() for c in word)
        ):
            self._add(SIGNATURE, NORMAL, following, following, word)
            self.skip_to = following


_LABELS: Final[dict[str, Callable[[_Line, int], None]]] = {
    "passport": _Line._passport,
    "idcard": _Line._idcard,
    "driver": _Line._driver,
    "regcert": _Line._regcert,
    "address": _Line._address,
    "health": _Line._health,
    "serial": _Line._serial,
}
