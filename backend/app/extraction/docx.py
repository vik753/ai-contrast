# ruff: noqa: RUF001 - checkbox and symbol glyphs are the point of the symbol tables
"""DOCX extraction (S3-T2; ADR 0004 revision, ADR 0009 Layer 0 and Layer 1; T4, T5, T11).

``extract_docx`` is pure and runs inside the parsing child (ADR 0011).

1. The archive is checked as a whole before any part is read (``docx_zip``):
   failures are ``archive_rejected``.
2. The package is resolved the way Word resolves it (``docx_package``). Every XML
   part is parsed with ``defusedxml`` and ``forbid_dtd=True`` (``docx_xml``).
3. The walker (``_PartWalker``) reads what the person reads, one block per
   paragraph: hidden text is removed only when its invisibility is resolved exactly
   (``docx_styles``), otherwise kept and flagged ``borderline_text``; content that
   is shown but not read gets a material ``not_read_*`` warning.
4. Only displayed parts are read: headers and footers referenced by a section
   (first-page ones with ``w:titlePg``, even-page ones with
   ``w:evenAndOddHeaders``); footnotes and endnotes referenced from read content.
   Everything else goes to ``removed`` as ``not_displayed``.
5. The shared text normalization (``normalize``), the header and footer filter,
   the caps of S3-T1 and language detection give the result. ``removed`` holds one
   item per span (``count`` in characters, a sample of the head); ``removed`` and
   ``warnings`` hold at most ``MAX_LIST_ITEMS`` items each.

Header and footer filter: a line that holds only a page number is dropped
(``page_number``); a line repeated in another header part (or another footer part)
is kept once, at its first occurrence (``repeated_header_footer``). Headers and
footers are filtered separately: the same line in a header and in a footer is
kept in both.

Errors carry a code only, never text, names or offsets.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Final
from xml.etree.ElementTree import Element

from app.extraction.docx_package import (
    R_NS,
    DocSettings,
    Reader,
    parse_settings,
    resolve_package,
)
from app.extraction.docx_styles import (
    AUTO,
    VAL,
    WHITE,
    Background,
    Color,
    Styles,
    Theme,
    Verdict,
    W,
    color_spec,
    judge,
    on_off,
    parse_styles,
    parse_theme,
    read_run_property,
    shade_spec,
)
from app.extraction.docx_xml import END, START, START_NS, XmlBudget, suspicious
from app.extraction.docx_zip import DocxArchive, ZipEntry
from app.extraction.language import detect_language
from app.extraction.model import (
    DEFAULT_MAX_BLOCKS,
    DEFAULT_MAX_DOCX_ELEMENTS,
    DEFAULT_MAX_DOCX_PART_BYTES,
    DEFAULT_MAX_DOCX_XML_DEPTH,
    DEFAULT_MAX_TEXT_CHARS,
    DEFAULT_MAX_ZIP_UNCOMPRESSED_BYTES,
    DOCX_STRICT_UNSUPPORTED,
    MAX_SAMPLE_CHARS,
    NO_TEXT_EXTRACTED,
    TOO_MUCH_TEXT,
    Block,
    ExtractionError,
    ExtractionResult,
    Part,
    Removed,
    Warning,
)
from app.extraction.normalize import ControlCleaner

__all__ = ["DocxLimits", "extract_docx"]


@dataclass(frozen=True)
class DocxLimits:
    max_part_bytes: int = DEFAULT_MAX_DOCX_PART_BYTES
    max_total_bytes: int = DEFAULT_MAX_ZIP_UNCOMPRESSED_BYTES
    max_xml_depth: int = DEFAULT_MAX_DOCX_XML_DEPTH
    max_elements: int = DEFAULT_MAX_DOCX_ELEMENTS


# --- Namespaces --------------------------------------------------------------------------

_W: Final = "{" + W + "}"
MC_NS: Final = "http://schemas.openxmlformats.org/markup-compatibility/2006"
W14_NS: Final = "http://schemas.microsoft.com/office/word/2010/wordml"
MATH_NS: Final = "http://schemas.openxmlformats.org/officeDocument/2006/math"
VML_NS: Final = "urn:schemas-microsoft-com:vml"
OFFICE_NS: Final = "urn:schemas-microsoft-com:office:office"
WP_NS: Final = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A_NS: Final = "http://schemas.openxmlformats.org/drawingml/2006/main"
STRICT_PREFIX: Final = "{http://purl.oclc.org/ooxml/"

# ``mc:Choice Requires``: the namespaces Word supports; any other → suspicious.
REQUIRES_ALLOWED: Final = frozenset(
    {
        "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",  # wps
        "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup",  # wpg
        "http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas",  # wpc
        "http://schemas.microsoft.com/office/word/2010/wordprocessingInk",  # wpi
        W14_NS,  # w14
        "http://schemas.microsoft.com/office/word/2012/wordml",  # w15
        "http://schemas.microsoft.com/office/word/2018/wordml",  # w16
        "http://schemas.microsoft.com/office/word/2015/wordml/symex",  # w16se
        "http://schemas.microsoft.com/office/word/2016/wordml/cid",  # w16cid
        "http://schemas.microsoft.com/office/word/2018/wordml/cex",  # w16cex
        "http://schemas.microsoft.com/office/word/2023/wordml/word16du",  # w16du
        "http://schemas.microsoft.com/office/word/2020/wordml/sdtdatahash",  # w16sdtdh
        "http://schemas.microsoft.com/office/drawing/2010/main",  # a14
    }
)
# Namespaces whose markup is understood; an element in an ``mc:Ignorable``
# namespace outside this set is skipped (and must hold no text).
KNOWN_NAMESPACES: Final = REQUIRES_ALLOWED | frozenset(
    {
        W,
        R_NS,
        MC_NS,
        MATH_NS,
        VML_NS,
        OFFICE_NS,
        WP_NS,
        A_NS,
        "http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing",  # wp14
        "http://schemas.openxmlformats.org/drawingml/2006/picture",  # pic
        "urn:schemas-microsoft-com:office:word",  # w10
        "http://schemas.microsoft.com/office/word/2006/wordml",  # wne
    }
)

# --- Element and attribute names -----------------------------------------------------------

T_DOCUMENT: Final = _W + "document"
T_BACKGROUND: Final = _W + "background"
T_P: Final = _W + "p"
T_R: Final = _W + "r"
T_T: Final = _W + "t"
T_MATH_T: Final = "{" + MATH_NS + "}t"
TEXT_TAGS: Final = frozenset({T_T, T_MATH_T})
T_RPR: Final = _W + "rPr"
T_PPR: Final = _W + "pPr"
T_PSTYLE: Final = _W + "pStyle"
T_SHD: Final = _W + "shd"
T_SDT: Final = _W + "sdt"
T_SDT_PR: Final = _W + "sdtPr"
T_SDT_CONTENT: Final = _W + "sdtContent"
T_DATA_BINDING: Final = _W + "dataBinding"
T_FLD_CHAR: Final = _W + "fldChar"
T_FLD_SIMPLE: Final = _W + "fldSimple"
T_FF_DATA: Final = _W + "ffData"
T_SYM: Final = _W + "sym"
T_TXBX: Final = _W + "txbxContent"
T_TBL: Final = _W + "tbl"
T_TBL_PR: Final = _W + "tblPr"
T_TBL_STYLE: Final = _W + "tblStyle"
T_TR_PR: Final = _W + "trPr"
T_TC: Final = _W + "tc"
T_TC_PR: Final = _W + "tcPr"
T_DEL: Final = _W + "del"
T_SECT_PR: Final = _W + "sectPr"
T_HEADER_REF: Final = _W + "headerReference"
T_FOOTER_REF: Final = _W + "footerReference"
T_TITLE_PG: Final = _W + "titlePg"
T_FOOTNOTE: Final = _W + "footnote"
T_ENDNOTE: Final = _W + "endnote"
T_FOOTNOTE_REF: Final = _W + "footnoteReference"
T_ENDNOTE_REF: Final = _W + "endnoteReference"
T_DRAWING: Final = _W + "drawing"
T_PICT: Final = _W + "pict"
T_OBJECT: Final = _W + "object"
T_DOC_PR: Final = "{" + WP_NS + "}docPr"
T_GRAPHIC_DATA: Final = "{" + A_NS + "}graphicData"
T_TEXTPATH: Final = "{" + VML_NS + "}textpath"
T_ALTERNATE: Final = "{" + MC_NS + "}AlternateContent"
T_CHOICE: Final = "{" + MC_NS + "}Choice"
T_FALLBACK: Final = "{" + MC_NS + "}Fallback"
A_IGNORABLE: Final = "{" + MC_NS + "}Ignorable"
T_W14_CHECKBOX: Final = "{" + W14_NS + "}checkbox"
T_W14_CHECKED: Final = "{" + W14_NS + "}checked"
T_W14_CHECKED_STATE: Final = "{" + W14_NS + "}checkedState"
T_W14_UNCHECKED_STATE: Final = "{" + W14_NS + "}uncheckedState"
A_W14_VAL: Final = "{" + W14_NS + "}val"
A_R_ID: Final = "{" + R_NS + "}id"
A_TYPE: Final = _W + "type"
A_ID: Final = _W + "id"
A_DIRTY: Final = _W + "dirty"
SEPARATOR_NOTES: Final = frozenset({"separator", "continuationSeparator", "continuationNotice"})
# VML shapes that can carry ``style="visibility:hidden"``.
VML_SHAPES: Final = frozenset(
    "{" + VML_NS + "}" + name
    for name in (
        "shape",
        "rect",
        "roundrect",
        "oval",
        "line",
        "polyline",
        "arc",
        "curve",
        "group",
        "image",
        "textbox",
    )
)
_VML_HIDDEN: Final = re.compile(r"(?:^|;)\s*visibility\s*:\s*hidden\s*(?:;|$)", re.IGNORECASE)
_FORM_FIELD: Final = {
    _W + "checkBox": "checkbox",
    _W + "ddList": "dropdown",
    _W + "textInput": "text",
}

# Subtrees whose text a person does not see as document text.
SKIPPED: Final = frozenset(
    {
        T_DEL,
        _W + "moveFrom",
        _W + "sdtEndPr",
        _W + "instrText",
        _W + "delInstrText",
        _W + "fldData",
    }
)
# Characters that empty elements stand for.
CHARACTERS: Final = {
    _W + "tab": "\t",
    _W + "ptab": "\t",
    _W + "br": "\n",
    _W + "cr": "\n",
    _W + "noBreakHyphen": "-",
    _W + "softHyphen": "",
}

# --- Codes ----------------------------------------------------------------------------------

NOT_READ_ALTCHUNK: Final = "not_read_altchunk"
NOT_READ_OBJECT: Final = "not_read_object"
NOT_READ_SUBDOCUMENT: Final = "not_read_subdocument"
NOT_READ_DATA_BINDING: Final = "not_read_data_binding"
NOT_READ_SYMBOL: Final = "not_read_symbol"
NOT_READ_DIAGRAM: Final = "not_read_diagram"
NOT_READ_CHART: Final = "not_read_chart"
NOT_READ_WORDART: Final = "not_read_wordart"
NOT_READ: Final = {
    _W + "altChunk": NOT_READ_ALTCHUNK,
    "{" + OFFICE_NS + "}OLEObject": NOT_READ_OBJECT,
    _W + "subDoc": NOT_READ_SUBDOCUMENT,
    T_TEXTPATH: NOT_READ_WORDART,
}
GRAPHIC_URIS: Final = {
    "http://schemas.openxmlformats.org/drawingml/2006/diagram": NOT_READ_DIAGRAM,
    "http://schemas.openxmlformats.org/drawingml/2006/chart": NOT_READ_CHART,
    "http://schemas.microsoft.com/office/drawing/2014/chartex": NOT_READ_CHART,
}
BORDERLINE_TEXT: Final = "borderline_text"
FIELD_MAY_UPDATE: Final = "field_may_update"
NOT_DISPLAYED: Final = "not_displayed"
HIDDEN_OBJECT: Final = "hidden_object"
PAGE_NUMBER: Final = "page_number"
REPEATED_HEADER_FOOTER: Final = "repeated_header_footer"

# Items in ``removed`` and in ``warnings`` (the browser applies the same caps).
MAX_LIST_ITEMS: Final = 1000
# Verdicts of distinct run formats kept at once (the cache is cleared when full).
MAX_CACHED_VERDICTS: Final = 4096
# Characters of removed text kept for the sample; the rest is only counted.
HEAD_CHARS: Final = 2 * MAX_SAMPLE_CHARS

# --- Symbols (ADR 0009 Layer 1) -------------------------------------------------------------

CHECKED: Final = "☒"
UNCHECKED: Final = "☐"
CHECKBOX_GLYPHS: Final = "☐☑☒"
_SYMBOL_BASE: Final = 0xF000
_BYTE: Final = 0x100
# Wingdings checkbox glyphs (private-use code points).
WINGDINGS: Final = {0xF0FE: "☑", 0xF0FD: "☒", 0xF0A8: "☐", 0xF06F: "☐", 0xF078: "☒"}
# The Symbol font (Adobe Symbol encoding) for code points that differ from ASCII.
_SYMBOL_CHARS: Final = {
    0x22: "∀", 0x24: "∃", 0x27: "∋", 0x2A: "∗", 0x2D: "−", 0x40: "≅",
    0x41: "Α", 0x42: "Β", 0x43: "Χ", 0x44: "Δ", 0x45: "Ε", 0x46: "Φ", 0x47: "Γ", 0x48: "Η",
    0x49: "Ι", 0x4A: "ϑ", 0x4B: "Κ", 0x4C: "Λ", 0x4D: "Μ", 0x4E: "Ν", 0x4F: "Ο", 0x50: "Π",
    0x51: "Θ", 0x52: "Ρ", 0x53: "Σ", 0x54: "Τ", 0x55: "Υ", 0x56: "ς", 0x57: "Ω", 0x58: "Ξ",
    0x59: "Ψ", 0x5A: "Ζ", 0x5C: "∴", 0x5E: "⊥",
    0x61: "α", 0x62: "β", 0x63: "χ", 0x64: "δ", 0x65: "ε", 0x66: "φ", 0x67: "γ", 0x68: "η",
    0x69: "ι", 0x6A: "ϕ", 0x6B: "κ", 0x6C: "λ", 0x6D: "μ", 0x6E: "ν", 0x6F: "ο", 0x70: "π",
    0x71: "θ", 0x72: "ρ", 0x73: "σ", 0x74: "τ", 0x75: "υ", 0x76: "ϖ", 0x77: "ω", 0x78: "ξ",
    0x79: "ψ", 0x7A: "ζ", 0x7E: "∼",
    0xA0: "€", 0xA1: "ϒ", 0xA2: "′", 0xA3: "≤", 0xA4: "⁄", 0xA5: "∞", 0xA6: "ƒ", 0xA7: "♣",
    0xA8: "♦", 0xA9: "♥", 0xAA: "♠", 0xAB: "↔", 0xAC: "←", 0xAD: "↑", 0xAE: "→", 0xAF: "↓",
    0xB0: "°", 0xB1: "±", 0xB2: "″", 0xB3: "≥", 0xB4: "×", 0xB5: "∝", 0xB6: "∂", 0xB7: "•",
    0xB8: "÷", 0xB9: "≠", 0xBA: "≡", 0xBB: "≈", 0xBC: "…", 0xBF: "↵",
    0xC0: "ℵ", 0xC1: "ℑ", 0xC2: "ℜ", 0xC3: "℘", 0xC4: "⊗", 0xC5: "⊕", 0xC6: "∅", 0xC7: "∩",
    0xC8: "∪", 0xC9: "⊃", 0xCA: "⊇", 0xCB: "⊄", 0xCC: "⊂", 0xCD: "⊆", 0xCE: "∈", 0xCF: "∉",
    0xD0: "∠", 0xD1: "∇", 0xD2: "®", 0xD3: "©", 0xD4: "™", 0xD5: "∏", 0xD6: "√", 0xD7: "⋅",
    0xD8: "¬", 0xD9: "∧", 0xDA: "∨", 0xDB: "⇔", 0xDC: "⇐", 0xDD: "⇑", 0xDE: "⇒", 0xDF: "⇓",
    0xE0: "◊", 0xE1: "〈", 0xE2: "®", 0xE3: "©", 0xE4: "™", 0xE5: "∑", 0xF1: "〉", 0xF2: "∫",
}  # fmt: skip
SYMBOL: Final = {
    **{_SYMBOL_BASE + code: chr(code) for code in range(0x20, 0x7F)},
    **{_SYMBOL_BASE + code: char for code, char in _SYMBOL_CHARS.items()},
}
_FONT_TABLES: Final = {
    "wingdings": str.maketrans(WINGDINGS),
    "symbol": str.maketrans(SYMBOL),
}
_FONT_SYMBOLS: Final = {"wingdings": WINGDINGS, "symbol": SYMBOL}

# A header or footer line that holds only a page number ("7", "- 3 -", "Page 2 of 5").
_PAGE_NUMBER_LINE: Final = re.compile(
    r"[\s\-–—]*(?:(?:page|p\.|pg\.?|сторінка|стор\.?|страница|стр\.?)\s*)?\d{1,5}"
    r"(?:\s*(?:of|/|з|із|из)\s*\d{1,5})?[\s\-–—]*",
    re.IGNORECASE,
)
_SPACES: Final = re.compile(r"\s+")


# --- Result (header and footer filter, removed text, caps) ------------------------------------


class _Collector:
    """Turns paragraphs into blocks under the caps and records removed text (one
    item per span, ``count`` in characters) and warnings."""

    def __init__(self, *, max_chars: int, max_blocks: int) -> None:
        self.max_chars = max_chars
        self.max_blocks = max_blocks
        self.blocks: list[Block] = []
        self.chars = 0
        self.cleaner = ControlCleaner()
        self.removed: list[Removed] = []
        self.warnings: list[Warning] = []
        self.warned: set[str] = set()
        self.lines: dict[Part, set[str]] = {"header": set(), "footer": set()}

    def chars_left(self) -> int:
        return self.max_chars - self.chars

    def remove(self, reason: str, head: str, count: int) -> None:
        """One removed span: ``head`` is its start (for the sample), ``count`` its
        length in characters."""
        if count <= 0:
            return
        if len(self.removed) >= MAX_LIST_ITEMS:
            raise ExtractionError(TOO_MUCH_TEXT)
        cleaned = ControlCleaner().clean(head[:HEAD_CHARS])
        sample = _SPACES.sub(" ", cleaned).strip()[:MAX_SAMPLE_CHARS]
        self.removed.append(Removed(reason=reason, count=count, sample=sample))

    def warn(self, code: str, *, once: bool = True) -> None:
        if once:
            if code in self.warned:
                return
            self.warned.add(code)
        if len(self.warnings) >= MAX_LIST_ITEMS:
            raise ExtractionError(TOO_MUCH_TEXT)
        self.warnings.append(Warning(code=code, page=None))

    def paragraph(self, part: Part, text: str) -> None:
        text = self.cleaner.clean(text).strip()
        if not text:
            return
        lines = self.lines.get(part)
        if lines is not None:
            if _PAGE_NUMBER_LINE.fullmatch(text):
                self.remove(PAGE_NUMBER, text, len(text))
                return
            key = _SPACES.sub(" ", text).casefold()
            if key in lines:
                self.remove(REPEATED_HEADER_FOOTER, text, len(text))
                return
            lines.add(key)
        self.chars += len(text)
        if self.chars > self.max_chars or len(self.blocks) >= self.max_blocks:
            raise ExtractionError(TOO_MUCH_TEXT)
        self.blocks.append(Block(text=text, part=part, page=None))

    def removed_list(self) -> list[Removed]:
        out = self.removed + self.cleaner.removed()
        if len(out) > MAX_LIST_ITEMS:
            raise ExtractionError(TOO_MUCH_TEXT)
        return out


# --- Document state ------------------------------------------------------------------------


@dataclass
class _Section:
    """``w:sectPr``: header and footer references by (kind, type), ``w:titlePg``."""

    refs: dict[tuple[str, str], str] = field(default_factory=dict)
    title_page: bool = False


def displayed_header_ids(sections: list[_Section], *, even_and_odd: bool) -> set[str]:
    """Relationship ids of the headers and footers Word shows.

    A section without a reference of a type inherits the previous section's one.
    Default ones are shown; first-page ones only with ``w:titlePg`` in that
    section; even-page ones only with ``w:evenAndOddHeaders`` in the settings.
    """
    shown: set[str] = set()
    inherited: dict[tuple[str, str], str] = {}
    for section in sections:
        inherited = {**inherited, **section.refs}
        for (_, kind), rid in inherited.items():
            if (
                kind == "default"
                or (kind == "first" and section.title_page)
                or (kind == "even" and even_and_odd)
            ):
                shown.add(rid)
    return shown


class _Document:
    """State shared by all parts of one document."""

    def __init__(
        self, styles: Styles, theme: Theme, settings: DocSettings, collector: _Collector
    ) -> None:
        self.styles = styles
        self.theme = theme
        self.settings = settings
        self.collector = collector
        self.page = Color(WHITE)
        self.sections: list[_Section] = []
        self.note_refs: dict[Part, set[str]] = {"footnote": set(), "endnote": set()}
        self.verdicts: dict[tuple[object, ...], Verdict] = {}

    def field_seen(self, *, dirty: bool) -> None:
        if dirty or self.settings.update_fields:
            self.collector.warn(FIELD_MAY_UPDATE)


# --- The walker -----------------------------------------------------------------------------


@dataclass
class _Span:
    """Removed text: its reason, its length and the head kept for the sample."""

    reason: str
    count: int = 0
    head: list[str] = field(default_factory=list)
    head_size: int = 0
    # Leading and trailing whitespace, not counted.
    lead: int = 0
    tail: int = 0

    def add(self, text: str) -> None:
        if not self.head_size and text.isspace():
            self.lead += len(text)
            return
        self.count += len(text)
        stripped = len(text.rstrip())
        self.tail = self.tail + len(text) if not stripped else len(text) - stripped
        if self.head_size < HEAD_CHARS:
            piece = text[: HEAD_CHARS - self.head_size]
            self.head.append(piece)
            self.head_size += len(piece)

    def size(self) -> int:
        """Characters without leading and trailing whitespace."""
        return self.count - self.tail


@dataclass
class _Capture(_Span):
    """A subtree whose text is removed as a whole, up to the end of ``depth``."""

    depth: int = 0


@dataclass
class _Table:
    depth: int
    style: str | None = None
    shading: Any = None  # w:tblPr/w:shd


@dataclass
class _Paragraph:
    depth: int
    part: Part
    table: _Table | None = None
    cell_shading: Any = None
    pieces: list[str] = field(default_factory=list)
    size: int = 0
    style: str | None = None
    shading: Any = None
    run_depth: int = -1
    run_props: dict[str, object] = field(default_factory=dict)
    verdict: Verdict | None = None
    span: _Span | None = None
    borderline: bool = False


@dataclass
class _Sdt:
    depth: int
    checkbox: bool = False
    checked: bool = False
    glyphs: str = CHECKBOX_GLYPHS
    previous: _Sdt | None = None  # the checkbox control around this one

    def table(self) -> dict[int, str]:
        state = CHECKED if self.checked else UNCHECKED
        return str.maketrans(dict.fromkeys(self.glyphs, state))


@dataclass
class _FormField:
    kind: str = ""
    checked: bool | None = None
    default: bool | None = None
    result: int | None = None
    entries: list[str] = field(default_factory=list)

    def text(self) -> str:
        if self.kind == "checkbox":
            state = self.checked if self.checked is not None else bool(self.default)
            return CHECKED if state else UNCHECKED
        if self.kind == "dropdown":
            index = self.result or 0
            return self.entries[index] if 0 <= index < len(self.entries) else ""
        return ""


@dataclass
class _Field:
    result: bool = False
    legacy: _FormField | None = None


Watch = Callable[[Element], None]
Collect = Callable[[str, dict[str, str]], None]


class _PartWalker:
    """Walks one part of a document."""

    def __init__(
        self, document: _Document, part: Part, *, main: bool, notes: bool, displayed: bool
    ) -> None:
        self.document = document
        self.collector = document.collector
        self.main = main
        self.notes = notes
        self.parts: list[Part] = [part]
        self.paragraphs: list[_Paragraph] = []
        self.paragraph: _Paragraph | None = None
        self.skip = 0
        self.watch: Watch | None = None
        self.collect: Collect | None = None
        self.collect_depth = 0
        self.after_collect: Callable[[], None] | None = None
        self.section: _Section | None = None
        self.section_depth = 0
        self.code_fields = 0
        self.fields: list[_Field] = []
        self.sdts: list[_Sdt] = []
        self.checkbox: _Sdt | None = None
        self.tables: list[_Table] = []
        self.cell_shadings: list[tuple[int, Any]] = []
        self.alternates: list[bool] = []
        self.namespaces: dict[str, list[str]] = {}
        self.declared: dict[int, list[str]] = {}
        self.ignorable: dict[int, frozenset[str]] = {}
        self.unknown_ignorable: frozenset[str] = frozenset()
        self.tag_unknown: dict[str, bool] = {}
        self.note_ids: set[str] = set()
        # Text that is removed as a whole (a part or a note not displayed, a hidden
        # object).
        self.capture: _Capture | None = _Capture(NOT_DISPLAYED) if not displayed else None

    def walk(self, events: Iterator[tuple[str, Any]]) -> None:  # noqa: PLR0912, PLR0915 - the event loop is kept flat for speed
        depth = 0
        pending: list[tuple[str, str]] = []
        start_handlers = self._start_handlers
        end_handlers = self._end_handlers
        for event, item in events:
            if event == START:
                depth += 1
                if pending:
                    self._declare(depth, pending)
                    pending = []
                if self.skip:
                    self.skip += 1
                    if self.watch is not None:
                        self.watch(item)
                    continue
                if self.collect is not None:
                    if depth == self.collect_depth + 1:
                        if item.tag == T_SECT_PR:
                            self._open_section(depth)
                        else:
                            self.collect(item.tag, item.attrib)
                    elif self.section is not None and depth == self.section_depth + 1:
                        self._section_child(item.tag, item.attrib)
                    continue
                tag = item.tag
                if depth == 1:
                    self._check_root(tag)
                if A_IGNORABLE in item.attrib:
                    self._ignorable(depth, item.get(A_IGNORABLE))
                if self.unknown_ignorable and self._is_unknown_ignorable(tag):
                    self._skip(self._no_text)
                    continue
                handler = start_handlers.get(tag)
                if handler is not None:
                    handler(self, item, depth)
            elif event == END:
                if self.skip:
                    self.skip -= 1
                    if not self.skip:
                        self.watch = None
                elif self.collect is not None:
                    if depth == self.section_depth:
                        self.section = None
                        self.section_depth = 0
                    if depth == self.collect_depth:
                        self.collect = None
                        if self.after_collect is not None:
                            after, self.after_collect = self.after_collect, None
                            after()
                else:
                    handler = end_handlers.get(item.tag)
                    if handler is not None:
                        handler(self, item, depth)
                    capture = self.capture
                    if capture is not None and capture.depth == depth:
                        self._flush_capture()
                if self.declared and depth in self.declared:
                    for prefix in self.declared.pop(depth):
                        self.namespaces[prefix].pop()
                if self.ignorable and depth in self.ignorable:
                    del self.ignorable[depth]
                    self._update_ignorable()
                depth -= 1
            elif event == START_NS:
                pending.append(item)
        if self.fields:
            # A field that never ends would hide the rest of the part from the
            # reader, but not necessarily from the person: fail closed.
            raise suspicious()
        if self.capture is not None:
            self._flush_capture()

    # --- Helpers ---

    def _declare(self, depth: int, pending: list[tuple[str, str]]) -> None:
        for prefix, uri in pending:
            self.namespaces.setdefault(prefix, []).append(uri)
        self.declared[depth] = [prefix for prefix, _ in pending]

    def _uri(self, prefix: str) -> str | None:
        uris = self.namespaces.get(prefix)
        return uris[-1] if uris else None

    def _ignorable(self, depth: int, value: str | None) -> None:
        uris = {self._uri(prefix) for prefix in (value or "").split()}
        self.ignorable[depth] = frozenset(uri for uri in uris if uri is not None)
        self._update_ignorable()

    def _update_ignorable(self) -> None:
        every = frozenset().union(*self.ignorable.values()) if self.ignorable else frozenset()
        self.unknown_ignorable = every - KNOWN_NAMESPACES
        self.tag_unknown = {}

    def _is_unknown_ignorable(self, tag: str) -> bool:
        known = self.tag_unknown.get(tag)
        if known is None:
            uri = tag[1 : tag.index("}")] if tag.startswith("{") else ""
            known = self.tag_unknown[tag] = uri in self.unknown_ignorable
        return known

    @staticmethod
    def _no_text(item: Element) -> None:
        """An ignorable element we do not know must hold no text."""
        if item.tag in TEXT_TAGS:
            raise suspicious()

    def _check_root(self, tag: str) -> None:
        if tag.startswith(STRICT_PREFIX):
            raise ExtractionError(DOCX_STRICT_UNSUPPORTED)
        if self.main and tag != T_DOCUMENT:
            raise suspicious()

    def _skip(self, watch: Watch | None = None) -> None:
        self.skip = 1
        self.watch = watch

    def _start_capture(self, reason: str, depth: int) -> None:
        if self.capture is None:
            self.capture = _Capture(reason, depth=depth)

    def _flush_capture(self) -> None:
        capture = self.capture
        self.capture = None
        if capture is None:
            return
        self.collector.remove(capture.reason, "".join(capture.head), capture.size())

    def _warn(self, code: str) -> None:
        if self.capture is None:
            self.collector.warn(code)

    def _open_section(self, depth: int) -> None:
        if not self.main:
            return
        self.section = _Section()
        self.section_depth = depth
        self.document.sections.append(self.section)

    def _section_child(self, tag: str, attrib: dict[str, str]) -> None:
        section = self.section
        if section is None:
            return
        if tag in (T_HEADER_REF, T_FOOTER_REF):
            rid = attrib.get(A_R_ID)
            kind = (attrib.get(A_TYPE) or "default").strip()
            if rid is not None:
                section.refs[(tag, kind)] = rid.strip()
        elif tag == T_TITLE_PG:
            section.title_page = bool(on_off(attrib))

    # --- Formatting ---

    def _run_verdict(self) -> Verdict | None:
        paragraph = self.paragraph
        return None if paragraph is None else self._verdict(paragraph)

    def _verdict(self, paragraph: _Paragraph) -> Verdict:
        verdict = paragraph.verdict
        if verdict is not None:
            return verdict
        table = paragraph.table
        direct = paragraph.run_props
        key = (
            paragraph.style,
            paragraph.shading,
            paragraph.cell_shading,
            None if table is None else (table.style, table.shading),
            *sorted(direct.items()),
        )
        cache = self.document.verdicts
        verdict = cache.get(key)
        if verdict is None:
            verdict = self._judge(paragraph, direct)
            if len(cache) >= MAX_CACHED_VERDICTS:
                cache.clear()
            cache[key] = verdict
        paragraph.verdict = verdict
        return verdict

    def _judge(self, paragraph: _Paragraph, direct: dict[str, object]) -> Verdict:
        """Effective formatting: docDefaults → table style → paragraph style →
        character style → direct. ``w:vanish`` is a toggle property (ECMA-376
        17.7.3): the style layers are XORed, direct formatting sets the value."""
        styles = self.document.styles
        table = paragraph.table
        table_style = (
            styles.chain(styles.table_style(table.style), "table") if table is not None else None
        )
        para_style = styles.chain(styles.paragraph_style(paragraph.style), "paragraph")
        rstyle = direct.get("rstyle")
        char_style = styles.chain(rstyle if isinstance(rstyle, str) else None, "character")
        layers = [styles.defaults, para_style.rpr, char_style.rpr]
        if table_style is not None:
            layers.insert(1, table_style.rpr)
        props: dict[str, object] = {}
        vanish = False
        for layer in layers:
            props.update(layer)
            if layer.get("vanish") is True:
                vanish = not vanish
        props.update(direct)
        direct_vanish = direct.get("vanish")
        props["vanish"] = direct_vanish if isinstance(direct_vanish, bool) else vanish
        shading = paragraph.shading or para_style.shading or styles.default_shading
        background = Background(
            layers=(
                shading,
                paragraph.cell_shading,
                None if table is None else table.shading,
                None if table_style is None else table_style.cell_shading,
                None if table_style is None else table_style.table_shading,
            ),
            conditional=table_style is not None and table_style.conditional,
            conditional_fills=() if table_style is None else table_style.conditional_fills,
        )
        return judge(props, background, self.document.theme, self.document.page)

    def _close_span(self, paragraph: _Paragraph) -> None:
        span = paragraph.span
        if span is not None:
            paragraph.span = None
            self.collector.remove(span.reason, "".join(span.head), span.size())

    def _emit(self, text: str, *, symbol: bool = False) -> None:
        paragraph = self.paragraph
        if paragraph is None or self.code_fields or not text:
            return
        if self.capture is not None:
            self.capture.add(text)
            return
        verdict = self._verdict(paragraph)
        if verdict.font and not symbol:
            text = text.translate(_FONT_TABLES[verdict.font])
        if self.checkbox is not None:
            text = text.translate(self.checkbox.table())
        if verdict.reason is not None:
            span = paragraph.span
            if span is None or span.reason != verdict.reason:
                self._close_span(paragraph)
                span = paragraph.span = _Span(verdict.reason)
            span.add(text)
            return
        self._close_span(paragraph)
        paragraph.pieces.append(text)
        # The text cap fails early: a paragraph is not built beyond it.
        paragraph.size += len(text)
        if paragraph.size > self.collector.chars_left():
            raise ExtractionError(TOO_MUCH_TEXT)
        if text.isspace():
            return
        if verdict.borderline and not paragraph.borderline:
            self.collector.warn(BORDERLINE_TEXT, once=False)
        paragraph.borderline = verdict.borderline

    # --- Start handlers: paragraphs, runs, properties ---

    def _start_p(self, item: Element, depth: int) -> None:
        paragraph = _Paragraph(
            depth=depth,
            part=self.parts[-1],
            table=self.tables[-1] if self.tables else None,
            cell_shading=self.cell_shadings[-1][1] if self.cell_shadings else None,
        )
        self.paragraphs.append(paragraph)
        self.paragraph = paragraph

    def _start_r(self, item: Element, depth: int) -> None:
        paragraph = self.paragraph
        if paragraph is not None:
            paragraph.run_depth = depth
            paragraph.run_props = {}
            paragraph.verdict = None

    def _start_rpr(self, item: Element, depth: int) -> None:
        paragraph = self.paragraph
        if paragraph is None or depth != paragraph.run_depth + 1:
            self._skip()
            return
        props = paragraph.run_props

        def collect(tag: str, attrib: dict[str, str]) -> None:
            read_run_property(tag, attrib, props)

        paragraph.verdict = None
        self.collect = collect
        self.collect_depth = depth

    def _start_ppr(self, item: Element, depth: int) -> None:
        paragraph = self.paragraph
        if paragraph is None or depth != paragraph.depth + 1:
            self._skip()
            return

        def collect(tag: str, attrib: dict[str, str]) -> None:
            if tag == T_PSTYLE:
                paragraph.style = attrib.get(VAL)
            elif tag == T_SHD:
                paragraph.shading = shade_spec(attrib)

        self.collect = collect
        self.collect_depth = depth

    def _start_character(self, item: Element, depth: int) -> None:
        self._emit(CHARACTERS[item.tag])

    # --- Tables ---

    def _start_tbl(self, item: Element, depth: int) -> None:
        self.tables.append(_Table(depth))

    def _start_tbl_pr(self, item: Element, depth: int) -> None:
        if not self.tables or self.tables[-1].depth != depth - 1:
            self._skip()
            return
        table = self.tables[-1]

        def collect(tag: str, attrib: dict[str, str]) -> None:
            if tag == T_TBL_STYLE:
                table.style = attrib.get(VAL)
            elif tag == T_SHD:
                table.shading = shade_spec(attrib)

        self.collect = collect
        self.collect_depth = depth

    def _start_tr_pr(self, item: Element, depth: int) -> None:
        deleted = False

        def collect(tag: str, attrib: dict[str, str]) -> None:
            nonlocal deleted
            if tag == T_DEL:
                deleted = True

        def after() -> None:
            # A row deleted with tracked changes is excluded like w:del: skip the
            # rest of the row (w:trPr is its first child).
            if deleted:
                self._skip()

        self.collect = collect
        self.collect_depth = depth
        self.after_collect = after

    def _start_tc(self, item: Element, depth: int) -> None:
        self.cell_shadings.append((depth, None))

    def _start_tc_pr(self, item: Element, depth: int) -> None:
        if not self.cell_shadings or self.cell_shadings[-1][0] != depth - 1:
            self._skip()
            return
        cell_depth = self.cell_shadings[-1][0]

        def collect(tag: str, attrib: dict[str, str]) -> None:
            if tag == T_SHD:
                self.cell_shadings[-1] = (cell_depth, shade_spec(attrib))

        self.collect = collect
        self.collect_depth = depth

    # --- Sections and notes ---

    def _start_sect_pr(self, item: Element, depth: int) -> None:
        if not self.main:
            self._skip()
            return
        self._open_section(depth)
        self.collect = self._section_child
        self.collect_depth = depth

    def _start_note(self, item: Element, depth: int) -> None:
        if not self.notes or depth != 2:  # noqa: PLR2004 - w:footnotes/w:footnote
            return
        kind = (item.get(A_TYPE) or "normal").strip()
        note_id = (item.get(A_ID) or "").strip()
        if note_id in self.note_ids:
            raise suspicious()
        self.note_ids.add(note_id)
        if self.capture is not None:
            return
        refs = self.document.note_refs.get(self.parts[0], set())
        if kind in SEPARATOR_NOTES or note_id not in refs:
            self._start_capture(NOT_DISPLAYED, depth)

    def _start_note_ref(self, item: Element, depth: int) -> None:
        paragraph = self.paragraph
        if paragraph is None or self.code_fields or self.capture is not None:
            return
        if self._verdict(paragraph).reason is not None:
            return
        note_id = item.get(A_ID)
        if note_id is not None:
            part: Part = "footnote" if item.tag == T_FOOTNOTE_REF else "endnote"
            self.document.note_refs[part].add(note_id.strip())

    # --- Symbols, fields, controls ---

    def _start_sym(self, item: Element, depth: int) -> None:
        verdict = self._run_verdict()
        if verdict is None:
            return
        font = (item.get(_W + "font") or "").strip().casefold()
        try:
            code = int(item.get(_W + "char") or "", 16)
        except ValueError:
            code = -1
        if 0 <= code < _BYTE:
            code += _SYMBOL_BASE
        glyph = _FONT_SYMBOLS.get(font, {}).get(code)
        if glyph is None:
            if verdict.reason is None:
                self._warn(NOT_READ_SYMBOL)
            return
        self._emit(glyph, symbol=True)

    def _start_field(self, item: Element, depth: int) -> None:
        kind = (item.get(_W + "fldCharType") or "").strip()
        fields = self.fields
        if kind == "begin":
            fields.append(_Field())
            self.code_fields += 1
            self.document.field_seen(dirty=bool(on_off({VAL: item.get(A_DIRTY) or "0"})))
        elif kind == "separate":
            if fields and not fields[-1].result:
                fields[-1].result = True
                self.code_fields -= 1
                self._emit_form(fields[-1])
        elif kind == "end" and fields:
            ended = fields.pop()
            if not ended.result:
                self.code_fields -= 1
                self._emit_form(ended)

    def _emit_form(self, ended: _Field) -> None:
        form = ended.legacy
        if form is not None:
            ended.legacy = None
            self._emit(form.text(), symbol=True)

    def _start_ff_data(self, item: Element, depth: int) -> None:
        if not self.fields:
            self._skip()
            return
        form = self.fields[-1].legacy = _FormField()

        def watch(child: Element) -> None:
            tag = child.tag
            kind = _FORM_FIELD.get(tag)
            if kind is not None:
                form.kind = kind
            elif tag == _W + "checked":
                form.checked = on_off(child.attrib)
            elif tag == _W + "default" and form.kind == "checkbox":
                form.default = on_off(child.attrib)
            elif tag == _W + "result":
                try:
                    form.result = int(child.get(VAL) or "0")
                except ValueError:
                    form.result = -1
            elif tag == _W + "listEntry":
                form.entries.append(child.get(VAL) or "")

        self._skip(watch)

    def _start_fld_simple(self, item: Element, depth: int) -> None:
        self.document.field_seen(dirty=bool(on_off({VAL: item.get(A_DIRTY) or "0"})))

    def _start_sdt(self, item: Element, depth: int) -> None:
        self.sdts.append(_Sdt(depth=depth))

    def _start_sdt_pr(self, item: Element, depth: int) -> None:
        sdt = self.sdts[-1] if self.sdts and self.sdts[-1].depth == depth - 1 else None

        def watch(child: Element) -> None:
            tag = child.tag
            if tag == T_DATA_BINDING:
                self._warn(NOT_READ_DATA_BINDING)
            elif sdt is None:
                return
            elif tag == T_W14_CHECKBOX:
                sdt.checkbox = True
            elif tag == T_W14_CHECKED:
                value = child.get(A_W14_VAL)
                sdt.checked = bool(on_off({VAL: value} if value is not None else {}))
            elif tag in (T_W14_CHECKED_STATE, T_W14_UNCHECKED_STATE):
                with contextlib.suppress(ValueError, OverflowError):
                    sdt.glyphs += chr(int(child.get(A_W14_VAL) or "", 16))

        self._skip(watch)

    def _start_sdt_content(self, item: Element, depth: int) -> None:
        sdt = self.sdts[-1] if self.sdts else None
        if sdt is not None and sdt.checkbox:
            # A checkbox control: its glyphs show the state (ADR 0009 Layer 1).
            sdt.previous = self.checkbox
            self.checkbox = sdt

    def _end_sdt(self, item: Element, depth: int) -> None:
        if self.sdts:
            sdt = self.sdts.pop()
            if self.checkbox is sdt:
                self.checkbox = sdt.previous

    # --- Text boxes, objects, markup compatibility ---

    def _start_txbx(self, item: Element, depth: int) -> None:
        self.parts.append("textbox")

    def _start_object(self, item: Element, depth: int) -> None:
        """``w:drawing``, ``w:pict``, ``w:object``: removed with a hidden run."""
        verdict = self._run_verdict()
        if verdict is not None and verdict.reason is not None:
            self._start_capture(verdict.reason, depth)
        elif item.tag == T_OBJECT:
            self._warn(NOT_READ_OBJECT)

    def _start_vml_shape(self, item: Element, depth: int) -> None:
        style = item.get("style")
        if style and _VML_HIDDEN.search(style):
            self._start_capture(HIDDEN_OBJECT, depth)

    def _start_doc_pr(self, item: Element, depth: int) -> None:
        hidden = item.get("hidden")
        if hidden is not None and on_off({VAL: hidden}):
            # w:drawing/wp:anchor/wp:docPr: the whole anchor or inline object.
            self._start_capture(HIDDEN_OBJECT, depth - 1)

    def _start_graphic_data(self, item: Element, depth: int) -> None:
        code = GRAPHIC_URIS.get((item.get("uri") or "").strip())
        if code is not None:
            self._warn(code)

    def _start_alternate(self, item: Element, depth: int) -> None:
        self.alternates.append(False)

    def _start_choice(self, item: Element, depth: int) -> None:
        if not self.alternates or self.alternates[-1]:
            self._skip()
            return
        prefixes = (item.get("Requires") or "").split()
        if not prefixes or any(self._uri(p) not in REQUIRES_ALLOWED for p in prefixes):
            raise suspicious()
        self.alternates[-1] = True

    def _start_fallback(self, item: Element, depth: int) -> None:
        if not self.alternates or self.alternates[-1]:
            self._skip()
            return
        self.alternates[-1] = True

    def _start_not_read(self, item: Element, depth: int) -> None:
        self._warn(NOT_READ[item.tag])

    def _start_skipped(self, item: Element, depth: int) -> None:
        self._skip()

    def _start_background(self, item: Element, depth: int) -> None:
        if depth != 2 or not self.document.settings.display_background:  # noqa: PLR2004
            return
        color = self.document.theme.resolve(
            color_spec({**item.attrib, VAL: item.get(_W + "color") or ""})
        )
        if color is None or color.hex == AUTO:
            return
        self.document.page = color

    # --- End handlers ---

    def _end_t(self, item: Element, depth: int) -> None:
        text = item.text
        if text:
            self._emit(text)

    def _end_p(self, item: Element, depth: int) -> None:
        paragraph = self.paragraphs.pop()
        self.paragraph = self.paragraphs[-1] if self.paragraphs else None
        self._close_span(paragraph)
        if self.capture is not None:
            self.capture.add("\n")
            return
        self.collector.paragraph(paragraph.part, "".join(paragraph.pieces))

    def _end_r(self, item: Element, depth: int) -> None:
        paragraph = self.paragraph
        if paragraph is not None and paragraph.run_depth == depth:
            paragraph.run_depth = -1
            paragraph.run_props = {}
            paragraph.verdict = None

    def _end_tbl(self, item: Element, depth: int) -> None:
        if self.tables and self.tables[-1].depth == depth:
            self.tables.pop()

    def _end_tc(self, item: Element, depth: int) -> None:
        if self.cell_shadings and self.cell_shadings[-1][0] == depth:
            self.cell_shadings.pop()

    def _end_txbx(self, item: Element, depth: int) -> None:
        if len(self.parts) > 1:
            self.parts.pop()

    def _end_alternate(self, item: Element, depth: int) -> None:
        if self.alternates:
            self.alternates.pop()

    _Handler = Callable[["_PartWalker", Element, int], None]
    _start_handlers: Final[dict[str, _Handler]] = {
        T_P: _start_p,
        T_R: _start_r,
        T_RPR: _start_rpr,
        T_PPR: _start_ppr,
        T_TBL: _start_tbl,
        T_TBL_PR: _start_tbl_pr,
        T_TR_PR: _start_tr_pr,
        T_TC: _start_tc,
        T_TC_PR: _start_tc_pr,
        T_SECT_PR: _start_sect_pr,
        T_FOOTNOTE: _start_note,
        T_ENDNOTE: _start_note,
        T_FOOTNOTE_REF: _start_note_ref,
        T_ENDNOTE_REF: _start_note_ref,
        T_SYM: _start_sym,
        T_FLD_CHAR: _start_field,
        T_FF_DATA: _start_ff_data,
        T_FLD_SIMPLE: _start_fld_simple,
        T_SDT: _start_sdt,
        T_SDT_PR: _start_sdt_pr,
        T_SDT_CONTENT: _start_sdt_content,
        T_TXBX: _start_txbx,
        T_DRAWING: _start_object,
        T_PICT: _start_object,
        T_OBJECT: _start_object,
        T_DOC_PR: _start_doc_pr,
        T_GRAPHIC_DATA: _start_graphic_data,
        T_ALTERNATE: _start_alternate,
        T_CHOICE: _start_choice,
        T_FALLBACK: _start_fallback,
        T_BACKGROUND: _start_background,
        **dict.fromkeys(VML_SHAPES, _start_vml_shape),
        **dict.fromkeys(CHARACTERS, _start_character),
        **dict.fromkeys(NOT_READ, _start_not_read),
        **dict.fromkeys(SKIPPED, _start_skipped),
    }
    _end_handlers: Final[dict[str, _Handler]] = {
        T_T: _end_t,
        T_MATH_T: _end_t,
        T_P: _end_p,
        T_R: _end_r,
        T_TBL: _end_tbl,
        T_TC: _end_tc,
        T_SDT: _end_sdt,
        T_TXBX: _end_txbx,
        T_ALTERNATE: _end_alternate,
    }


# --- Entry point -------------------------------------------------------------------------------


def extract_docx(
    data: bytes,
    *,
    max_chars: int = DEFAULT_MAX_TEXT_CHARS,
    max_blocks: int = DEFAULT_MAX_BLOCKS,
    limits: DocxLimits,
) -> ExtractionResult:
    archive = DocxArchive(
        data, max_part_bytes=limits.max_part_bytes, max_total_bytes=limits.max_total_bytes
    )
    reader = Reader(
        archive, XmlBudget(max_depth=limits.max_xml_depth, max_elements=limits.max_elements)
    )
    parts = resolve_package(reader)
    single = parts.single
    styles = parse_styles(reader.events(single["styles"])) if "styles" in single else Styles()
    settings = (
        parse_settings(reader.events(single["settings"])) if "settings" in single else DocSettings()
    )
    theme = Theme(mapping=settings.color_mapping)
    if "theme" in single:
        theme.scheme = parse_theme(reader.events(single["theme"]))
        theme.present = True
    collector = _Collector(max_chars=max_chars, max_blocks=max_blocks)
    document = _Document(styles, theme, settings, collector)

    def walk(entry: ZipEntry, part: Part, **kwargs: bool) -> None:
        options = {"main": False, "notes": False, "displayed": True, **kwargs}
        _PartWalker(document, part, **options).walk(reader.events(entry))

    # Body first (sections and note references), then headers and footers (note
    # references too), then the notes.
    walk(parts.main, "body", main=True)
    shown = displayed_header_ids(document.sections, even_and_odd=settings.even_and_odd_headers)
    for header in parts.headers:
        walk(header.entry, header.part, displayed=bool(header.rids & shown))
    for label, entry in parts.notes:
        walk(entry, label, notes=True)
    if not collector.blocks:
        raise ExtractionError(NO_TEXT_EXTRACTED)
    return ExtractionResult(
        kind="docx",
        bytes=len(data),
        language=detect_language("\n".join(block.text for block in collector.blocks)),
        pages=None,
        blocks=collector.blocks,
        ocr_pages=[],
        removed=collector.removed_list(),
        warnings=collector.warnings,
    )
