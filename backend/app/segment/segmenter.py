"""The segmenter: blocks in, clauses out (ADR 0014; threat model T5, T6).

``segment`` is pure and deterministic. It cleans the input (``app.textclean``), then
assigns every non-white-space character of the cleaned body and non-body blocks to
exactly one clause, and returns the cleaned blocks once with ``spans`` into them.
Nothing is rewritten, truncated or dropped; every cap fails closed.

Unit of work: a *line* (a stripped, non-empty line of a block). Linear time: one pass
over the lines for numbering and running-line detection, one pass for the clauses;
running lines are found by hashing (a dict keyed by the line text). Patterns are in
``app.segment.patterns``.

Rules (ADR 0014 points 5 to 8, tech lead decisions of S5-T1):

- Non-body blocks (footnote, endnote, header, footer, textbox): one clause per block.
- Body: text before the first clause start is the ``preamble``; a start (decimal,
  article word, paragraph sign, Roman) or a heading line begins a clause; other lines
  continue it. A numbered title (short, no final punctuation) is a heading and starts
  its own clause; sub-clauses carry the nearest heading. An unnumbered all-capitals line
  is a heading once a start was seen, before that only if a clause text follows it. A
  line of the closed requisites list is a heading; its clause has ``section_kind``
  ``requisites``.
- Running lines: exact repeats among the first or last two lines of at least three and
  at least half of the pages, up to 120 characters, never a start or a heading, become
  one ``running`` clause (spans at every occurrence, placed at the first one).
- Without any numbered start, every body block is one clause and the result warns
  ``no_numbering_found``.
- Warnings: ``numbering_gap``, ``numbering_restart``, ``duplicate_number``.
- A clause above ``max_clause_chars`` is split at line boundaries, then at sentence
  ends, into parts with the same number and increasing ``part_index``.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Final

from app.extraction.model import Block
from app.extraction.normalize import normalize_line_breaks
from app.segment import patterns
from app.segment.model import (
    CLAUSE_TOO_LONG,
    NO_TEXT_EXTRACTED,
    TOO_MANY_CLAUSES,
    Clause,
    ClausePart,
    InputBlock,
    SegmentResult,
    SegmentWarning,
    Span,
)
from app.textclean import TextCleaner

__all__ = ["InputBlock", "SegmentError", "SegmentLimits", "SegmentResult", "segment"]

MIN_RUNNING_PAGES: Final = 3
RUNNING_LINES_PER_EDGE: Final = 2
_SENTENCE_END: Final = ".!?…"
_MARKER_CHARS: Final = 12
_MARKER_SET: Final = frozenset("0123456789.)IVXivx§")
_BODY: Final = "body"
_REQUISITES: Final = "requisites"


class SegmentError(Exception):
    """Segmentation failed. ``code`` is a fixed error code; the message holds no input."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SegmentLimits:
    max_clauses: int
    max_clause_chars: int


def _lines(text: str, begin: int = 0) -> Iterator[tuple[int, int]]:
    """``(start, end)`` of every non-empty line of ``text`` from ``begin``, without outer
    white space."""
    position = begin
    size = len(text)
    while position <= size:
        newline = text.find("\n", position)
        end = size if newline < 0 else newline
        if end > position:
            raw = text[position:end]
            stripped = raw.strip()
            if stripped:
                start = position + len(raw) - len(raw.lstrip())
                yield start, start + len(stripped)
        position = end + 1


def _is_marker(text: str, start: int, end: int) -> bool:
    """Is ``text[start:end]`` a clause number such as ``1.2`` or ``IV`` (no sentence)?"""
    return end - start <= _MARKER_CHARS and all(char in _MARKER_SET for char in text[start:end])


def _sentences(text: str, start: int, end: int) -> Iterator[tuple[int, int]]:
    """Cut ``text[start:end]`` after sentence-ending marks that are followed by white space."""
    piece = start
    index = start
    while index < end:
        if (
            text[index] in _SENTENCE_END
            and (index + 1 == end or text[index + 1].isspace())
            and not _is_marker(text, piece, index)
        ):
            yield piece, index + 1
            index += 1
            while index < end and text[index].isspace():
                index += 1
            piece = index
        else:
            index += 1
    if piece < end:
        yield piece, end


