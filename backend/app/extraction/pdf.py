"""PDF extraction (S3-T3; ADR 0004 revision, ADR 0009 Layer 0; threat model T4, T5).

``extract_pdf`` is pure and runs inside the parsing child (ADR 0011). It uses
``pdfminer.six`` with our own document layer (``app.extraction.pdf_document``) and
device (``app.extraction.pdf_device``). No pdfplumber.

pdfminer safety (AC1, AC2): the ``pdfminer`` logger is set to ERROR, does not
propagate and has only a counting handler that never formats a message (pdfminer
messages contain PDF data); ``CMAP_PATH`` is removed from the environment, so
CMaps come only from pdfminer's own JSON files; an encrypted PDF is opened only
with the empty user password, otherwise ``encrypted_unsupported``.

Steps:

1. Open the document: the ``/Prev`` chain is walked by our own loop (cap
   ``max_prev_chain``, loop → ``pdf_damaged``); an object listed in a
   cross-reference section that cannot be parsed → ``pdf_damaged``; pdfminer's
   cross-reference reconstruction → material warning ``damaged_pdf``; more than
   one revision → warning ``pdf_edited``. Any parse failure or ``RecursionError``
   → ``pdf_damaged``.
2. Count pages before extraction: more than ``max_pages`` → ``too_many_pages``.
3. Per page, the device records glyphs, filled paths and images. Glyphs are
   classified (first match wins) and removed text is reported per page and reason:

   - render mode 3 or 7 → ``invisible_render_mode``;
   - box fully outside the crop box → ``outside_page``;
   - em size under 1 pt along either axis → ``tiny_text``;
   - alpha 0 for every paint the render mode uses → ``transparent``;
   - exact white (Gray 1, RGB 1/1/1, CMYK 0/0/0/0) for every paint the render
     mode uses, in a plain graphics state, with nothing painted behind it except
     exact-white fills → ``same_color``.

   Kept glyphs get ``borderline_text`` (per page) when: em size at most
   ``SMALL_TEXT_PT``; a render mode outside 0-7; a paint colour that cannot be
   resolved (patterns, unknown spaces); alpha above 0 and below ``LOW_ALPHA``;
   any fill or stroke whose colour cannot be compared (patterns, shadings, ``sh``,
   stroked paths) lies behind the glyph; the glyph is clipped away (zero-area clip,
   outside a form ``BBox``) or in an optional content group that is OFF; the text
   luminance is within ``MIN_CONTRAST`` of a known fill behind it; or the glyph is
   light (luminance above ``NEAR_WHITE``) and lies on the white page, on an image,
   or in an exotic graphics state (blend mode, soft mask). Colour spaces are
   resolved by ``pdf_colour``; clips, optional content and content that pdfminer
   does not run (``not_read_pattern``, ``not_read_type3``) by ``pdf_device`` and
   ``pdf_content``. Residual: text covered by a shape painted later (ADR 0009).
   Whitespace glyphs follow the removal rules but never raise ``borderline_text``,
   and removed whitespace is not counted (it appears in the sample).
4. Overlap (NFC; marks Mn, Me and Sk excluded): identical glyphs at the same
   position (fake bold) are merged; different glyphs whose boxes overlap by more
   than half of the smaller box → kept, warning ``overlapping_text``.
5. Layout: pdfminer's line and box grouping (``LAParams`` defaults); boxes are
   ordered by pdfminer's hierarchical flow up to ``MAX_FLOW_BOXES`` boxes per page,
   else top to bottom, left to right. One block per box; lines joined with ``\\n``.
6. Running headers and footers: a line in the top or bottom band
   (``EDGE_BAND`` of the page height) whose text repeats in that band on at least
   half of the pages (and at least two) is kept once (``repeated_header_footer``
   for the rest); page-number-only lines in the bands → ``page_number``.
7. Scans: a page with no body text (header, footer and page-number lines do not
   count) and images over at least ``OCR_MIN_IMAGE_SHARE`` of the page →
   ``ocr_pages``. A page with fewer than ``LITTLE_TEXT_CHARS`` characters and an
   image of at least 15 % of the page or images of at least 30 % together →
   material warning ``not_read_image_page`` (signature-page rule).
8. Annotations: any visible annotation with a normal appearance (``/AP /N``) other
   than Link and Popup, FreeText and Text with non-empty ``Contents``, Widget with
   a non-empty value (``V`` of the widget or its parent fields) → material warning
   ``not_read_annotation``; Hidden and NoView annotations are ignored. An AcroForm
   with ``XFA`` → ``not_read_xfa``.
9. Shared post-processing: NFC and invisible and control characters
   (``app.textclean``), external references (``app.extraction.references``), language,
   caps (characters, blocks, ``removed`` and ``warnings`` at most ``MAX_LIST_ITEMS`` each;
   a cap fails closed with ``too_much_text``). Zero blocks and no OCR page → ``no_text_extracted``.

Errors carry codes only, never text.
"""

