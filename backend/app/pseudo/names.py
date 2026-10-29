# ruff: noqa: RUF001, RUF002
"""Names of people and organisations (ADR 0008 point 1, ADR 0015 point 2).

Two passes over the NFKC view. Pass 1 finds names by structure: legal forms with quoted
names, sole traders, patronymics, surname with initials, names after "в особі" /
"represented by", names before a definition "(далі — …)", signature lines, quoted names with
an organisation context. It fills a hashed stem index: ``stem_key`` of the surname (or of
the words of an organisation name) -> group key. Pass 2 looks up every capitalised word and
every quote in that index, so a later case form ("Шевченком", "Шевченку") joins the entity of
the preamble name. Both passes are one scan with bounded look-around per word: linear time.
"""

from __future__ import annotations

import re
from array import array
from bisect import bisect_left
from typing import Final

from app.pseudo.hits import HIGH, NORMAL, ORG, PERSON, SIGNATURE, Hits
from app.pseudo.lexicon import (
    DEFINITION_FILLERS,
    DEFINITION_OPENERS,
    LEGAL_FORMS_LONG,
    LEGAL_PREFIX,
    LEGAL_SUFFIX,
    ORG_NOUNS,
    PERSON_LEADINS,
    PERSON_TRIGGERS,
    PERSON_VERBS,
    SOLE_TRADER,
    SOLE_TRADER_LEADS,
    SOLE_TRADER_NOUNS,
    is_not_name,
    is_obligation,
    is_patronymic,
    is_person_role,
    is_role,
    is_title,
    stem_key,
)
from app.pseudo.matching import View, fold

_WORD: Final = re.compile(r"[^\W\d_](?:[^\W\d_]|['’ʼ\-](?=[^\W\d_]))*")
_GAP: Final = re.compile(r"[\W\d_]+")
_SIGNATURE: Final = re.compile(r"_{3,}[ \t]{0,3}/")
_OPEN_QUOTES: Final = {"«": "»", "“": "”", "„": "“”", '"': '"'}
_MAX_QUOTE: Final = 80
_MAX_NAME_WORDS: Final = 4
_MAX_SIGNATURE_NAME: Final = 60
_MAX_RUN_WORDS: Final = 3
_ROLE_GAP: Final = frozenset(" \t:—–-,")
_ROLE_PUNCTUATION: Final = frozenset(":—–-,")
_MIN_ROLE_SURNAME: Final = 4
_LONG_FIRST: Final = tuple({form[0] for form in LEGAL_FORMS_LONG})
_LEADIN_LAST: Final = frozenset(key[-1] for key in PERSON_LEADINS)
_LEADIN_GAP: Final = frozenset(" :")
_MAX_LEADIN: Final = 4
_MAX_TITLE_WORDS: Final = 5
_MAX_BRACKET: Final = 60
_QUOTE_GAP: Final = frozenset(" :—–-")
_MAX_QUOTE_GAP: Final = 4
_MAX_STEM_SUFFIX: Final = 3
_SHORT_STEM: Final = 2


def _stem_of(word: str, stem: str) -> bool:
    """``word`` is ``stem`` with up to three more letters (one- and two-letter stems: equal)."""
    if len(stem) <= _SHORT_STEM:
        return word == stem
    return word.startswith(stem) and len(word) - len(stem) <= _MAX_STEM_SUFFIX


def words_of(text: str, start: int, end: int) -> tuple[array[int], array[int]]:
    starts: array[int] = array("i")
    ends: array[int] = array("i")
    position = start
    while position < end:
        matched = _WORD.match(text, position, end)
        if matched is not None:
            starts.append(position)
            ends.append(matched.end())
            position = matched.end()
        else:
            gap = _GAP.match(text, position, end)
            position = gap.end() if gap is not None else position + 1
    return starts, ends