class _Entry:
    """One clause (logical): its metadata and the parts it was split into."""

    __slots__ = (
        "done",
        "first_id",
        "heading_span",
        "last_block",
        "last_tick",
        "length",
        "level",
        "number",
        "pages",
        "part",
        "section_kind",
        "spans",
    )

    def __init__(
        self,
        part: ClausePart,
        number: str | None,
        level: int,
        section_kind: str | None,
        heading_span: Span | None,
    ) -> None:
        self.part: ClausePart = part
        self.number = number
        self.level = level
        self.section_kind = section_kind
        self.heading_span = heading_span
        self.done: list[tuple[list[list[int]], list[int]]] = []
        self.spans: list[list[int]] = []
        self.pages: set[int] = set()
        self.length = 0
        self.last_block = -1
        self.last_tick = -2
        self.first_id = ""

    def flush(self) -> None:
        if self.spans:
            self.done.append((self.spans, sorted(self.pages)))
            self.spans = []
            self.pages = set()
            self.length = 0


class _Builder:
    """Collects the lines of the clauses and enforces the clause caps."""

    def __init__(self, limits: SegmentLimits) -> None:
        self.limits = limits
        self.entries: list[_Entry] = []
        self.parts = 0
        self.tick = 0

    def add(  # noqa: PLR0913, PLR0917 - one call per line, positions are plain ints
        self, entry: _Entry, block: int, text: str, start: int, end: int, page: int | None
    ) -> None:
        cap = self.limits.max_clause_chars
        if end - start <= cap:
            self._unit(entry, block, start, end, page)
            return
        for piece_start, piece_end in _sentences(text, start, end):
            if piece_end - piece_start > cap:
                raise SegmentError(CLAUSE_TOO_LONG)
            self._unit(entry, block, piece_start, piece_end, page)

    def _unit(self, entry: _Entry, block: int, start: int, end: int, page: int | None) -> None:
        # Adjacent units of one block that no other clause separates form one span.
        merge = entry.last_block == block and entry.last_tick == self.tick - 1
        size = end - start
        if entry.spans:
            length = entry.length + (end - entry.spans[-1][2] if merge else 1 + size)
            if length > self.limits.max_clause_chars:
                entry.flush()
        if entry.spans:
            if merge:
                entry.spans[-1][2] = end
            else:
                entry.spans.append([block, start, end])
            entry.length = length
        else:
            self.parts += 1
            if self.parts > self.limits.max_clauses:
                raise SegmentError(TOO_MANY_CLAUSES)
            entry.spans.append([block, start, end])
            entry.length = size
        if page is not None:
            entry.pages.add(page)
        entry.last_block = block
        entry.last_tick = self.tick
        self.tick += 1


class _Numbering:
    """Checks the sequence of clause numbers; one tracker per style (Arabic, Roman)."""

    def __init__(self) -> None:
        self.previous: dict[str, tuple[int, ...]] = {}

    def reset(self) -> None:
        self.previous = {}

    def check(self, style: str, parts: tuple[int, ...]) -> str | None:
        previous = self.previous.get(style)
        self.previous[style] = parts
        if previous is None:
            return None
        if parts == previous:
            return "duplicate_number"
        if self._follows(previous, parts):
            return None
        return "numbering_restart" if parts[-1] == 1 else "numbering_gap"

    @staticmethod
    def _follows(previous: tuple[int, ...], parts: tuple[int, ...]) -> bool:
        """Next sibling, first child, or the next number of an ancestor (then 1s below)."""
        for common in range(len(previous) + 1):
            if parts[:common] != previous[:common]:
                break
            if common == len(previous):
                if len(parts) > common and all(p == 1 for p in parts[common:]):
                    return True
            elif (
                len(parts) > common
                and parts[common] == previous[common] + 1
                and all(p == 1 for p in parts[common + 1 :])
            ):
                return True
        return False