from __future__ import annotations

import logging
import os
import re
import struct
import unicodedata
import zlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from io import BytesIO
from typing import Final

from pdfminer.layout import (
    IndexAssigner,
    LAParams,
    LTChar,
    LTPage,
    LTTextBox,
    LTTextBoxVertical,
    LTTextLine,
)
from pdfminer.pdfdocument import PDFEncryptionError, PDFPasswordIncorrect
from pdfminer.pdfinterp import PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from pdfminer.pdftypes import resolve1
from pdfminer.psexceptions import PSException
from pdfminer.psparser import PSLiteral, literal_name
from pdfminer.utils import Rect

from app.extraction.language import detect_language
from app.extraction.model import (
    DEFAULT_MAX_PDF_PAGES,
    DEFAULT_MAX_PDF_PREV_CHAIN,
    ENCRYPTED_UNSUPPORTED,
    MAX_LIST_ITEMS,
    MAX_SAMPLE_CHARS,
    NO_TEXT_EXTRACTED,
    PDF_DAMAGED,
    TOO_MANY_PAGES,
    TOO_MUCH_TEXT,
    Block,
    ExtractionError,
    ExtractionResult,
    Removed,
    Warning,
)
from app.extraction.normalize import PAGE_NUMBER_LINE
from app.extraction.pdf_colour import Colour, is_white, luminance
from app.extraction.pdf_content import OptionalContent
from app.extraction.pdf_device import (
    Glyph,
    PageRecord,
    RecordingDevice,
    StateInterpreter,
    clip_hides,
    intersect,
    resolved_list,
)
from app.extraction.pdf_document import CheckedDocument, PdfDamagedError
from app.extraction.references import external_reference_warnings
from app.textclean import TextCleaner, clean_text

# --- pdfminer logging (AC1) -------------------------------------------------------------------


class _CountingHandler(logging.Handler):
    """Counts pdfminer records of ERROR and above; never formats or writes them."""

    def __init__(self) -> None:
        super().__init__(logging.ERROR)
        self.count = 0

    def emit(self, record: logging.LogRecord) -> None:
        self.count += 1


_PDFMINER_HANDLER: Final = _CountingHandler()


def _quiet_pdfminer() -> None:
    logger = logging.getLogger("pdfminer")
    logger.setLevel(logging.ERROR)
    logger.propagate = False
    if _PDFMINER_HANDLER not in logger.handlers:
        logger.addHandler(_PDFMINER_HANDLER)


_quiet_pdfminer()

# --- Rules --------------------------------------------------------------------------------------

INVISIBLE_RENDER_MODE: Final = "invisible_render_mode"
OUTSIDE_PAGE: Final = "outside_page"
TINY_TEXT: Final = "tiny_text"
TRANSPARENT: Final = "transparent"
SAME_COLOR: Final = "same_color"
REPEATED_HEADER_FOOTER: Final = "repeated_header_footer"
PAGE_NUMBER: Final = "page_number"

BORDERLINE_TEXT: Final = "borderline_text"
OVERLAPPING_TEXT: Final = "overlapping_text"
NOT_READ_IMAGE_PAGE: Final = "not_read_image_page"
NOT_READ_ANNOTATION: Final = "not_read_annotation"
NOT_READ_XFA: Final = "not_read_xfa"
DAMAGED_PDF: Final = "damaged_pdf"
PDF_EDITED: Final = "pdf_edited"

