# ruff: noqa: RUF001 - checkbox glyphs are the point of the symbol table
"""DOCX extraction (S3-T2; ADR 0004 revision, ADR 0009 Layer 0 and Layer 1; T4, T5, T11).

``extract_docx`` is pure and runs inside the parsing child (ADR 0011).

1. The archive is checked as a whole before any part is read (``docx_zip``):
   failures are ``archive_rejected``.
2. The package is resolved the way Word resolves it (``_resolve_package``): the
   main part is the target of the single ``officeDocument`` relationship in
   ``_rels/.rels``; styles, footnotes, endnotes, headers and footers are targets of
   the main part's relationships only. Every XML part is parsed with ``defusedxml``
   and ``forbid_dtd=True`` (``docx_xml``).
3. The walker (``_Walker``) reads what the person reads, one block per paragraph,
   with hidden text removed by effective formatting (``docx_styles``) and material
   content that is not read reported as warnings.
4. The shared text normalization (``normalize``), the header and footer filter,
   the caps of S3-T1 and language detection give the result.

Errors carry a code only, never text, names or offsets.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any, Final
from urllib.parse import urlsplit
from xml.etree.ElementTree import Element

from app.extraction.detect import UNSUPPORTED_TYPE
from app.extraction.docx_styles import (
    AUTO,
    VAL,
    WHITE,
    StyleDef,
    Styles,
    Verdict,
    W,
    judge,
    on_off,
    read_run_property,
    shading_fill,
)
from app.extraction.docx_xml import END, START, START_NS, XmlBudget, iter_xml, suspicious
from app.extraction.docx_zip import DocxArchive, ZipEntry, part_key
from app.extraction.language import detect_language
from app.extraction.model import (
    DEFAULT_MAX_BLOCKS,
    DEFAULT_MAX_TEXT_CHARS,
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

MIB: Final = 1024 * 1024


@dataclass(frozen=True)
class DocxLimits:
    max_part_bytes: int = 32 * MIB
    max_total_bytes: int = 100 * MIB
    max_xml_depth: int = 256
    max_elements: int = 2_000_000


# --- Namespaces, relationship and content types ----------------------------------------

_W: Final = "{" + W + "}"
R_NS: Final = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS: Final = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS: Final = "http://schemas.openxmlformats.org/package/2006/content-types"
MC_NS: Final = "http://schemas.openxmlformats.org/markup-compatibility/2006"
W14_NS: Final = "http://schemas.microsoft.com/office/word/2010/wordml"
MATH_NS: Final = "http://schemas.openxmlformats.org/officeDocument/2006/math"
STRICT_PREFIX: Final = "{http://purl.oclc.org/ooxml/"

REL_OFFICE_DOCUMENT: Final = R_NS + "/officeDocument"
REL_OFFICE_DOCUMENT_STRICT: Final = (
    "http://purl.oclc.org/ooxml/officeDocument/relationships/officeDocument"
)
REL_STYLES: Final = R_NS + "/styles"
REL_FOOTNOTES: Final = R_NS + "/footnotes"
REL_ENDNOTES: Final = R_NS + "/endnotes"
REL_HEADER: Final = R_NS + "/header"
REL_FOOTER: Final = R_NS + "/footer"
REL_SETTINGS: Final = R_NS + "/settings"

CT_MAIN: Final = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
CT_UNSUPPORTED: Final = frozenset(
    {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml",
        "application/vnd.ms-word.document.macroenabled.main+xml",
        "application/vnd.ms-word.template.macroenabledtemplate.main+xml",
    }
)

# Namespaces whose markup the walker reads inside ``mc:Choice`` (``Requires``).
KNOWN_NAMESPACES: Final = frozenset(
    {
        W,
        R_NS,
        MC_NS,
        MATH_NS,
        W14_NS,
        "http://schemas.microsoft.com/office/word/2012/wordml",  # w15
        "http://schemas.microsoft.com/office/word/2010/wordprocessingShape",  # wps
        "http://schemas.microsoft.com/office/word/2010/wordprocessingGroup",  # wpg
        "http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas",  # wpc
        "http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing",  # wp14
        "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",  # wp
        "http://schemas.openxmlformats.org/drawingml/2006/main",  # a
        "http://schemas.microsoft.com/office/drawing/2010/main",  # a14
        "http://schemas.openxmlformats.org/drawingml/2006/picture",  # pic
        "urn:schemas-microsoft-com:vml",  # v
        "urn:schemas-microsoft-com:office:office",  # o
        "urn:schemas-microsoft-com:office:word",  # w10
    }
)

# --- Element names -------------------------------------------------------------------

T_DOCUMENT: Final = _W + "document"
T_BACKGROUND: Final = _W + "background"
T_P: Final = _W + "p"
T_R: Final = _W + "r"
T_T: Final = _W + "t"
T_MATH_T: Final = "{" + MATH_NS + "}t"
T_RPR: Final = _W + "rPr"
T_PPR: Final = _W + "pPr"
T_PSTYLE: Final = _W + "pStyle"
T_SHD: Final = _W + "shd"
T_SDT: Final = _W + "sdt"
T_SDT_PR: Final = _W + "sdtPr"
T_SDT_CONTENT: Final = _W + "sdtContent"
T_FLD_CHAR: Final = _W + "fldChar"
T_SYM: Final = _W + "sym"
T_TXBX: Final = _W + "txbxContent"
T_TBL: Final = _W + "tbl"
T_TBL_PR: Final = _W + "tblPr"
T_TBL_STYLE: Final = _W + "tblStyle"
T_SECT_PR: Final = _W + "sectPr"
T_HEADER_REF: Final = _W + "headerReference"
T_FOOTER_REF: Final = _W + "footerReference"
T_TITLE_PG: Final = _W + "titlePg"
T_EVEN_ODD: Final = _W + "evenAndOddHeaders"
T_FOOTNOTE: Final = _W + "footnote"
T_ENDNOTE: Final = _W + "endnote"
T_FOOTNOTE_REF: Final = _W + "footnoteReference"
T_ENDNOTE_REF: Final = _W + "endnoteReference"
A_R_ID: Final = "{" + R_NS + "}id"
A_TYPE: Final = _W + "type"
A_ID: Final = _W + "id"
SEPARATOR_NOTES: Final = frozenset({"separator", "continuationSeparator", "continuationNotice"})
T_STYLE: Final = _W + "style"
T_BASED_ON: Final = _W + "basedOn"
T_RPR_DEFAULT: Final = _W + "rPrDefault"
T_PPR_DEFAULT: Final = _W + "pPrDefault"
T_ALTERNATE: Final = "{" + MC_NS + "}AlternateContent"
T_CHOICE: Final = "{" + MC_NS + "}Choice"
T_FALLBACK: Final = "{" + MC_NS + "}Fallback"
T_W14_CHECKBOX: Final = "{" + W14_NS + "}checkbox"
T_W14_CHECKED: Final = "{" + W14_NS + "}checked"
A_W14_VAL: Final = "{" + W14_NS + "}val"
T_CT_DEFAULT: Final = "{" + CT_NS + "}Default"
T_CT_OVERRIDE: Final = "{" + CT_NS + "}Override"
T_RELATIONSHIP: Final = "{" + REL_NS + "}Relationship"

# Subtrees whose text a person does not see as document text.
SKIPPED: Final = frozenset(
    {
        _W + "del",
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

NOT_READ_ALTCHUNK: Final = "not_read_altchunk"
NOT_READ_OBJECT: Final = "not_read_object"
NOT_READ_SUBDOCUMENT: Final = "not_read_subdocument"
NOT_READ: Final = {
    _W + "altChunk": NOT_READ_ALTCHUNK,
    _W + "object": NOT_READ_OBJECT,
    "{urn:schemas-microsoft-com:office:office}OLEObject": NOT_READ_OBJECT,
    _W + "subDoc": NOT_READ_SUBDOCUMENT,
}
BORDERLINE_TEXT: Final = "borderline_text"
NOT_DISPLAYED: Final = "not_displayed"
# Items in ``removed`` and in ``warnings`` (the browser applies the same caps).
MAX_LIST_ITEMS: Final = 1000
# Verdicts of distinct run formats kept at once (the cache is cleared when full).
MAX_CACHED_VERDICTS: Final = 4096
PAGE_NUMBER: Final = "page_number"
REPEATED_HEADER_FOOTER: Final = "repeated_header_footer"

# Wingdings checkbox glyphs (private-use code points, ADR 0009 Layer 1).
WINGDINGS: Final = {0xF0FE: "☑", 0xF0FD: "☒", 0xF0A8: "☐", 0xF06F: "☐", 0xF078: "☒"}
_WINGDINGS_TABLE: Final = str.maketrans(WINGDINGS)
_SYMBOL_BASE: Final = 0xF000
_BYTE: Final = 0x100
CHECKED: Final = "☒"
UNCHECKED: Final = "☐"

# A header or footer line that holds only a page number ("7", "- 3 -", "Page 2 of 5").
_PAGE_NUMBER_LINE: Final = re.compile(
    r"[\s\-–—]*(?:(?:page|p\.|pg\.?|сторінка|стор\.?|страница|стр\.?)\s*)?\d{1,5}"
    r"(?:\s*(?:of|/|з|із|из)\s*\d{1,5})?[\s\-–—]*",
    re.IGNORECASE,
)
_SPACES: Final = re.compile(r"\s+")


# --- Package resolution (AC3) --------------------------------------------------------------


@dataclass(frozen=True)
class _Rel:
    rid: str
    type: str
    target: str
    external: bool


@dataclass
class _HeaderPart:
    part: Part
    entry: ZipEntry
    rids: set[str]


@dataclass
class _Parts:
    main: ZipEntry
    styles: ZipEntry | None = None
    settings: ZipEntry | None = None
    notes: list[tuple[Part, ZipEntry]] = field(default_factory=list)
    headers: list[_HeaderPart] = field(default_factory=list)


def _rels_name(part: str) -> str:
    folder, _, base = part.rpartition("/")
    return f"{folder}/_rels/{base}.rels" if folder else f"_rels/{base}.rels"


def _resolve_target(source: str, rel: _Rel) -> str:
    """The part name of an internal target, relative to the source part's folder.

    External targets, URIs with a scheme, authority, query or fragment, empty
    segments and paths that leave the package are ``suspicious_package``.
    """
    if rel.external:
        raise suspicious()
    split = urlsplit(rel.target)
    if split.scheme or split.netloc or split.query or split.fragment or "\\" in rel.target:
        raise suspicious()
    path = split.path
    folder = source.rpartition("/")[0]
    joined = path[1:] if path.startswith("/") else (f"{folder}/{path}" if folder else path)
    segments: list[str] = []
    for segment in joined.split("/"):
        if segment == "..":
            if not segments:
                raise suspicious()
            segments.pop()
        elif not segment:
            raise suspicious()
        elif segment != ".":
            segments.append(segment)
    if not segments:
        raise suspicious()
    return "/".join(segments)


class _Reader:
    """Parses the XML parts of one archive under one budget."""

    def __init__(self, archive: DocxArchive, budget: XmlBudget) -> None:
        self.archive = archive
        self.budget = budget

    def entry(self, name: str) -> ZipEntry | None:
        return self.archive.get(part_key(name))

    def events(self, entry: ZipEntry) -> Iterator[tuple[str, Any]]:
        return iter_xml(self.archive.open(entry), self.budget)

    def content_types(self) -> tuple[dict[str, str], dict[str, str]]:
        entry = self.entry("[Content_Types].xml")
        if entry is None:
            raise suspicious()
        defaults: dict[str, str] = {}
        overrides: dict[str, str] = {}
        for event, item in self.events(entry):
            if event != START:
                continue
            if item.tag == T_CT_DEFAULT:
                extension = item.get("Extension")
                content_type = item.get("ContentType")
                if extension is not None and content_type is not None:
                    defaults.setdefault(extension.casefold(), content_type.strip().casefold())
            elif item.tag == T_CT_OVERRIDE:
                name = item.get("PartName")
                content_type = item.get("ContentType")
                if name is not None and content_type is not None:
                    key = part_key(name.removeprefix("/"))
                    overrides.setdefault(key, content_type.strip().casefold())
        return defaults, overrides

    def rels(self, part: str) -> list[_Rel]:
        entry = self.entry(_rels_name(part))
        if entry is None:
            return []
        out: list[_Rel] = []
        for event, item in self.events(entry):
            if event == START and item.tag == T_RELATIONSHIP:
                rel_type = item.get("Type")
                target = item.get("Target")
                if rel_type is None or target is None:
                    raise suspicious()
                mode = (item.get("TargetMode") or "Internal").strip().casefold()
                rid = (item.get("Id") or "").strip()
                out.append(_Rel(rid, rel_type.strip(), target.strip(), mode == "external"))
        return out


def _main_part(reader: _Reader) -> str:
    office = [
        rel
        for rel in reader.rels("")
        if rel.type in (REL_OFFICE_DOCUMENT, REL_OFFICE_DOCUMENT_STRICT)
    ]
    if len(office) != 1:
        raise suspicious()
    if office[0].type == REL_OFFICE_DOCUMENT_STRICT:
        raise ExtractionError(DOCX_STRICT_UNSUPPORTED)
    return _resolve_target("", office[0])


def _check_content_type(reader: _Reader, main: str) -> None:
    defaults, overrides = reader.content_types()
    key = part_key(main)
    content_type = overrides.get(key)
    if content_type is None:
        extension = key.rpartition("/")[2].rpartition(".")
        content_type = defaults.get(extension[2]) if extension[1] else None
    if content_type == CT_MAIN:
        return
    if content_type in CT_UNSUPPORTED:
        raise ExtractionError(UNSUPPORTED_TYPE)
    raise suspicious()


# Relationship types of the main part that are read; the rest are ignored.
_FOLLOWED: Final[dict[str, str]] = {
    REL_STYLES: "styles",
    REL_SETTINGS: "settings",
    REL_FOOTNOTES: "footnote",
    REL_ENDNOTES: "endnote",
    REL_HEADER: "header",
    REL_FOOTER: "footer",
}
_PART_LABELS: Final[dict[str, Part]] = {
    "footnote": "footnote",
    "endnote": "endnote",
    "header": "header",
    "footer": "footer",
}


def _resolve_package(reader: _Reader) -> _Parts:  # noqa: PLR0912 - one branch per check
    main = _main_part(reader)
    _check_content_type(reader, main)
    entry = reader.entry(main)
    if entry is None:
        raise suspicious()
    decoy = reader.entry("word/document.xml")
    if decoy is not None and decoy is not entry:
        raise suspicious()
    parts = _Parts(main=entry)
    seen: dict[str, str] = {}
    headers: dict[str, _HeaderPart] = {}
    for rel in reader.rels(main):
        label = _FOLLOWED.get(rel.type)
        if label is None:
            continue
        name = _resolve_target(main, rel)
        target = reader.entry(name)
        if target is None or target is entry:
            raise suspicious()
        key = part_key(name)
        if key in seen:
            if seen[key] != label:
                raise suspicious()
            if key in headers:
                headers[key].rids.add(rel.rid)
            continue  # the same part twice is read once
        seen[key] = label
        if label == "styles":
            if parts.styles is not None:
                raise suspicious()
            parts.styles = target
        elif label == "settings":
            if parts.settings is not None:
                raise suspicious()
            parts.settings = target
        elif label in ("footnote", "endnote"):
            if any(existing == label for existing, _ in parts.notes):
                raise suspicious()
            parts.notes.append((_PART_LABELS[label], target))
        else:
            headers[key] = _HeaderPart(_PART_LABELS[label], target, {rel.rid})
            parts.headers.append(headers[key])
    # Footnotes before endnotes, headers before footers; relationship order otherwise.
    parts.notes.sort(key=lambda item: item[0] != "footnote")
    parts.headers.sort(key=lambda item: item.part != "header")
    return parts


def _even_and_odd_headers(events: Iterator[tuple[str, Any]]) -> bool:
    """``w:settings/w:evenAndOddHeaders`` of the main part's settings part."""
    depth = 0
    found = False
    for event, item in events:
        if event == START:
            depth += 1
            if depth == 2 and item.tag == T_EVEN_ODD:  # noqa: PLR2004 - w:settings/*
                found = bool(on_off(item.attrib))
        elif event == END:
            depth -= 1
    return found