def _clean(blocks: Sequence[InputBlock]) -> tuple[list[Block], TextCleaner]:
    cleaner = TextCleaner()
    cleaned = [
        Block(text=cleaner.clean(normalize_line_breaks(b.text)), part=b.part, page=b.page)
        for b in blocks
    ]
    return cleaned, cleaner


def _running_positions(blocks: Sequence[Block]) -> set[tuple[int, int]]:
    """Positions ``(block, start)`` of the running lines, found by hashing the line text."""
    first: dict[int, list[tuple[int, int, int]]] = {}
    last: dict[int, deque[tuple[int, int, int]]] = {}
    for index, block in enumerate(blocks):
        if block.part != _BODY or block.page is None:
            continue
        head = first.setdefault(block.page, [])
        tail = last.setdefault(block.page, deque(maxlen=RUNNING_LINES_PER_EDGE))
        for start, end in _lines(block.text):
            item = (index, start, end)
            if len(head) < RUNNING_LINES_PER_EDGE:
                head.append(item)
            tail.append(item)
    pages_total = len(first)
    seen: dict[str, dict[int, set[tuple[int, int]]]] = {}
    for page, head in first.items():
        for index, start, end in {*head, *last[page]}:
            if end - start > patterns.MAX_RUNNING_CHARS:
                continue
            line = blocks[index].text[start:end]
            if patterns.is_structural(line):
                continue
            seen.setdefault(line, {}).setdefault(page, set()).add((index, start))
    running: set[tuple[int, int]] = set()
    for pages in seen.values():
        if len(pages) >= MIN_RUNNING_PAGES and 2 * len(pages) >= pages_total:
            for positions in pages.values():
                running |= positions
    return running


def _has_numbering(blocks: Sequence[Block]) -> bool:
    for block in blocks:
        if block.part != _BODY:
            continue
        for start, end in _lines(block.text):
            if patterns.parse_start(block.text[start:end]) is not None:
                return True
    return False


def _next_line_opens_clause(blocks: Sequence[Block], index: int, after: int) -> bool:
    """Does the next body line after ``(index, after)`` start a numbered clause text?"""
    while index < len(blocks):
        if blocks[index].part == _BODY:
            text = blocks[index].text
            for start, end in _lines(text, after):
                return patterns.opens_clause_text(text[start:end])
        index += 1
        after = 0
    return False


class _Structure:
    """The body pass: preamble, starts, headings, running lines, warnings."""

    def __init__(self, blocks: Sequence[Block], builder: _Builder) -> None:
        self.blocks = blocks
        self.builder = builder
        self.numbering = _Numbering()
        self.warnings: list[tuple[str, _Entry]] = []
        self.running = _running_positions(blocks)
        self.running_entries: dict[str, _Entry] = {}
        self.current: _Entry | None = None
        self.heading: Span | None = None
        self.started = False

    def _begin(self, entry: _Entry) -> _Entry:
        self.builder.entries.append(entry)
        self.current = entry
        self.started = True
        return entry

    def body_block(self, index: int) -> None:
        block = self.blocks[index]
        text = block.text
        for start, end in _lines(text):
            if (index, start) in self.running:
                self._running_line(index, text, start, end, block.page)
                continue
            line = text[start:end]
            entry = self._start_entry(index, text, line, start, end)
            if entry is None:
                entry = self.current
                if entry is None:
                    entry = _Entry("preamble", None, 0, None, None)
                    self.builder.entries.append(entry)
                    self.current = entry
            self.builder.add(entry, index, text, start, end, block.page)

    def _running_line(self, index: int, text: str, start: int, end: int, page: int | None) -> None:
        line = text[start:end]
        entry = self.running_entries.get(line)
        if entry is None:
            entry = _Entry("running", None, 0, None, None)
            self.running_entries[line] = entry
            self.builder.entries.append(entry)
        self.builder.add(entry, index, text, start, end, page)

    def _start_entry(self, index: int, text: str, line: str, start: int, end: int) -> _Entry | None:
        """A new current entry if ``line`` is a clause start or a heading, else ``None``."""
        found = patterns.parse_start(line)
        if found is not None:
            title = line[found.title_offset :]
            kind: str | None = None
            if len(found.parts) == 1 and patterns.is_title(line, title):
                self.heading = (index, start + found.title_offset, end)
                if patterns.is_requisites_title(title):
                    kind = _REQUISITES
            entry = _Entry(_BODY, found.number, len(found.parts), kind, self.heading)
            code = self.numbering.check(found.style, found.parts)
            if code is not None:
                self.warnings.append((code, entry))
            return self._begin(entry)
        heading = patterns.unnumbered_heading(line)
        if heading == patterns.HEADING_NONE:
            return None
        if (
            heading == patterns.HEADING_CAPS
            and not self.started
            # The first line of the file is the title; later a heading needs clause text next.
            and (self.current is None or not _next_line_opens_clause(self.blocks, index, end))
        ):
            return None
        if heading == patterns.HEADING_CAPS and line.startswith(patterns.ANNEX_WORDS):
            self.numbering.reset()
        self.heading = (index, start, end)
        kind = _REQUISITES if heading == patterns.HEADING_REQUISITES else None
        return self._begin(_Entry(_BODY, None, 1, kind, self.heading))