INVISIBLE_MODES: Final = frozenset({3, 7})
FILL_MODES: Final = frozenset({0, 2, 4, 6})
STROKE_MODES: Final = frozenset({1, 2, 5, 6})
MIN_EM_PT: Final = 1.0
SMALL_TEXT_PT: Final = 4.0
NEAR_WHITE: Final = 0.9
# Alpha below this (but above 0) and a luminance difference below this to a known
# fill are borderline.
LOW_ALPHA: Final = 0.2
MIN_CONTRAST: Final = 0.2
# Render modes 0-7 are defined (ISO 32000-1, 9.3.6).
MAX_RENDER_MODE: Final = 7
# Distinct known fill colours kept per glyph before the background is unknown.
MAX_FILL_COLOURS: Final = 16
# Overlap: more than half of the smaller box; fake bold: offset within a quarter
# of the glyph box.
OVERLAP_SHARE: Final = 0.5
SAME_POSITION_SHARE: Final = 0.25
# Characters that are drawn over a base letter on purpose (accents, breves).
MARK_CATEGORIES: Final = frozenset({"Mn", "Me", "Sk"})
# Glyphs per grid cell before the page is flagged as overlapping without more checks.
MAX_CELL_GLYPHS: Final = 256
GRID_CELLS_PER_SIDE: Final = 64
MIN_GRID_CELL_PT: Final = 16.0

MAX_FLOW_BOXES: Final = 200
EDGE_BAND: Final = 0.08
# A header or footer line counts as repeated on at least this many pages.
MIN_REPEATS: Final = 2
LITTLE_TEXT_CHARS: Final = 200
OCR_MIN_IMAGE_SHARE: Final = 0.01
STAMP_MAX_SHARE: Final = 0.15
STAMPS_MAX_SHARE: Final = 0.30
MAX_ANNOTATIONS: Final = 1000
MAX_FIELD_DEPTH: Final = 32
ANNOT_HIDDEN_FLAGS: Final = 0b10_0010  # Hidden (bit 2) or NoView (bit 6)
VALUE_ANNOTS: Final = frozenset({"FreeText", "Text"})
QUIET_ANNOTS: Final = frozenset({"Link", "Popup"})
HEAD_CHARS: Final = 2 * MAX_SAMPLE_CHARS
# Glyphs rendered in the whole document, visible or not, per allowed character.
GLYPHS_PER_CHAR: Final = 2

_SPACES: Final = re.compile(r"\s+")
# Parse failures of hostile input. MemoryError is not here: the child dies and the
# parent answers `extraction_failed`.
_PARSE_ERRORS: Final = (
    PSException,
    PdfDamagedError,
    RecursionError,
    ValueError,
    TypeError,
    KeyError,
    IndexError,
    AttributeError,
    AssertionError,
    ArithmeticError,
    EOFError,
    struct.error,
    zlib.error,
)


@dataclass(frozen=True)
class PdfLimits:
    max_pages: int = DEFAULT_MAX_PDF_PAGES
    max_prev_chain: int = DEFAULT_MAX_PDF_PREV_CHAIN


# --- Per-page analysis --------------------------------------------------------------------------


def _area(box: Rect) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


_Cell = tuple[int, int]