# --- Styles ------------------------------------------------------------------------------------


def _parse_styles(events: Iterator[tuple[str, Any]]) -> Styles:  # noqa: PLR0912 - one branch per element
    styles = Styles()
    depth = 0
    collect: Callable[[str, dict[str, str]], None] | None = None
    collect_depth = 0
    current: StyleDef | None = None
    current_id: str | None = None
    defaults_kind: str | None = None
    for event, item in events:
        if event == START:
            depth += 1
            tag = item.tag
            if collect is not None:
                if depth == collect_depth + 1:
                    collect(tag, item.attrib)
                continue
            if depth == 2 and tag == T_STYLE:  # noqa: PLR2004 - w:styles/w:style
                current = StyleDef(kind=item.get(_W + "type") or "paragraph")
                current_id = item.get(_W + "styleId")
                default = item.get(_W + "default")
                if (
                    current_id is not None
                    and current.kind == "paragraph"
                    and default is not None
                    and on_off({VAL: default})
                    and styles.default_paragraph is None
                ):
                    styles.default_paragraph = current_id
            elif depth == 3 and current is not None:  # noqa: PLR2004 - w:style/*
                collect, collect_depth = _style_child(tag, item.attrib, current), depth
            elif depth == 3 and tag in (T_RPR_DEFAULT, T_PPR_DEFAULT):  # noqa: PLR2004
                defaults_kind = tag
            elif depth == 4 and defaults_kind is not None:  # noqa: PLR2004 - docDefaults
                collect, collect_depth = _defaults_child(tag, defaults_kind, styles), depth
        elif event == END:
            if collect is not None and depth == collect_depth:
                collect = None
            if depth == 2 and item.tag == T_STYLE and current is not None:  # noqa: PLR2004
                if current_id is not None:
                    styles.styles.setdefault(current_id, current)
                current = None
            elif depth == 3 and item.tag in (T_RPR_DEFAULT, T_PPR_DEFAULT):  # noqa: PLR2004
                defaults_kind = None
            depth -= 1
    return styles