def segment(blocks: Sequence[InputBlock], *, limits: SegmentLimits) -> SegmentResult:
    """Split the blocks of one document into clauses (ADR 0014)."""
    cleaned, cleaner = _clean(blocks)
    if not any(text and not text.isspace() for text in (b.text for b in cleaned)):
        raise SegmentError(NO_TEXT_EXTRACTED)
    builder = _Builder(limits)
    numbered = _has_numbering(cleaned)
    structure = _Structure(cleaned, builder) if numbered else None
    for index, block in enumerate(cleaned):
        if structure is not None and block.part == _BODY:
            structure.body_block(index)
            continue
        # A non-body block, or a body block of a file without numbering: one clause.
        part: ClausePart = block.part
        entry = _Entry(part, None, 0, None, None)
        for start, end in _lines(block.text):
            builder.add(entry, index, block.text, start, end, block.page)
        if entry.spans or entry.done:
            builder.entries.append(entry)
    warnings: list[tuple[str, _Entry | None]] = []
    if structure is not None:
        warnings.extend(structure.warnings)
    else:
        warnings.append(("no_numbering_found", None))
    return _result(cleaned, cleaner, builder.entries, warnings)


def _result(
    blocks: list[Block],
    cleaner: TextCleaner,
    entries: list[_Entry],
    warnings: list[tuple[str, _Entry | None]],
) -> SegmentResult:
    # Parts of a long clause and the running clauses interleave: order by the first span.
    parts: list[tuple[int, int, _Entry, int, list[list[int]], list[int]]] = []
    for entry in entries:
        entry.flush()
        parts.extend(
            (spans[0][0], spans[0][1], entry, part_index, spans, pages)
            for part_index, (spans, pages) in enumerate(entry.done)
        )
    parts.sort(key=lambda item: (item[0], item[1]))
    clauses: list[Clause] = []
    for _, _, entry, part_index, spans, pages in parts:
        clause_id = f"c{len(clauses) + 1}"
        if part_index == 0:
            entry.first_id = clause_id
        clauses.append(
            Clause(
                id=clause_id,
                number=entry.number,
                level=entry.level,
                part_index=part_index,
                section_kind=_REQUISITES if entry.section_kind else None,
                part=entry.part,
                pages=pages,
                spans=[(s[0], s[1], s[2]) for s in spans],
                heading_span=entry.heading_span,
            )
        )
    return SegmentResult(
        clauses=clauses,
        blocks=blocks,
        removed=cleaner.removed(),
        warnings=[
            SegmentWarning(code=code, clause=None if entry is None else entry.first_id)
            for code, entry in warnings
        ],
    )