class _Grid:
    """A uniform grid over the crop box: item indices per cell."""

    def __init__(self, crop: Rect) -> None:
        self.crop = crop
        side = max(crop[2] - crop[0], crop[3] - crop[1], 1.0)
        self.cell = max(MIN_GRID_CELL_PT, side / GRID_CELLS_PER_SIDE)
        self.cells: dict[_Cell, list[int]] = {}

    def keys(self, box: Rect) -> list[_Cell]:
        """The cells of ``box`` clipped to the crop box (at most 65 x 65)."""
        cx0, cy0, cx1, cy1 = self.crop
        x0, y0 = max(box[0], cx0), max(box[1], cy0)
        x1, y1 = min(box[2], cx1), min(box[3], cy1)
        if x0 > x1 or y0 > y1:
            return []
        cell = self.cell
        i0, i1 = int((x0 - cx0) // cell), int((x1 - cx0) // cell)
        j0, j1 = int((y0 - cy0) // cell), int((y1 - cy0) // cell)
        if i0 == i1 and j0 == j1:
            return [(i0, j0)]
        return [(i, j) for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)]

    def add(self, index: int, box: Rect) -> None:
        for key in self.keys(box):
            self.cells.setdefault(key, []).append(index)

    def near(self, keys: list[_Cell]) -> set[int]:
        out: set[int] = set()
        for key in keys:
            out.update(self.cells.get(key, ()))
        return out


@dataclass
class _Line:
    text: str
    y0: float
    y1: float


@dataclass
class _Removal:
    """Removed text of one reason: characters and the head of the sample."""

    count: int = 0
    head: str = ""


@dataclass
class _PageText:
    number: int
    height: float
    bottom: float
    boxes: list[list[_Line]]
    removed: dict[str, _Removal]
    warnings: set[str]
    image_shares: list[float]  # visible share of the page per image


@dataclass
class _Background:
    """What is painted behind one glyph."""

    white_only: bool = True  # nothing but exact-white fills (or nothing)
    image: bool = False
    unknown_fill: bool = False
    lums: list[float] = field(default_factory=list)  # luminance of known fills


_PLAIN_PAGE: Final = _Background()


def _background(glyph: Glyph, record: PageRecord, fills: _Grid, images: _Grid) -> _Background:
    found = _Background()
    if record.fills_overflow:
        found.white_only = False
        found.unknown_fill = True
    box = glyph.bbox
    if record.fills:
        keys = fills.keys(box)
    elif record.images:
        keys = images.keys(box)
    else:
        return found
    for index in fills.near(keys):
        item = record.fills[index]
        if item.seq > glyph.seq or intersect(item.bbox, box) is None:
            continue
        if item.colour is None or item.stroke:
            # A stroke box is only an upper bound of the paint: not comparable.
            found.unknown_fill = True
            found.white_only = False
            continue
        if not is_white(item.colour):
            found.white_only = False
        if len(found.lums) < MAX_FILL_COLOURS:
            found.lums.append(luminance(item.colour))
        else:
            found.unknown_fill = True
    for index in images.near(keys):
        image = record.images[index]
        if image.seq < glyph.seq and intersect(image.bbox, box) is not None:
            found.image = True
            found.white_only = False
    return found


def _outside_axis(low: float, high: float, start: float, end: float) -> bool:
    if high > low:
        return high <= start or low >= end
    # A zero-width box (a combining mark) is outside unless strictly inside.
    return low <= start or low >= end


def _outside(box: Rect, crop: Rect) -> bool:
    """The box shares no area with the crop box (zero-width boxes: no point)."""
    return _outside_axis(box[0], box[2], crop[0], crop[2]) or _outside_axis(
        box[1], box[3], crop[1], crop[3]
    )


@dataclass(frozen=True, slots=True)
class _Paint:
    """What the paint of one style and render mode says, before the background."""

    transparent: bool  # alpha 0 for every paint the render mode uses
    plain_white: bool  # white for every paint, in a plain graphics state
    light: bool  # luminance above NEAR_WHITE for every known paint
    unresolved: bool  # a paint colour we cannot resolve (patterns, unknown spaces)
    low_alpha: bool  # alpha above 0 and below LOW_ALPHA for some paint
    lums: tuple[float, ...]  # luminance of the known paints
    exotic: bool


def _paint(glyph: Glyph) -> _Paint:
    style = glyph.style
    alphas: list[float] = []
    colours: list[Colour | None] = []
    if glyph.render in FILL_MODES:
        alphas.append(style.fill_alpha)
        colours.append(style.fill)
    if glyph.render in STROKE_MODES:
        alphas.append(style.stroke_alpha)
        colours.append(style.stroke)
    known = [colour for colour in colours if colour is not None]
    white = bool(colours) and len(known) == len(colours) and all(is_white(c) for c in known)
    lums = tuple(luminance(c) for c in known)
    return _Paint(
        transparent=bool(alphas) and all(alpha == 0.0 for alpha in alphas),
        plain_white=white and not style.exotic,
        light=bool(known) and all(lum > NEAR_WHITE for lum in lums),
        unresolved=len(known) != len(colours),
        low_alpha=any(0.0 < alpha < LOW_ALPHA for alpha in alphas),
        lums=lums,
        exotic=style.exotic,
    )


class _Judge:
    """Classifies the glyphs of one page (rules in the module doc)."""

    def __init__(self, record: PageRecord) -> None:
        self.record = record
        self.fills = _Grid(record.crop)
        for index, fill_item in enumerate(record.fills):
            self.fills.add(index, fill_item.bbox)
        self.images = _Grid(record.crop)
        for index, image in enumerate(record.images):
            self.images.add(index, image.bbox)
        self.painted = bool(record.fills or record.images or record.fills_overflow)
        # Paint verdicts per (style, render mode): styles are shared by the glyphs of
        # one text-showing operator and stay alive with the page record.
        self._paints: dict[tuple[int, int], _Paint] = {}

    def verdict(self, glyph: Glyph) -> tuple[str | None, bool]:
        """(removal reason or None, borderline)."""
        if glyph.render in INVISIBLE_MODES:
            return INVISIBLE_RENDER_MODE, False
        if _outside(glyph.bbox, self.record.crop):
            return OUTSIDE_PAGE, False
        em = min(glyph.em_x, glyph.em_y)
        if em < MIN_EM_PT:
            return TINY_TEXT, False
        key = (id(glyph.style), glyph.render)
        paint = self._paints.get(key)
        if paint is None:
            paint = self._paints[key] = _paint(glyph)
        if paint.transparent:
            return TRANSPARENT, False
        behind = (
            _background(glyph, self.record, self.fills, self.images)
            if self.painted
            else _PLAIN_PAGE
        )
        if paint.plain_white and behind.white_only:
            return SAME_COLOR, False
        borderline = (
            em <= SMALL_TEXT_PT
            or glyph.render > MAX_RENDER_MODE
            or glyph.render < 0
            or paint.unresolved
            or paint.low_alpha
            or behind.unknown_fill
            or glyph.style.layer_off
            or clip_hides(glyph.style.clip, glyph.bbox)
            or (paint.light and (behind.white_only or behind.image or paint.exotic))
            or any(abs(lum - fill) < MIN_CONTRAST for lum in paint.lums for fill in behind.lums)
        )
        return None, borderline


def _skips_overlap(text: str) -> bool:
    """Whitespace and marks drawn over a base letter on purpose."""
    return not text.strip() or all(unicodedata.category(ch) in MARK_CATEGORIES for ch in text)


def _merge_overlaps(glyphs: list[Glyph], crop: Rect) -> tuple[list[Glyph], bool]:
    """Fake-bold duplicates merged; ``True`` when different glyphs overlap."""
    grid = _Grid(crop)
    cells = grid.cells
    # Glyphs in the grid: (x0, y0, x1, y1, area, NFC text).
    entries: list[tuple[float, float, float, float, float, str]] = []
    kept: list[Glyph] = []
    overlapping = False
    # Glyphs per cell, merged duplicates included: a cap on the work per cell.
    visits: dict[_Cell, int] = {}
    skips: dict[str, bool] = {}
    for glyph in glyphs:
        text = glyph.text if glyph.text.isascii() else unicodedata.normalize("NFC", glyph.text)
        skip = skips.get(text)
        if skip is None:
            skip = skips[text] = _skips_overlap(text)
        x0, y0, x1, y1 = glyph.bbox
        area = (x1 - x0) * (y1 - y0)
        if skip or area <= 0.0:
            kept.append(glyph)
            continue
        keys = grid.keys(glyph.bbox)
        crowded = False
        for key in keys:
            visits[key] = visits.get(key, 0) + 1
            crowded = crowded or visits[key] > MAX_CELL_GLYPHS
        if crowded:
            # Too many glyphs in one cell to compare them all: fail closed.
            overlapping = True
            kept.append(glyph)
            continue
        candidates: Iterable[int] = cells.get(keys[0], ()) if len(keys) == 1 else grid.near(keys)
        duplicate = False
        for index in candidates:
            ox0, oy0, ox1, oy1, other_area, other_text = entries[index]
            width_shared = min(x1, ox1) - max(x0, ox0)
            if width_shared <= 0.0:
                continue
            height_shared = min(y1, oy1) - max(y0, oy0)
            if height_shared <= 0.0:
                continue
            if width_shared * height_shared <= OVERLAP_SHARE * min(area, other_area):
                continue
            width = max(x1 - x0, ox1 - ox0)
            height = max(y1 - y0, oy1 - oy0)
            if (
                other_text == text
                and abs(x0 - ox0) <= SAME_POSITION_SHARE * width
                and abs(y0 - oy0) <= SAME_POSITION_SHARE * height
            ):
                duplicate = True
                break
            overlapping = True
        if duplicate:
            continue
        index = len(entries)
        entries.append((x0, y0, x1, y1, area, text))
        for key in keys:
            cells.setdefault(key, []).append(index)
        kept.append(glyph)
    return kept, overlapping


def _layout(glyphs: list[Glyph], crop: Rect, number: int) -> list[LTTextBox]:
    """pdfminer's grouping into lines and boxes, with a cap on the flow analysis."""
    laparams = LAParams()
    page = LTPage(number, crop)
    chars: list[LTChar] = [glyph.char for glyph in glyphs]
    if not chars:
        return []
    lines = [line for line in page.group_objects(laparams, chars) if not line.is_empty()]
    boxes = list(page.group_textlines(laparams, lines))
    if len(boxes) > MAX_FLOW_BOXES:
        for box in boxes:
            box.analyze(laparams)

        def key(box: LTTextBox) -> tuple[int, float, float]:
            if isinstance(box, LTTextBoxVertical):
                return (0, -box.x1, -box.y0)
            return (1, -box.y0, box.x0)

        boxes.sort(key=key)
        return boxes
    assigner = IndexAssigner()
    for group in page.group_textboxes(laparams, boxes):
        group.analyze(laparams)
        assigner.run(group)
    boxes.sort(key=lambda box: box.index)
    return boxes


class _Removals:
    """Removed text of one page: per reason a character count and the sample head."""

    def __init__(self) -> None:
        self.items: dict[str, _Removal] = {}
        self._runs: dict[str, int] = {}

    def add(self, reason: str, glyph: Glyph) -> None:
        item = self.items.setdefault(reason, _Removal())
        if not glyph.text.isspace():
            item.count += len(glyph.text)
        if len(item.head) < HEAD_CHARS:
            if self._runs.get(reason, glyph.run) != glyph.run:
                item.head += " "
            item.head += glyph.text
        self._runs[reason] = glyph.run


def _image_shares(record: PageRecord) -> list[float]:
    page_area = _area(record.crop)
    if page_area <= 0.0:
        return []
    shares = []
    for image in record.images:
        visible = intersect(image.bbox, record.crop)
        if visible is not None:
            shares.append(_area(visible) / page_area)
    return shares


def analyze_page(record: PageRecord) -> _PageText:
    judge = _Judge(record)
    removals = _Removals()
    warnings: set[str] = set()
    visible: list[Glyph] = []
    for glyph in record.glyphs:
        reason, borderline = judge.verdict(glyph)
        if reason is not None:
            removals.add(reason, glyph)
            continue
        if borderline and not glyph.text.isspace():
            warnings.add(BORDERLINE_TEXT)
        visible.append(glyph)
    kept, overlapping = _merge_overlaps(visible, record.crop)
    if overlapping:
        warnings.add(OVERLAPPING_TEXT)
    boxes: list[list[_Line]] = []
    for box in _layout(kept, record.crop, record.number):
        lines = []
        for line in box:
            if isinstance(line, LTTextLine):
                text = line.get_text().rstrip()
                if text.strip():
                    lines.append(_Line(text=text, y0=line.y0, y1=line.y1))
        if lines:
            boxes.append(lines)
    warnings |= record.flags
    return _PageText(
        number=record.number,
        height=record.crop[3] - record.crop[1],
        bottom=record.crop[1],
        boxes=boxes,
        removed=removals.items,
        warnings=warnings,
        image_shares=_image_shares(record),
    )


# --- Annotations and forms ----------------------------------------------------------------------


def _non_empty(value: object) -> bool:
    value = resolve1(value)
    if isinstance(value, bytes):
        return bool(value.strip(b" \t\r\n\x00")) and value not in {b"\xfe\xff", b"\xff\xfe"}
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, PSLiteral):
        return literal_name(value) not in {"", "Off"}
    if isinstance(value, (list, tuple)):
        return any(_non_empty(item) for item in value)
    return False