def _style_child(
    tag: str, attrib: dict[str, str], style: StyleDef
) -> Callable[[str, dict[str, str]], None] | None:
    if tag == T_BASED_ON:
        style.based_on = attrib.get(VAL)
        return None
    if tag == T_RPR:
        return lambda child, child_attrib: read_run_property(child, child_attrib, style.rpr)
    if tag == T_PPR:

        def shading(child: str, child_attrib: dict[str, str]) -> None:
            if child == T_SHD:
                style.shading = shading_fill(child_attrib)

        return shading
    return None


def _defaults_child(
    tag: str, kind: str, styles: Styles
) -> Callable[[str, dict[str, str]], None] | None:
    if kind == T_RPR_DEFAULT and tag == T_RPR:
        return lambda child, child_attrib: read_run_property(child, child_attrib, styles.defaults)
    if kind == T_PPR_DEFAULT and tag == T_PPR:

        def shading(child: str, child_attrib: dict[str, str]) -> None:
            if child == T_SHD:
                styles.default_shading = shading_fill(child_attrib)

        return shading
    return None


# --- The walker (AC4 to AC7, review round 0) ------------------------------------------------------


@dataclass
class _Paragraph:
    depth: int
    part: Part
    table_style: str | None = None
    pieces: list[str] = field(default_factory=list)
    size: int = 0
    style: str | None = None
    shading: str | None = None
    run_depth: int = -1
    run_props: dict[str, object] = field(default_factory=dict)
    verdict: Verdict | None = None
    # The open span of removed text (one ``removed`` item per span) and whether the
    # last visible text was borderline (one warning per borderline span).
    span_reason: str | None = None
    span: list[str] = field(default_factory=list)
    borderline: bool = False