class Names:
    def __init__(self, view: View, hits: Hits) -> None:
        self.view = view
        self.u = view.u
        self.s = view.s
        self.hits = hits
        self.covered = bytearray(len(view.u))
        self.surnames: dict[str, str] = {}
        # Second words of a two-word name whose order is unknown: found again, but not a surname.
        self.aliases: dict[str, str] = {}
        self.firsts: dict[str, set[str]] = {}
        self.org_phrase: dict[str, str] = {}
        self.org_first: dict[str, str] = {}
        self.org_multi: dict[str, list[tuple[tuple[str, ...], str]]] = {}
        self.org_single: dict[str, str] = {}
        self._fold: dict[str, str] = {}
        self._stem: dict[str, str] = {}
        self._name_word: dict[str, bool] = {}

    # ------------------------------------------------------------------ helpers

    def folded(self, word: str) -> str:
        found = self._fold.get(word)
        if found is None:
            if len(self._fold) > 100_000:  # noqa: PLR2004
                self._fold.clear()
            found = fold(word)
            self._fold[word] = found
        return found

    def stem(self, word: str) -> str:
        found = self._stem.get(word)
        if found is None:
            if len(self._stem) > 100_000:  # noqa: PLR2004
                self._stem.clear()
            found = stem_key(word)
            self._stem[word] = found
        return found

    def mark(self, start: int, end: int) -> None:
        self.covered[start:end] = b"\x01" * (end - start)

    def is_covered(self, start: int, end: int) -> bool:
        return any(self.covered[start:end])

    def name_word(self, word: str) -> bool:
        """A capitalised word that may be part of a name."""
        found = self._name_word.get(word)
        if found is None:
            if len(self._name_word) > 100_000:  # noqa: PLR2004
                self._name_word.clear()
            found = word[0].isupper() and len(word) >= 2 and not is_not_name(self.folded(word))  # noqa: PLR2004
            self._name_word[word] = found
        return found

    def adjacent(self, left_end: int, right_start: int) -> bool:
        gap = self.u[left_end:right_start]
        return bool(gap) and gap.isspace() and "\n" not in gap

    # ---------------------------------------------------------------- registration

    def add_person(self, start: int, end: int, surname: str | None, first: str | None) -> str:
        if surname is not None:
            key = self.stem(surname)
            canon = self.surnames.setdefault(key, key)
        else:
            canon = "fp:" + self.stem(first or "")
        if first is not None:
            self.firsts.setdefault(canon, set()).add(self.stem(first))
        self.hits.add(PERSON, NORMAL, start, end, canon)
        self.mark(start, end)
        return canon

    def add_org(self, start: int, end: int, name_words: list[str], precision: str) -> str:
        stems = tuple(self.stem(word) for word in name_words)
        phrase = " ".join(stems)
        canon = self.org_phrase.setdefault(phrase, phrase)
        parts = tuple(self.stem(part) for word in name_words for part in word.split("-") if part)
        if len(parts) > len(stems) and parts[0]:
            # A hyphenated name is also found with a space instead of the hyphen.
            self.org_multi.setdefault(parts[0], []).append((parts, canon))
        if stems:
            self.org_first.setdefault(stems[0], canon)
            if len(stems) == 1:
                self.org_single.setdefault(stems[0], canon)
            if len(stems) >= 2:  # noqa: PLR2004
                self.org_multi.setdefault(stems[0], []).append((stems, canon))
        self.hits.add(ORG, precision, start, end, canon)
        self.mark(start, end)
        return canon

    # --------------------------------------------------------------------- scan

    def pass_one(self) -> None:
        self._each_line(self._line_one)

    def pass_two(self) -> None:
        if self.surnames or self.org_phrase:
            self._each_line(self._line_two)

    def _each_line(self, handler: object) -> None:
        u = self.u
        size = len(u)
        position = 0
        while position <= size:
            newline = u.find("\n", position)
            end = size if newline < 0 else newline
            if end > position:
                handler(position, end)  # type: ignore[operator]
            position = end + 1

    # -------------------------------------------------------------------- pass 1

    def _line_one(self, ls: int, le: int) -> None:
        u = self.u
        ws, we = words_of(u, ls, le)
        count = len(ws)
        index = 0
        while index < count:
            word = u[ws[index] : we[index]]
            long_form = self._long_legal(ls, le, ws, we, index)
            if long_form:
                index = max(index + 1, long_form)
                continue
            if self._long_sole_trader(ws, we, index, word):
                done = self._sole_trader(ls, le, ws, we, index + 1, org_first=index)
                if done:
                    index = max(index + 1, done)
                    continue
            if word[0].isupper() and not self.is_covered(ws[index], we[index]):
                advance = self._word_rules(ls, le, ws, we, index, word)
                index = max(index + 1, advance)
            else:
                index += 1
        self._signatures(ls, le)
        self._quoted(ls, le, ws, we)
        self._definitions(ls, le, ws, we)

    def _word_rules(  # noqa: PLR0911, PLR0913, PLR0917
        self, ls: int, le: int, ws: array[int], we: array[int], index: int, word: str
    ) -> int:
        skeleton = self.s[ws[index] : we[index]]
        if skeleton in SOLE_TRADER:
            return self._sole_trader(ls, le, ws, we, index)
        if skeleton in LEGAL_PREFIX:
            done = self._legal_prefix(ls, le, ws, we, index)
            if done:
                return done
        if skeleton in LEGAL_SUFFIX:
            done = self._legal_suffix(le, ws, we, index)
            if done:
                return done
        if len(word) >= 2:  # noqa: PLR2004
            if is_patronymic(word):
                done = self._patronymic(ls, ws, we, index)
                if done:
                    return done
            if (
                self._trigger_before(ws, we, index)
                or self._role_before(ws, we, index)
                or self._leadin_before(ws, we, index)
            ) and self.name_word(word):
                return self._after_trigger(le, ws, we, index)
            if self.name_word(word):
                run = self._run(ws, we, index, _MAX_RUN_WORDS)
                done = (
                    self._bracket_form(le, ws, we, run)
                    or self._title_after_name(ls, le, ws, we, run)
                    or self._subject_before_verb(ls, ws, we, run)
                )
                if done:
                    return done
                return self._initials_name(ls, le, ws, we, index)
        return index + 1

    def _run(self, ws: array[int], we: array[int], index: int, limit: int) -> list[int]:
        """Indexes of consecutive capitalised name words from ``index``."""
        found: list[int] = []
        count = len(ws)
        while index < count and len(found) < limit:
            word = self.u[ws[index] : we[index]]
            if not self.name_word(word):
                break
            if found and not self.adjacent(we[found[-1]], ws[index]):
                break
            found.append(index)
            index += 1
        return found

    def _initials_after(self, position: int, limit: int) -> tuple[int, int]:
        """End and count of initials ("І.І.", "І. І.") after a space at ``position``."""
        u = self.u
        if position >= limit or not u[position].isspace() or u[position] == "\n":
            return position, 0
        cursor = position
        while cursor < limit and u[cursor] == " ":
            cursor += 1
        count = 0
        end = position
        while count < 2 and cursor + 1 < limit:  # noqa: PLR2004
            if not (u[cursor].isalpha() and u[cursor].isupper() and u[cursor + 1] == "."):
                break
            count += 1
            end = cursor + 2
            cursor = end
            while cursor < limit and u[cursor] == " " and cursor - end < 2:  # noqa: PLR2004
                cursor += 1
        if count and end < limit and u[end].isalpha():
            return position, 0
        return end, count

    def _initials_before(self, position: int, floor: int) -> tuple[int, int]:
        """Start and count of initials ending before the space before ``position``."""
        u = self.u
        cursor = position
        if cursor <= floor or u[cursor - 1] != " ":
            return position, 0
        while cursor > floor and u[cursor - 1] == " ":
            cursor -= 1
        count = 0
        start = position
        while count < 2 and cursor - 2 >= floor:  # noqa: PLR2004
            if not (
                u[cursor - 1] == "."
                and u[cursor - 2].isalpha()
                and u[cursor - 2].isupper()
                and (cursor - 3 < floor or not u[cursor - 3].isalpha())
            ):
                break
            count += 1
            start = cursor - 2
            cursor = start
            while cursor > floor and u[cursor - 1] == " " and start - cursor < 2:  # noqa: PLR2004
                cursor -= 1
        return start, count

    def _classify(
        self, words: list[str], has_initials: bool
    ) -> tuple[str | None, str | None, list[str]]:
        """``(surname, first name, other surname candidates)`` of a name."""
        if not words:
            return None, None, []
        if len(words) >= 2 and is_patronymic(words[-1]):  # noqa: PLR2004
            first = words[-2]
            surname = words[-3] if len(words) >= 3 else None  # noqa: PLR2004
            return surname, first, []
        if has_initials or len(words) == 1:
            return words[-1], None, []
        if all(word.isascii() for word in words):
            return words[-1], words[0], []
        return words[0], words[1], [words[1]]

    def _register_run(  # noqa: PLR0913, PLR0917
        self, ws: array[int], we: array[int], run: list[int], start: int, end: int, initials: bool
    ) -> None:
        words = [self.u[ws[k] : we[k]] for k in run]
        surname, first, extra = self._classify(words, initials)
        if surname is None and first is None:
            return
        canon = self.add_person(start, end, surname, first)
        for other in extra:
            self.aliases.setdefault(self.stem(other), canon)

    def _patronymic(self, ls: int, ws: array[int], we: array[int], index: int) -> int:
        u = self.u
        if index < 1 or not self.adjacent(we[index - 1], ws[index]):
            return 0
        if not self.name_word(u[ws[index - 1] : we[index - 1]]) or self.is_covered(
            ws[index - 1], we[index]
        ):
            return 0
        run = [index - 1, index]
        if (
            index >= 2  # noqa: PLR2004
            and self.adjacent(we[index - 2], ws[index - 1])
            and self.name_word(u[ws[index - 2] : we[index - 2]])
            and not self.is_covered(ws[index - 2], we[index - 2])
        ):
            run.insert(0, index - 2)
        self._register_run(ws, we, run, ws[run[0]], we[index], False)
        return index + 1

    def _title_gap(self, left_end: int, right_start: int) -> bool:
        """Spaces, or a full stop and spaces ("Mr. Smith")."""
        gap = self.u[left_end:right_start]
        return bool(gap) and (gap.isspace() or (gap[0] == "." and gap[1:].isspace()))

    def _trigger_before(self, ws: array[int], we: array[int], index: int) -> bool:
        u = self.u
        cursor = index - 1
        steps = 0
        while cursor >= 0 and steps < 6:  # noqa: PLR2004
            if not self._title_gap(we[cursor], ws[cursor + 1]):
                return False
            word = self.folded(u[ws[cursor] : we[cursor]])
            if (word,) in PERSON_TRIGGERS:
                return True
            if (
                cursor >= 1
                and self._title_gap(we[cursor - 1], ws[cursor])
                and (self.folded(u[ws[cursor - 1] : we[cursor - 1]]), word) in PERSON_TRIGGERS
            ):
                return True
            if not is_title(word):
                return False
            cursor -= 1
            steps += 1
        return False

    def _long_sole_trader(self, ws: array[int], we: array[int], index: int, word: str) -> bool:
        """``индивидуальный предприниматель`` / ``індивідуальний підприємець`` at ``index``."""
        if index + 1 >= len(ws) or self.is_covered(ws[index], we[index]):
            return False
        if not self.folded(word).startswith(SOLE_TRADER_LEADS):
            return False
        following = self.folded(self.u[ws[index + 1] : we[index + 1]])
        return following.startswith(SOLE_TRADER_NOUNS) and self.adjacent(we[index], ws[index + 1])

    def _role_before(self, ws: array[int], we: array[int], index: int) -> bool:  # noqa: PLR0911
        """A role of a person, then a colon, a dash or a comma, then this word: a name.

        Not for organisations (legal forms, organisation nouns) and not for a lone short
        word or a lone word in capitals.
        """
        u = self.u
        if index < 1:
            return False
        gap = u[we[index - 1] : ws[index]]
        previous = self.folded(u[ws[index - 1] : we[index - 1]])
        person_role = is_person_role(previous)
        # A job title ("Managing Director: ...") needs a full name; a lone word is not enough.
        title_only = not person_role and is_title(previous)
        if (
            not gap
            or not set(gap) <= _ROLE_GAP
            or not set(gap) & _ROLE_PUNCTUATION
            or not (person_role or title_only)
        ):
            return False
        skeleton = self.s[ws[index] : we[index]]
        if skeleton in LEGAL_PREFIX or skeleton in LEGAL_SUFFIX or skeleton in SOLE_TRADER:
            return False
        if self.folded(u[ws[index] : we[index]]) in ORG_NOUNS:
            return False
        names = 1
        cursor = index
        while (
            cursor + 1 < len(ws)
            and names <= _MAX_NAME_WORDS
            and self.adjacent(we[cursor], ws[cursor + 1])
            and self.name_word(u[ws[cursor + 1] : we[cursor + 1]])
        ):
            cursor += 1
            names += 1
            if self.s[ws[cursor] : we[cursor]] in LEGAL_SUFFIX | LEGAL_PREFIX:
                return False
        if names > 1:
            return True
        if title_only:
            return False
        word = u[ws[index] : we[index]]
        if word.isupper():
            return self._comma_given(len(u), ws, we, index) is not None
        return len(word) >= _MIN_ROLE_SURNAME

    def _after_trigger(self, le: int, ws: array[int], we: array[int], index: int) -> int:
        run = self._run(ws, we, index, _MAX_NAME_WORDS)
        if not run:
            return index + 1
        last = run[-1]
        if last + 1 < len(ws) and self.s[ws[last + 1] : we[last + 1]] in LEGAL_SUFFIX:
            return index + 1
        if self.s[ws[run[0]] : we[run[0]]] in LEGAL_PREFIX:
            return index + 1
        end, count = self._initials_after(we[last], le)
        end = end if count else we[last]
        if not count and len(run) == 1:
            given = self._comma_given(le, ws, we, last)
            if given is not None:
                self.add_person(
                    ws[run[0]],
                    we[given],
                    self.u[ws[run[0]] : we[run[0]]],
                    self.u[ws[given] : we[given]],
                )
                return given + 1
        self._register_run(ws, we, run, ws[run[0]], end, count > 0)
        return last + 1

    def _comma_given(self, le: int, ws: array[int], we: array[int], last: int) -> int | None:
        """``DOE, JANE``: the index of the given name after "Surname, ", or ``None``."""
        u = self.u
        nxt = last + 1
        if nxt >= len(ws) or u[we[last] : ws[nxt]] != ", " or ws[nxt] >= le:
            return None
        word = u[ws[nxt] : we[nxt]]
        if not self.name_word(word) or self.s[ws[nxt] : we[nxt]] in LEGAL_PREFIX | LEGAL_SUFFIX:
            return None
        if self.is_covered(ws[nxt], we[nxt]):
            return None
        after = nxt + 1
        if (
            after < len(ws)
            and self.adjacent(we[nxt], ws[after])
            and self.name_word(u[ws[after] : we[after]])
        ):
            # "DOE, JANE MARIE": a given name of up to two words, all in capitals.
            given = u[ws[nxt] : we[nxt]].isupper() and u[ws[after] : we[after]].isupper()
            further = after + 1
            more = (
                further < len(ws)
                and self.adjacent(we[after], ws[further])
                and self.name_word(u[ws[further] : we[further]])
            )
            return after if given and not more else None  # not "Surname, Given"
        return nxt

    def _initials_name(self, ls: int, le: int, ws: array[int], we: array[int], index: int) -> int:
        end, count = self._initials_after(we[index], le)
        if count == 2:  # noqa: PLR2004
            word = self.u[ws[index] : we[index]]
            self.add_person(ws[index], end, word, None)
            return index + 1
        start, count = self._initials_before(ws[index], ls)
        if count == 2:  # noqa: PLR2004
            word = self.u[ws[index] : we[index]]
            self.add_person(start, we[index], word, None)
        return index + 1

    # --------------------------------------------------------- organisations

    def _quote_end(self, position: int, le: int) -> int:
        """Index of the closing quote of the quote opened at ``position``, or -1."""
        closers = _OPEN_QUOTES.get(self.u[position], "")
        limit = min(le, position + _MAX_QUOTE + 1)
        cursor = position + 1
        while cursor < limit:
            if self.u[cursor] in closers:
                return cursor
            cursor += 1
        return -1

    def _inner_words(self, start: int, end: int) -> list[str]:
        ws, we = words_of(self.u, start, end)
        return [self.u[a:b] for a, b in zip(ws, we, strict=True)]

    def _legal_prefix(  # noqa: PLR0913, PLR0917
        self,
        ls: int,
        le: int,
        ws: array[int],
        we: array[int],
        index: int,
        start: int | None = None,
    ) -> int:
        u = self.u
        first = ws[index] if start is None else start
        cursor = we[index]
        if cursor < le and u[cursor] == ".":
            cursor += 1
        gap = cursor
        while cursor < le and u[cursor] == " " and cursor - gap < 2:  # noqa: PLR2004
            cursor += 1
        if cursor < le and u[cursor] in _OPEN_QUOTES:
            close = self._quote_end(cursor, le)
            if close < 0:
                return 0
            inner = self._inner_words(cursor + 1, close)
            if not inner:
                return 0
            self.add_org(first, close + 1, inner, HIGH)
            return bisect_left(ws, close + 1)
        run_start = bisect_left(ws, cursor)
        if cursor == we[index] or run_start >= len(ws) or ws[run_start] != cursor:
            return 0
        run = self._run(ws, we, run_start, _MAX_NAME_WORDS)
        if not run:
            return 0
        names = [u[ws[k] : we[k]] for k in run]
        self.add_org(first, we[run[-1]], names, NORMAL)
        return run[-1] + 1

    def _long_legal(self, ls: int, le: int, ws: array[int], we: array[int], index: int) -> int:
        """A legal form in full words ("Общество с ограниченной ответственностью") and a name."""
        if self.is_covered(ws[index], we[index]):
            return 0
        first = self.folded(self.u[ws[index] : we[index]])
        if not first.startswith(_LONG_FIRST):
            return 0
        for form in LEGAL_FORMS_LONG:
            last = index + len(form) - 1
            if last >= len(ws) or not _stem_of(first, form[0]):
                continue
            if all(
                _stem_of(self.folded(self.u[ws[index + k] : we[index + k]]), stem)
                and (k == 0 or self.adjacent(we[index + k - 1], ws[index + k]))
                for k, stem in enumerate(form)
            ):
                return self._legal_prefix(ls, le, ws, we, last, ws[index])
        return 0

    def _leadin_before(self, ws: array[int], we: array[int], index: int) -> bool:
        """ "Notices to: Name" / "Questions go to Name" / "Attention: Name"."""
        u = self.u
        if index < 1:
            return False
        gap = u[we[index - 1] : ws[index]]
        if not gap or not set(gap) <= _LEADIN_GAP:
            return False
        if self.folded(u[ws[index - 1] : we[index - 1]]) not in _LEADIN_LAST:
            return False
        parts: list[str] = []
        cursor = index - 1
        while cursor >= 0 and len(parts) < _MAX_LEADIN:
            if parts and u[we[cursor] : ws[cursor + 1]].strip(" "):
                break
            parts.insert(0, self.folded(u[ws[cursor] : we[cursor]]))
            if tuple(parts) in PERSON_LEADINS:
                return True
            cursor -= 1
        return False

    def _title_after_name(
        self, ls: int, le: int, ws: array[int], we: array[int], run: list[int]
    ) -> int:
        """ "Daniel Marlow, Chief Executive Officer" / "J. Thornberry, Finance Director"."""
        if not run:
            return 0
        last = run[-1]
        start, count = self._initials_before(ws[run[0]], ls)
        if (len(run) < 2 and not count) or not self._job_title_follows(le, ws, we, last):  # noqa: PLR2004
            return 0
        if self.s[ws[last] : we[last]] in LEGAL_SUFFIX or self.s[ws[run[0]] : we[run[0]]] in (
            LEGAL_PREFIX
        ):
            return 0
        self._register_run(ws, we, run, start if count else ws[run[0]], we[last], count > 0)
        return last + 1

    def _job_title_follows(self, le: int, ws: array[int], we: array[int], last: int) -> bool:
        """ ", " and then a capitalised job title (a title or person-role word within five)."""
        u = self.u
        nxt = last + 1
        if nxt >= len(ws) or ws[nxt] >= le or u[we[last] : ws[nxt]] != ", ":
            return False
        for step in range(_MAX_TITLE_WORDS):
            current = nxt + step
            if current >= len(ws) or ws[current] >= le:
                return False
            word = u[ws[current] : we[current]]
            if step == 0 and not word[0].isupper():
                return False
            folded = self.folded(word)
            if is_title(folded) or is_person_role(folded):
                return True
            if current + 1 < len(ws) and not self.adjacent(we[current], ws[current + 1]):
                return False
        return False

    def _subject_before_verb(self, ls: int, ws: array[int], we: array[int], run: list[int]) -> int:
        """ "Tobias Wren signs ..." at the start of a sentence: a full name and an action verb."""
        u = self.u
        if len(run) < 2:  # noqa: PLR2004
            return 0
        before = ws[run[0]]
        while before > ls and u[before - 1] == " ":
            before -= 1
        if before > ls and u[before - 1] not in ".!?":
            return 0
        last = run[-1]
        nxt = last + 1
        if nxt >= len(ws) or not self.adjacent(we[last], ws[nxt]):
            return 0
        verb = u[ws[nxt] : we[nxt]]
        if verb != verb.lower() or self.folded(verb) not in PERSON_VERBS:
            return 0
        self._register_run(ws, we, run, ws[run[0]], we[last], False)
        return last + 1

    def _bracket_form(self, le: int, ws: array[int], we: array[int], run: list[int]) -> int:
        """ "Iryna Kovalenko (Ірина Коваленко)": one person in two scripts."""
        u = self.u
        if len(run) < 2 or u[we[run[-1]] : we[run[-1]] + 2] != " (":  # noqa: PLR2004
            return 0
        if not all(u[ws[k] : we[k]].isascii() for k in run):
            return 0
        last = run[-1]
        opening = we[last] + 2
        close = u.find(")", opening, min(le, opening + _MAX_BRACKET))
        if close < 0:
            return 0
        cws, cwe = words_of(u, opening, close)
        words = [u[a:b] for a, b in zip(cws, cwe, strict=True)]
        if (
            not 2 <= len(words) <= _MAX_RUN_WORDS  # noqa: PLR2004
            or cws[0] != opening
            or cwe[-1] != close
            or not all(w[0].isupper() and len(w) >= 2 and not w.isascii() for w in words)  # noqa: PLR2004
        ):
            return 0
        latin = [u[ws[k] : we[k]] for k in run]
        wanted = self._loose(latin[-1])
        match = next((w for w in words if self._loose(w) == wanted), None)
        if match is None:
            return 0
        surname, first, _ = self._classify(latin, False)
        canon = self.add_person(ws[run[0]], we[last], surname, first)
        self.surnames.setdefault(self.stem(match), canon)
        given = next((w for w in words if w is not match), None)
        self.add_person(cws[0], cwe[-1], match, given)
        return bisect_left(ws, close + 1)

    def _loose(self, word: str) -> str:
        """Stem key without "h" and "g": Hnatyuk and Гнатюк, Smith and Сміт meet."""
        return self.stem(word).replace("h", "").replace("g", "")

    def _legal_suffix(self, le: int, ws: array[int], we: array[int], index: int) -> int:
        u = self.u
        run: list[int] = []
        cursor = index - 1
        while cursor >= 0 and len(run) < _MAX_NAME_WORDS:
            word = u[ws[cursor] : we[cursor]]
            if not (word.isascii() and self.name_word(word)):
                break
            if not self.adjacent(we[cursor], ws[cursor + 1]):
                break
            run.insert(0, cursor)
            cursor -= 1
        if not run or self.is_covered(ws[run[0]], we[index]):
            return 0
        end = we[index]
        if end < le and u[end] == ".":
            end += 1
        names = [u[ws[k] : we[k]] for k in run]
        self.add_org(ws[run[0]], end, names, NORMAL)
        return index + 1

    def _sole_trader(  # noqa: PLR0913, PLR0917
        self,
        ls: int,
        le: int,
        ws: array[int],
        we: array[int],
        index: int,
        org_first: int | None = None,
    ) -> int:
        if index + 1 >= len(ws) or not self.adjacent(we[index], ws[index + 1]):
            return 0
        run = self._run(ws, we, index + 1, _MAX_RUN_WORDS)
        if not run:
            return 0
        end, count = self._initials_after(we[run[-1]], le)
        end = end if count else we[run[-1]]
        words = [self.u[ws[k] : we[k]] for k in run]
        surname, first, extra = self._classify(words, count > 0)
        person_start = ws[run[0]]
        if surname is None:
            return 0
        canon = self.add_person(person_start, end, surname, first)
        for other in extra:
            self.aliases.setdefault(self.stem(other), canon)
        org_start = ws[index if org_first is None else org_first]
        self.hits.add(ORG, NORMAL, org_start, end, "fop:" + canon)
        return run[-1] + 1

    def _quoted(self, ls: int, le: int, ws: array[int], we: array[int]) -> None:
        """Quoted names without a legal form, found by their context."""
        u = self.u
        for opener in "«“„":
            position = u.find(opener, ls, le)
            while position != -1:
                self._one_quote(le, ws, we, position)
                position = u.find(opener, position + 1, le)

    def _one_quote(self, le: int, ws: array[int], we: array[int], position: int) -> None:
        u = self.u
        close = self._quote_end(position, le)
        if close < 0 or self.is_covered(position, close + 1):
            return
        start, end = position + 1, close
        while start < end and u[start] == " ":
            start += 1
        while end > start and u[end - 1] == " ":
            end -= 1
        if start >= end or not (u[start].isupper() or u[start].isdigit()):
            return
        inner = self._inner_words(start, end)
        if not inner or len(inner) > 6 or all(is_role(self.folded(w)) for w in inner):  # noqa: PLR2004
            return
        if not self._org_context(le, ws, we, position, close):
            return
        self.add_org(start, end, inner, NORMAL)

    def _org_context(
        self, le: int, ws: array[int], we: array[int], open_at: int, close: int
    ) -> bool:
        u = self.u
        # The word before the quote.
        before = bisect_left(we, open_at) - 1
        if before >= 0 and self._noun_colon_quote(we[before], open_at, u[ws[before] : we[before]]):
            return True
        if before >= 0 and self.adjacent(we[before], open_at):
            word = u[ws[before] : we[before]]
            folded = self.folded(word)
            if (
                (word.isupper() and len(word) >= 2)  # noqa: PLR2004
                or folded in ORG_NOUNS
                or is_role(folded)
            ):
                return True
        # A definition after the quote: «Name» (далі — …).
        cursor = close + 1
        while cursor < le and u[cursor] == " ":
            cursor += 1
        if cursor < le and u[cursor] == "(":
            first = bisect_left(ws, cursor + 1)
            if first < len(ws) and (self.folded(u[ws[first] : we[first]]),) in DEFINITION_OPENERS:
                return True
        return False

    def _noun_colon_quote(self, left_end: int, open_at: int, word: str) -> bool:
        """``Банк: «Name»``: an organisation noun, a colon or dash, then the quote."""
        gap = self.u[left_end:open_at]
        return (
            0 < len(gap) <= _MAX_QUOTE_GAP
            and set(gap) <= _QUOTE_GAP
            and gap.strip(" ") != ""
            and self.folded(word) in ORG_NOUNS
        )

    # ------------------------------------------------------------ definitions

    def _definition_term(self, le: int, position: int) -> tuple[int, int] | None:
        """Span of the term of a definition opened by the "(" at ``position``, or ``None``."""
        u = self.u
        ws, we = words_of(u, position + 1, min(le, position + 1 + 60))
        index = 0
        if index >= len(ws) or (self.folded(u[ws[0] : we[0]]),) not in DEFINITION_OPENERS:
            return None
        index = 1
        while index < len(ws) and self.folded(u[ws[index] : we[index]]) in DEFINITION_FILLERS:
            index += 1
        cursor = we[index - 1]
        while cursor < le and u[cursor] in " —–-:":
            cursor += 1
        quoted = cursor < le and u[cursor] in _OPEN_QUOTES
        if quoted:
            close = self._quote_end(cursor, le)
            if close < 0:
                return None
            return cursor + 1, close
        close = u.find(")", cursor, min(le, cursor + 60))
        if close < 0:
            return None
        return cursor, close

    def _definitions(self, ls: int, le: int, ws: array[int], we: array[int]) -> None:
        """A name run just before "(далі — …)" / "(the …)" is a party name."""
        u = self.u
        position = u.find("(", ls, le)
        while position != -1:
            self._definition_name(ls, ws, we, position)
            position = u.find("(", position + 1, le)

    def _definition_name(self, ls: int, ws: array[int], we: array[int], position: int) -> None:
        u = self.u
        first = bisect_left(ws, position + 1)
        if first >= len(ws) or (self.folded(u[ws[first] : we[first]]),) not in DEFINITION_OPENERS:
            return
        cursor = position
        while cursor > ls and u[cursor - 1] == " ":
            cursor -= 1
        last = bisect_left(we, cursor)
        if last >= len(we) or we[last] != cursor or u[cursor - 1] in "»”\"'":
            return
        if self.s[ws[last] : we[last]] in LEGAL_SUFFIX:
            return
        run: list[int] = []
        index = last
        while index >= 0 and len(run) < _MAX_NAME_WORDS:
            word = u[ws[index] : we[index]]
            if not self.name_word(word) or self.is_covered(ws[index], we[index]):
                break
            if run and not self.adjacent(we[index], ws[run[0]]):
                break
            run.insert(0, index)
            index -= 1
        if len(run) < 2:  # noqa: PLR2004
            return
        self._register_run(ws, we, run, ws[run[0]], we[last], False)

    # -------------------------------------------------------------- signatures

    def _signatures(self, ls: int, le: int) -> None:
        u = self.u
        position = u.find("___", ls, le)
        while position != -1:
            if position > ls and u[position - 1] == "_":
                position = u.find("___", position + 1, le)
                continue
            matched = _SIGNATURE.match(u, position, le)
            if matched is None:
                end = position
                while end < le and u[end] == "_":
                    end += 1
                position = u.find("___", end, le)
                continue
            inner_start = matched.end()
            limit = min(le, inner_start + _MAX_SIGNATURE_NAME)
            at = bisect_left(self.view.breaks, inner_start)
            if at < len(self.view.breaks) and self.view.breaks[at] < limit:
                limit = self.view.breaks[at]  # a signature line ends at its line break
            close = u.find("/", inner_start, limit)
            if close > inner_start:
                self._signature_name(position, inner_start, close)
                position = u.find("___", close + 1, le)
            else:
                position = u.find("___", matched.end(), le)

    def _signature_name(self, start: int, inner_start: int, close: int) -> None:
        u = self.u
        first = inner_start
        last = close
        while first < last and u[first] == " ":
            first += 1
        while last > first and u[last - 1] == " ":
            last -= 1
        ws, we = words_of(u, first, last)
        stop = next(
            (k for k in range(len(ws)) if is_obligation(self.folded(u[ws[k] : we[k]]))), None
        )
        hit_end = close + 1
        if stop is not None:
            # The line goes on with an obligation: the signature ends before it.
            if stop == 0:
                return
            last = ws[stop]
            while last > first and u[last - 1] == " ":
                last -= 1
            hit_end = last
            ws, we = ws[:stop], we[:stop]
        capital = [k for k in range(len(ws)) if u[ws[k]].isupper()]
        if not capital or any(ch.isdigit() for ch in u[first:last]):
            return
        key = "".join(c for c in fold(u[first:last]) if c.isalnum())
        self.hits.add(SIGNATURE, NORMAL, start, hit_end, key)
        self.mark(start, hit_end)
        long_words = [
            u[ws[k] : we[k]]
            for k in range(len(ws))
            if we[k] - ws[k] >= 2 and u[ws[k]].isupper()  # noqa: PLR2004
        ]
        has_initials = any(
            we[k] - ws[k] == 1 and we[k] < last and u[we[k]] == "." for k in range(len(ws))
        )
        surname, first_name, extra = self._classify(long_words, has_initials)
        if surname is None:
            return
        canon = self.add_person(first, last, surname, first_name)
        for other in extra:
            self.aliases.setdefault(self.stem(other), canon)

    # -------------------------------------------------------------------- pass 2

    def _line_two(self, ls: int, le: int) -> None:
        u = self.u
        ws, we = words_of(u, ls, le)
        count = len(ws)
        index = 0
        while index < count:
            word = u[ws[index] : we[index]]
            if word[0].isupper() and len(word) >= 2 and not self.is_covered(ws[index], we[index]):  # noqa: PLR2004
                index = max(index + 1, self._known_word(ls, le, ws, we, index, word))
            else:
                index += 1
        self._known_quotes(ls, le, ws, we)

    def _known_word(  # noqa: PLR0913, PLR0917
        self, ls: int, le: int, ws: array[int], we: array[int], index: int, word: str
    ) -> int:
        if is_not_name(self.folded(word)):
            return index + 1
        key = self.stem(word)
        canon = self.surnames.get(key) or self.aliases.get(key)
        if canon is not None:
            return self._known_person(ls, le, ws, we, index, canon)
        candidates = self.org_multi.get(key)
        if candidates:
            done = self._known_org(ws, we, index, candidates)
            if done > index + 1:
                return done
        single = self.org_single.get(key)
        if single is not None:
            self.hits.add(ORG, NORMAL, ws[index], we[index], single)
            self.mark(ws[index], we[index])
        return index + 1

    def _known_person(  # noqa: PLR0913, PLR0917
        self, ls: int, le: int, ws: array[int], we: array[int], index: int, canon: str
    ) -> int:
        u = self.u
        start, end = ws[index], we[index]
        firsts = self.firsts.get(canon, set())
        # To the left: a known first name, else initials.
        if (
            index >= 1
            and self.adjacent(we[index - 1], ws[index])
            and not self.is_covered(ws[index - 1], we[index - 1])
            and self.stem(u[ws[index - 1] : we[index - 1]]) in firsts
            and u[ws[index - 1]].isupper()
        ):
            start = ws[index - 1]
        else:
            initial_start, count = self._initials_before(ws[index], ls)
            if count:
                start = initial_start
        # To the right: initials, else a known first name and a patronymic.
        initial_end, count = self._initials_after(we[index], le)
        last = index
        if count:
            end = initial_end
        elif (
            index + 1 < len(ws)
            and self.adjacent(we[index], ws[index + 1])
            and u[ws[index + 1]].isupper()
            and self.stem(u[ws[index + 1] : we[index + 1]]) in firsts
            and not self.is_covered(ws[index + 1], we[index + 1])
        ):
            end = we[index + 1]
            last = index + 1
            if (
                index + 2 < len(ws)
                and self.adjacent(we[index + 1], ws[index + 2])
                and is_patronymic(u[ws[index + 2] : we[index + 2]])
            ):
                end = we[index + 2]
                last = index + 2
        self.hits.add(PERSON, NORMAL, start, end, canon)
        self.mark(start, end)
        return last + 1

    def _known_org(
        self,
        ws: array[int],
        we: array[int],
        index: int,
        candidates: list[tuple[tuple[str, ...], str]],
    ) -> int:
        u = self.u
        for stems, canon in candidates:
            last = index + len(stems) - 1
            if last >= len(ws):
                continue
            ok = True
            for offset, wanted in enumerate(stems):
                current = index + offset
                word = u[ws[current] : we[current]]
                if not word[0].isupper() or self.stem(word) != wanted:
                    ok = False
                    break
                if offset and not self.adjacent(we[current - 1], ws[current]):
                    ok = False
                    break
            if ok:
                self.hits.add(ORG, NORMAL, ws[index], we[last], canon)
                self.mark(ws[index], we[last])
                return last + 1
        return index + 1

    def _known_quotes(self, ls: int, le: int, ws: array[int], we: array[int]) -> None:
        u = self.u
        for opener in "«“„":
            position = u.find(opener, ls, le)
            while position != -1:
                self._known_quote(le, position)
                position = u.find(opener, position + 1, le)
        position = u.find("(", ls, le)
        while position != -1:
            term = self._definition_term(le, position)
            if term is not None and not self.is_covered(*term):
                self._known_term(term[0], term[1])
            position = u.find("(", position + 1, le)

    def _known_quote(self, le: int, position: int) -> None:
        close = self._quote_end(position, le)
        if close < 0:
            return
        start, end = position + 1, close
        if self.is_covered(start, end):
            return
        self._known_term(start, end, quoted=True)

    def _known_term(self, start: int, end: int, *, quoted: bool = False) -> None:
        u = self.u
        while start < end and u[start] == " ":
            start += 1
        while end > start and u[end - 1] in " .,":
            end -= 1
        if start >= end or self.is_covered(start, end):
            return
        words = self._inner_words(start, end)
        if not words or not words[0][0].isupper() or any(is_role(self.folded(w)) for w in words):
            return
        stems = [self.stem(w) for w in words]
        phrase = " ".join(stems)
        canon = self.org_phrase.get(phrase)
        if canon is not None:
            self.hits.add(ORG, NORMAL, start, end, canon)
            self.mark(start, end)
            return
        if len(words) == 1:
            person = self.surnames.get(stems[0]) or self.aliases.get(stems[0])
            if person is not None:
                self.hits.add(PERSON, NORMAL, start, end, person)
                self.mark(start, end)
                return
            first = self.org_first.get(stems[0])
            if first is not None:
                self.hits.add(ORG, NORMAL, start, end, first)
                self.mark(start, end)