def _field_value(annot: dict[object, object]) -> object:
    node: object = annot
    for _ in range(MAX_FIELD_DEPTH):
        if not isinstance(node, dict):
            return None
        if "V" in node:
            return node["V"]
        node = resolve1(node.get("Parent"))
    return None


def _has_appearance(annot: dict[object, object]) -> bool:
    """The annotation has a normal appearance stream (``/AP /N``) that viewers draw."""
    appearance = resolve1(annot.get("AP"))
    return isinstance(appearance, dict) and resolve1(appearance.get("N")) is not None


def _annotation_warning(page: PDFPage) -> bool:
    annots = resolved_list(page.annots) if page.annots is not None else []
    for item in annots[:MAX_ANNOTATIONS]:
        annot = resolve1(item)
        if not isinstance(annot, dict):
            continue
        flags = resolve1(annot.get("F"))
        if isinstance(flags, int) and flags & ANNOT_HIDDEN_FLAGS:
            continue
        subtype = resolve1(annot.get("Subtype"))
        name = literal_name(subtype) if isinstance(subtype, PSLiteral) else ""
        if name not in QUIET_ANNOTS and _has_appearance(annot):
            return True
        if name in VALUE_ANNOTS and _non_empty(annot.get("Contents")):
            return True
        if name == "Widget" and _non_empty(_field_value(annot)):
            return True
    return len(annots) > MAX_ANNOTATIONS