@dataclass
class _Sdt:
    depth: int
    checkbox: bool = False
    checked: bool = False


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


class _Walker:
    """Walks the parts of one document and hands paragraphs, removed text and
    warnings to the collector."""

    def __init__(self, styles: Styles, collector: _Collector) -> None:
        self.styles = styles
        self.collector = collector
        self.page = WHITE
        self.sections: list[_Section] = []
        self.note_refs: dict[Part, set[str]] = {"footnote": set(), "endnote": set()}
        self._verdicts: dict[tuple[object, ...], Verdict] = {}

    # The state of one part.
    def _reset(self, part: Part, *, main: bool, notes: bool) -> None:
        self.main = main
        self.notes = notes
        self.parts: list[Part] = [part]
        self.paragraphs: list[_Paragraph] = []
        self.paragraph: _Paragraph | None = None
        self.skip = 0
        self.watch: _Sdt | None = None
        self.collect: Callable[[str, dict[str, str]], None] | None = None
        self.collect_depth = 0
        self.section: _Section | None = None
        self.section_depth = 0
        self.code_fields = 0
        self.fields: list[bool] = []
        self.sdts: list[_Sdt] = []
        self.tables: list[list[Any]] = []
        self.alternates: list[bool] = []
        self.namespaces: dict[str, list[str]] = {}
        self.declared: dict[int, list[str]] = {}
        # Text of content that is not displayed, collected for ``removed``.
        self.capture: list[str] | None = None
        self.capture_depth = 0

    def walk(  # noqa: PLR0912, PLR0915 - the event loop is kept flat for speed
        self,
        events: Iterator[tuple[str, Any]],
        part: Part,
        *,
        main: bool = False,
        notes: bool = False,
        displayed: bool = True,
    ) -> None:
        self._reset(part, main=main, notes=notes)
        if not displayed:
            self.capture = []
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
                        self._watch_checkbox(item)
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
                if depth == 1:
                    self._check_root(item.tag, main=main)
                handler = start_handlers.get(item.tag)
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
                else:
                    handler = end_handlers.get(item.tag)
                    if handler is not None:
                        handler(self, item, depth)
                if self.declared and depth in self.declared:
                    for prefix in self.declared.pop(depth):
                        self.namespaces[prefix].pop()
                depth -= 1
            elif event == START_NS:
                pending.append(item)
        if self.fields:
            # A field that never ends would hide the rest of the part from the
            # reader, but not necessarily from the person: fail closed.
            raise suspicious()
        if not displayed:
            self._flush_capture()

    # --- Helpers ---

    def _declare(self, depth: int, pending: list[tuple[str, str]]) -> None:
        for prefix, uri in pending:
            self.namespaces.setdefault(prefix, []).append(uri)
        self.declared[depth] = [prefix for prefix, _ in pending]

    @staticmethod
    def _check_root(tag: str, *, main: bool) -> None:
        if tag.startswith(STRICT_PREFIX):
            raise ExtractionError(DOCX_STRICT_UNSUPPORTED)
        if main and tag != T_DOCUMENT:
            raise suspicious()

    def _watch_checkbox(self, item: Element) -> None:
        watch = self.watch
        if watch is None:
            return
        if item.tag == T_W14_CHECKBOX:
            watch.checkbox = True
        elif item.tag == T_W14_CHECKED:
            value = item.get(A_W14_VAL)
            watch.checked = bool(on_off({VAL: value} if value is not None else {}))

    def _skip(self) -> None:
        self.skip = 1

    def _flush_capture(self) -> None:
        text = "".join(self.capture or ()).strip()
        self.capture = None
        if text:
            self.collector.remove(NOT_DISPLAYED, text)

    def _open_section(self, depth: int) -> None:
        if not self.main:
            return
        self.section = _Section()
        self.section_depth = depth
        self.sections.append(self.section)

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

    def _verdict(self, paragraph: _Paragraph) -> Verdict:
        verdict = paragraph.verdict
        if verdict is not None:
            return verdict
        direct = paragraph.run_props
        key = (
            paragraph.style,
            paragraph.shading,
            paragraph.table_style,
            *sorted(direct.items()),
        )
        verdict = self._verdicts.get(key)
        if verdict is None:
            verdict = self._judge(paragraph, direct)
            if len(self._verdicts) >= MAX_CACHED_VERDICTS:
                self._verdicts.clear()
            self._verdicts[key] = verdict
        paragraph.verdict = verdict
        return verdict

    def _judge(self, paragraph: _Paragraph, direct: dict[str, object]) -> Verdict:
        """Effective formatting: docDefaults → table style → paragraph style →
        character style → direct. ``w:vanish`` is a toggle property (ECMA-376
        17.7.3): the style layers are XORed, direct formatting sets the value."""
        styles = self.styles
        table_props = styles.table(paragraph.table_style)
        style_props, style_shading = styles.paragraph(styles.paragraph_style(paragraph.style))
        rstyle = direct.get("rstyle")
        char_props = styles.character(rstyle if isinstance(rstyle, str) else None)
        props = dict(styles.defaults)
        vanish = False
        for layer in (styles.defaults, table_props, style_props, char_props):
            if layer is not styles.defaults:
                props.update(layer)
            if layer.get("vanish") is True:
                vanish = not vanish
        props.update(direct)
        direct_vanish = direct.get("vanish")
        props["vanish"] = direct_vanish if isinstance(direct_vanish, bool) else vanish
        shading = paragraph.shading
        if shading is None:
            shading = style_shading if style_shading is not None else styles.default_shading
        return judge(props, shading, self.page)

    def _close_span(self, paragraph: _Paragraph) -> None:
        if paragraph.span_reason is not None:
            self.collector.remove(paragraph.span_reason, "".join(paragraph.span))
            paragraph.span_reason = None
            paragraph.span = []

    def _emit(self, text: str, *, symbol: bool = False) -> None:
        paragraph = self.paragraph
        if paragraph is None or self.code_fields or not text:
            return
        if self.capture is not None:
            self.capture.append(text)
            return
        verdict = self._verdict(paragraph)
        if verdict.wingdings and not symbol:
            text = text.translate(_WINGDINGS_TABLE)
        if verdict.reason is not None:
            if paragraph.span_reason != verdict.reason:
                self._close_span(paragraph)
                paragraph.span_reason = verdict.reason
            paragraph.span.append(text)
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
            self.collector.warn(BORDERLINE_TEXT)
        paragraph.borderline = verdict.borderline

    # --- Start handlers ---

    def _start_p(self, item: Element, depth: int) -> None:
        table_style = self.tables[-1][1] if self.tables else None
        paragraph = _Paragraph(depth=depth, part=self.parts[-1], table_style=table_style)
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
                paragraph.shading = shading_fill(attrib)

        self.collect = collect
        self.collect_depth = depth

    def _start_tbl(self, item: Element, depth: int) -> None:
        self.tables.append([depth, None])

    def _start_tbl_pr(self, item: Element, depth: int) -> None:
        if not self.tables or self.tables[-1][0] != depth - 1:
            self._skip()
            return
        table = self.tables[-1]

        def collect(tag: str, attrib: dict[str, str]) -> None:
            if tag == T_TBL_STYLE:
                table[1] = attrib.get(VAL)

        self.collect = collect
        self.collect_depth = depth

    def _start_sect_pr(self, item: Element, depth: int) -> None:
        if not self.main:
            self._skip()
            return
        self._open_section(depth)
        self.collect = self._section_child
        self.collect_depth = depth

    def _start_note(self, item: Element, depth: int) -> None:
        if not self.notes or depth != 2 or self.capture is not None:  # noqa: PLR2004
            return
        kind = (item.get(A_TYPE) or "normal").strip()
        note_id = (item.get(A_ID) or "").strip()
        part = self.parts[0]
        if kind in SEPARATOR_NOTES or note_id not in self.note_refs.get(part, set()):
            self.capture = []
            self.capture_depth = depth

    def _start_note_ref(self, item: Element, depth: int) -> None:
        paragraph = self.paragraph
        if paragraph is None or self.code_fields or self.capture is not None:
            return
        if self._verdict(paragraph).reason is not None:
            return
        note_id = item.get(A_ID)
        if note_id is not None:
            part: Part = "footnote" if item.tag == T_FOOTNOTE_REF else "endnote"
            self.note_refs[part].add(note_id.strip())

    def _start_character(self, item: Element, depth: int) -> None:
        self._emit(CHARACTERS[item.tag])

    def _start_sym(self, item: Element, depth: int) -> None:
        font = (item.get(_W + "font") or "").strip().casefold()
        try:
            code = int(item.get(_W + "char") or "", 16)
        except ValueError:
            return
        if code < _BYTE:
            code += _SYMBOL_BASE
        glyph = WINGDINGS.get(code) if font == "wingdings" else None
        if glyph is not None:
            self._emit(glyph, symbol=True)

    def _start_field(self, item: Element, depth: int) -> None:
        kind = (item.get(_W + "fldCharType") or "").strip()
        fields = self.fields
        if kind == "begin":
            fields.append(False)
            self.code_fields += 1
        elif kind == "separate":
            if fields and not fields[-1]:
                fields[-1] = True
                self.code_fields -= 1
        elif kind == "end" and fields and not fields.pop():
            self.code_fields -= 1

    def _start_sdt(self, item: Element, depth: int) -> None:
        self.sdts.append(_Sdt(depth=depth))

    def _start_sdt_pr(self, item: Element, depth: int) -> None:
        self._skip()
        if self.sdts and self.sdts[-1].depth == depth - 1:
            self.watch = self.sdts[-1]

    def _start_sdt_content(self, item: Element, depth: int) -> None:
        sdt = self.sdts[-1] if self.sdts else None
        if sdt is None or not sdt.checkbox or self.paragraph is None:
            return
        # A checkbox control: its state, not its content (ADR 0009 Layer 1).
        self._emit(CHECKED if sdt.checked else UNCHECKED, symbol=True)
        self._skip()

    def _start_txbx(self, item: Element, depth: int) -> None:
        self.parts.append("textbox")

    def _start_alternate(self, item: Element, depth: int) -> None:
        self.alternates.append(False)

    def _start_choice(self, item: Element, depth: int) -> None:
        if not self.alternates or self.alternates[-1] or not self._known(item.get("Requires")):
            self._skip()
            return
        self.alternates[-1] = True

    def _start_fallback(self, item: Element, depth: int) -> None:
        if not self.alternates or self.alternates[-1]:
            self._skip()
            return
        self.alternates[-1] = True

    def _known(self, requires: str | None) -> bool:
        prefixes = (requires or "").split()
        if not prefixes:
            return False
        for prefix in prefixes:
            uris = self.namespaces.get(prefix)
            if not uris or uris[-1] not in KNOWN_NAMESPACES:
                return False
        return True

    def _start_not_read(self, item: Element, depth: int) -> None:
        if self.capture is None:
            self.collector.warn(NOT_READ[item.tag], once=True)

    def _start_skipped(self, item: Element, depth: int) -> None:
        self._skip()

    def _start_background(self, item: Element, depth: int) -> None:
        if depth == 2:  # noqa: PLR2004 - w:document/w:background
            color = shading_fill({_W + "fill": item.get(_W + "color") or ""})
            if color is not None and color != AUTO:
                self.page = color

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
            self.capture.append("\n")
            return
        self.collector.paragraph(paragraph.part, "".join(paragraph.pieces))

    def _end_r(self, item: Element, depth: int) -> None:
        paragraph = self.paragraph
        if paragraph is not None and paragraph.run_depth == depth:
            paragraph.run_depth = -1
            paragraph.run_props = {}
            paragraph.verdict = None

    def _end_tbl(self, item: Element, depth: int) -> None:
        if self.tables and self.tables[-1][0] == depth:
            self.tables.pop()

    def _end_note(self, item: Element, depth: int) -> None:
        if self.capture is not None and self.capture_depth == depth:
            self.capture_depth = 0
            self._flush_capture()

    def _end_sdt(self, item: Element, depth: int) -> None:
        if self.sdts:
            self.sdts.pop()

    def _end_txbx(self, item: Element, depth: int) -> None:
        if len(self.parts) > 1:
            self.parts.pop()

    def _end_alternate(self, item: Element, depth: int) -> None:
        if self.alternates:
            self.alternates.pop()

    _Handler = Callable[["_Walker", Element, int], None]
    _start_handlers: Final[dict[str, _Handler]] = {
        T_P: _start_p,
        T_R: _start_r,
        T_RPR: _start_rpr,
        T_PPR: _start_ppr,
        T_TBL: _start_tbl,
        T_TBL_PR: _start_tbl_pr,
        T_SECT_PR: _start_sect_pr,
        T_FOOTNOTE: _start_note,
        T_ENDNOTE: _start_note,
        T_FOOTNOTE_REF: _start_note_ref,
        T_ENDNOTE_REF: _start_note_ref,
        T_SYM: _start_sym,
        T_FLD_CHAR: _start_field,
        T_SDT: _start_sdt,
        T_SDT_PR: _start_sdt_pr,
        T_SDT_CONTENT: _start_sdt_content,
        T_TXBX: _start_txbx,
        T_ALTERNATE: _start_alternate,
        T_CHOICE: _start_choice,
        T_FALLBACK: _start_fallback,
        T_BACKGROUND: _start_background,
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
        T_FOOTNOTE: _end_note,
        T_ENDNOTE: _end_note,
        T_SDT: _end_sdt,
        T_TXBX: _end_txbx,
        T_ALTERNATE: _end_alternate,
    }