def _has_xfa(catalog: dict[str, object]) -> bool:
    form = resolve1(catalog.get("AcroForm"))
    return isinstance(form, dict) and resolve1(form.get("XFA")) is not None


# --- Document -----------------------------------------------------------------------------------


@dataclass
class _Report:
    """Warnings (per code: document level or pages in order) and removed items."""

    pages: dict[str, set[int]] = field(default_factory=dict)
    document: list[str] = field(default_factory=list)
    removed: list[Removed] = field(default_factory=list)

    def warn(self, code: str, page: int | None = None) -> None:
        if page is None:
            if code not in self.document:
                self.document.append(code)
        else:
            self.pages.setdefault(code, set()).add(page)

    def remove(self, reason: str, count: int, head: str) -> None:
        if count <= 0:
            return
        if len(self.removed) >= MAX_LIST_ITEMS:
            raise ExtractionError(TOO_MUCH_TEXT)
        sample = _SPACES.sub(" ", clean_text(head[:HEAD_CHARS]).text).strip()
        self.removed.append(Removed(reason=reason, count=count, sample=sample[:MAX_SAMPLE_CHARS]))

    def warnings(self, extra: list[Warning]) -> list[Warning]:
        out = [Warning(code=code, page=None) for code in self.document]
        for code, pages in self.pages.items():
            out.extend(Warning(code=code, page=page) for page in sorted(pages))
        out.extend(extra)
        if len(out) > MAX_LIST_ITEMS:
            raise ExtractionError(TOO_MUCH_TEXT)
        return out


def _band_key(line: _Line, page: _PageText) -> str | None:
    """The comparison key of a line in the top or bottom band, else ``None``."""
    band = EDGE_BAND * page.height
    if line.y0 >= page.bottom + page.height - band or line.y1 <= page.bottom + band:
        return _SPACES.sub(" ", line.text).strip().casefold()
    return None


def _repeated_keys(pages: list[_PageText]) -> set[str]:
    seen: dict[str, int] = {}
    for page in pages:
        keys = {key for box in page.boxes for line in box if (key := _band_key(line, page))}
        for key in keys:
            seen[key] = seen.get(key, 0) + 1
    return {key for key, count in seen.items() if count >= MIN_REPEATS and 2 * count >= len(pages)}


def _blocks(  # noqa: PLR0912 - one pass over lines, removals and warnings
    pages: list[_PageText],
    report: _Report,
    cleaner: TextCleaner,
    *,
    max_chars: int,
    max_blocks: int,
) -> tuple[list[Block], list[int]]:
    """Blocks and OCR pages. Header, footer and page-number lines do not count as text."""
    repeated = _repeated_keys(pages)
    ocr_pages: list[int] = []
    shown: set[str] = set()
    blocks: list[Block] = []
    chars = 0
    for page in pages:
        dropped: dict[str, list[str]] = {}
        body_chars = 0
        for box in page.boxes:
            kept: list[str] = []
            for line in box:
                key = _band_key(line, page)
                if key is not None and PAGE_NUMBER_LINE.fullmatch(key):
                    dropped.setdefault(PAGE_NUMBER, []).append(line.text)
                    continue
                if key is not None and key in repeated:
                    if key in shown:
                        dropped.setdefault(REPEATED_HEADER_FOOTER, []).append(line.text)
                        continue
                    shown.add(key)
                else:
                    body_chars += len("".join(line.text.split()))
                kept.append(line.text)
            text = cleaner.clean("\n".join(kept)).strip()
            if not text:
                continue
            chars += len(text)
            if chars > max_chars or len(blocks) >= max_blocks:
                raise ExtractionError(TOO_MUCH_TEXT)
            blocks.append(Block(text=text, part="body", page=page.number))
        total_share = min(1.0, sum(page.image_shares))
        if body_chars == 0 and total_share >= OCR_MIN_IMAGE_SHARE:
            ocr_pages.append(page.number)
        elif body_chars < LITTLE_TEXT_CHARS and page.image_shares and not _stamps_only(page):
            page.warnings.add(NOT_READ_IMAGE_PAGE)
        for reason, removed in page.removed.items():
            report.remove(reason, removed.count, removed.head)
        for reason, texts in dropped.items():
            joined = "\n".join(texts)
            report.remove(reason, len("".join(joined.split())), joined)
        for code in sorted(page.warnings):
            report.warn(code, page.number)
    return blocks, ocr_pages