# --- Result (AC4 header and footer filter, AC5 removed text, AC8, AC9) -------------------------


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
        self.header_lines: set[str] = set()

    def chars_left(self) -> int:
        return self.max_chars - self.chars

    def remove(self, reason: str, text: str) -> None:
        if not text:
            return
        if len(self.removed) >= MAX_LIST_ITEMS:
            raise ExtractionError(TOO_MUCH_TEXT)
        head = ControlCleaner().clean(text[: 2 * MAX_SAMPLE_CHARS])
        sample = _SPACES.sub(" ", head).strip()[:MAX_SAMPLE_CHARS]
        self.removed.append(Removed(reason=reason, count=len(text), sample=sample))

    def warn(self, code: str, *, once: bool = False) -> None:
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
        if part in ("header", "footer"):
            if _PAGE_NUMBER_LINE.fullmatch(text):
                self.remove(PAGE_NUMBER, text)
                return
            key = _SPACES.sub(" ", text).casefold()
            if key in self.header_lines:
                self.remove(REPEATED_HEADER_FOOTER, text)
                return
            self.header_lines.add(key)
        self.chars += len(text)
        if self.chars > self.max_chars or len(self.blocks) >= self.max_blocks:
            raise ExtractionError(TOO_MUCH_TEXT)
        self.blocks.append(Block(text=text, part=part, page=None))

    def removed_list(self) -> list[Removed]:
        out = self.removed + self.cleaner.removed()
        if len(out) > MAX_LIST_ITEMS:
            raise ExtractionError(TOO_MUCH_TEXT)
        return out


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
    reader = _Reader(
        archive, XmlBudget(max_depth=limits.max_xml_depth, max_elements=limits.max_elements)
    )
    parts = _resolve_package(reader)
    styles = _parse_styles(reader.events(parts.styles)) if parts.styles else Styles()
    even_and_odd = _even_and_odd_headers(reader.events(parts.settings)) if parts.settings else False
    collector = _Collector(max_chars=max_chars, max_blocks=max_blocks)
    walker = _Walker(styles, collector)
    # Body first (sections and note references), then headers and footers (note
    # references too), then the notes.
    walker.walk(reader.events(parts.main), "body", main=True)
    shown = displayed_header_ids(walker.sections, even_and_odd=even_and_odd)
    for header in parts.headers:
        walker.walk(reader.events(header.entry), header.part, displayed=bool(header.rids & shown))
    for label, entry in parts.notes:
        walker.walk(reader.events(entry), label, notes=True)
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