def _stamps_only(page: _PageText) -> bool:
    """The signature-page rule: small images only (each under 15 %, together under 30 %)."""
    shares = page.image_shares
    return all(s < STAMP_MAX_SHARE for s in shares) and min(1.0, sum(shares)) < STAMPS_MAX_SHARE


def _open(data: bytes, limits: PdfLimits) -> tuple[CheckedDocument, list[PDFPage]]:
    parser = PDFParser(BytesIO(data))
    try:
        document = CheckedDocument(parser, data=data, max_prev_chain=limits.max_prev_chain)
    except (PDFPasswordIncorrect, PDFEncryptionError):
        raise ExtractionError(ENCRYPTED_UNSUPPORTED) from None
    pages: list[PDFPage] = []
    for page in PDFPage.create_pages(document):
        pages.append(page)
        if len(pages) > limits.max_pages:
            raise ExtractionError(TOO_MANY_PAGES)
    return document, pages


def _extract(
    data: bytes, *, max_chars: int, max_blocks: int, limits: PdfLimits
) -> ExtractionResult:
    report = _Report()
    document, pages = _open(data, limits)
    if not pages:
        raise ExtractionError(NO_TEXT_EXTRACTED)
    if document.fallback_used:
        report.warn(DAMAGED_PDF)
    if document.revisions > 1:
        report.warn(PDF_EDITED)
    if _has_xfa(document.catalog):
        report.warn(NOT_READ_XFA)

    texts: list[_PageText] = []
    rsrcmgr = PDFResourceManager(caching=True)
    device = RecordingDevice(
        rsrcmgr,
        max_glyphs=GLYPHS_PER_CHAR * max_chars,
        on_page=lambda record: texts.append(analyze_page(record)),
    )
    interpreter = StateInterpreter(rsrcmgr, device, OptionalContent(document.catalog))
    for number, page in enumerate(pages, start=1):
        interpreter.process_page(page)
        if _annotation_warning(page):
            report.warn(NOT_READ_ANNOTATION, number)
    if _PDFMINER_HANDLER.count:
        report.warn(DAMAGED_PDF)

    cleaner = TextCleaner()
    blocks, ocr_pages = _blocks(texts, report, cleaner, max_chars=max_chars, max_blocks=max_blocks)
    if not blocks and not ocr_pages:
        raise ExtractionError(NO_TEXT_EXTRACTED)
    removed = report.removed + cleaner.removed()
    if len(removed) > MAX_LIST_ITEMS:
        raise ExtractionError(TOO_MUCH_TEXT)
    return ExtractionResult(
        kind="pdf",
        bytes=len(data),
        language=detect_language("\n".join(block.text for block in blocks)),
        pages=len(pages),
        blocks=blocks,
        ocr_pages=ocr_pages,
        removed=removed,
        warnings=report.warnings(external_reference_warnings(blocks, per_page=True)),
    )


def extract_pdf(
    data: bytes, *, max_chars: int, max_blocks: int, limits: PdfLimits
) -> ExtractionResult:
    """Extract the text a person sees in ``data`` (see the module doc).

    Raises ``ExtractionError`` with a contract code.
    """
    _quiet_pdfminer()
    os.environ.pop("CMAP_PATH", None)
    _PDFMINER_HANDLER.count = 0
    try:
        return _extract(data, max_chars=max_chars, max_blocks=max_blocks, limits=limits)
    except ExtractionError:
        raise
    except _PARSE_ERRORS:
        # `from None`: pdfminer exceptions quote the file's bytes.
        raise ExtractionError(PDF_DAMAGED) from None
