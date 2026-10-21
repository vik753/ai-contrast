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
    type: str
    target: str
    external: bool


@dataclass
class _Parts:
    main: ZipEntry
    styles: ZipEntry | None = None
    notes: list[tuple[Part, ZipEntry]] = field(default_factory=list)
    headers: list[tuple[Part, ZipEntry]] = field(default_factory=list)


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
                out.append(_Rel(rel_type.strip(), target.strip(), mode == "external"))
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
_FOLLOWED: Final[dict[str, Part | None]] = {
    REL_STYLES: None,
    REL_FOOTNOTES: "footnote",
    REL_ENDNOTES: "endnote",
    REL_HEADER: "header",
    REL_FOOTER: "footer",
}


def _resolve_package(reader: _Reader) -> _Parts:
    main = _main_part(reader)
    _check_content_type(reader, main)
    entry = reader.entry(main)
    if entry is None:
        raise suspicious()
    decoy = reader.entry("word/document.xml")
    if decoy is not None and decoy is not entry:
        raise suspicious()
    parts = _Parts(main=entry)
    seen: dict[str, Part | None] = {}
    for rel in reader.rels(main):
        label = _FOLLOWED.get(rel.type)
        if rel.type not in _FOLLOWED:
            continue
        name = _resolve_target(main, rel)
        target = reader.entry(name)
        if target is None or target is entry:
            raise suspicious()
        key = part_key(name)
        if key in seen:
            if seen[key] != label:
                raise suspicious()
            continue  # the same part twice is read once
        seen[key] = label
        if label is None:
            if parts.styles is not None:
                raise suspicious()
            parts.styles = target
        elif label in ("footnote", "endnote"):
            if any(existing == label for existing, _ in parts.notes):
                raise suspicious()
            parts.notes.append((label, target))
        else:
            parts.headers.append((label, target))
    # Footnotes before endnotes, headers before footers; relationship order otherwise.
    parts.notes.sort(key=lambda item: item[0] != "footnote")
    parts.headers.sort(key=lambda item: item[0] != "header")
    return parts


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


# --- The walker (AC4 to AC7) ---------------------------------------------------------------------


@dataclass
class _Paragraph:
    depth: int
    part: Part
    pieces: list[str] = field(default_factory=list)
    size: int = 0
    style: str | None = None
    shading: str | None = None
    run_depth: int = -1
    run_props: dict[str, object] = field(default_factory=dict)
    verdict: Verdict | None = None


@dataclass
class _Sdt:
    depth: int
    checkbox: bool = False
    checked: bool = False


class _Walker:
    """Walks the parts of one document and hands paragraphs and removed text to the
    collector."""

    def __init__(self, styles: Styles, collector: _Collector) -> None:
        self.styles = styles
        self.collector = collector
        self.page = WHITE
        self.warnings: dict[str, None] = {}
        self.borderline = False
        self._verdicts: dict[tuple[object, ...], Verdict] = {}

    # The state of one part.
    def _reset(self, part: Part) -> None:
        self.parts: list[Part] = [part]
        self.paragraphs: list[_Paragraph] = []
        self.paragraph: _Paragraph | None = None
        self.skip = 0
        self.watch: _Sdt | None = None
        self.collect: Callable[[str, dict[str, str]], None] | None = None
        self.collect_depth = 0
        self.code_fields = 0
        self.fields: list[bool] = []
        self.sdts: list[_Sdt] = []
        self.alternates: list[bool] = []
        self.namespaces: dict[str, list[str]] = {}
        self.declared: dict[int, list[str]] = {}

    def walk(  # noqa: PLR0912 - the event loop is kept flat for speed
        self, events: Iterator[tuple[str, Any]], part: Part, *, main: bool = False
    ) -> None:
        self._reset(part)
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
                        self.collect(item.tag, item.attrib)
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

    def _verdict(self, paragraph: _Paragraph) -> Verdict:
        verdict = paragraph.verdict
        if verdict is not None:
            return verdict
        direct = paragraph.run_props
        key = (paragraph.style, paragraph.shading, *sorted(direct.items()))
        verdict = self._verdicts.get(key)
        if verdict is None:
            style_props, style_shading = self.styles.paragraph(
                self.styles.paragraph_style(paragraph.style)
            )
            rstyle = direct.get("rstyle")
            props = dict(self.styles.defaults)
            props.update(style_props)
            props.update(self.styles.character(rstyle if isinstance(rstyle, str) else None))
            props.update(direct)
            shading = paragraph.shading
            if shading is None:
                shading = (
                    style_shading if style_shading is not None else self.styles.default_shading
                )
            verdict = judge(props, shading, self.page)
            if len(self._verdicts) >= MAX_CACHED_VERDICTS:
                self._verdicts.clear()
            self._verdicts[key] = verdict
        paragraph.verdict = verdict
        return verdict

    def _emit(self, text: str, *, symbol: bool = False) -> None:
        paragraph = self.paragraph
        if paragraph is None or self.code_fields or not text:
            return
        verdict = self._verdict(paragraph)
        if verdict.wingdings and not symbol:
            text = text.translate(_WINGDINGS_TABLE)
        if verdict.reason is not None:
            self.collector.remove(verdict.reason, text)
            return
        paragraph.pieces.append(text)
        # The text cap fails early: a paragraph is not built beyond it.
        paragraph.size += len(text)
        if paragraph.size > self.collector.chars_left():
            raise ExtractionError(TOO_MUCH_TEXT)
        if verdict.borderline and not text.isspace():
            self.borderline = True

    # --- Start handlers ---

    def _start_p(self, item: Element, depth: int) -> None:
        paragraph = _Paragraph(depth=depth, part=self.parts[-1])
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
        self.warnings.setdefault(NOT_READ[item.tag], None)

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
        self.collector.paragraph(paragraph.part, "".join(paragraph.pieces))

    def _end_r(self, item: Element, depth: int) -> None:
        paragraph = self.paragraph
        if paragraph is not None and paragraph.run_depth == depth:
            paragraph.run_depth = -1
            paragraph.run_props = {}
            paragraph.verdict = None

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
        T_SDT: _end_sdt,
        T_TXBX: _end_txbx,
        T_ALTERNATE: _end_alternate,
    }


# --- Result (AC4 header and footer filter, AC5 removed text, AC8, AC9) -------------------------


class _Collector:
    """Turns paragraphs into blocks under the caps and records removed text."""

    def __init__(self, *, max_chars: int, max_blocks: int) -> None:
        self.max_chars = max_chars
        self.max_blocks = max_blocks
        self.blocks: list[Block] = []
        self.chars = 0
        self.cleaner = ControlCleaner()
        self.removed: dict[str, tuple[int, list[str]]] = {}
        self.header_lines: set[str] = set()

    def chars_left(self) -> int:
        return self.max_chars - self.chars

    def remove(self, reason: str, text: str) -> None:
        sample = _SPACES.sub(" ", ControlCleaner().clean(text)).strip()
        count, samples = self.removed.get(reason, (0, []))
        if sample and sum(len(s) + 1 for s in samples) < MAX_SAMPLE_CHARS:
            samples.append(sample)
        self.removed[reason] = (count + len(text), samples)

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
        out = [
            Removed(reason=reason, count=count, sample="\n".join(samples)[:MAX_SAMPLE_CHARS])
            for reason, (count, samples) in self.removed.items()
            if count > 0
        ]
        return out + self.cleaner.removed()


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
    collector = _Collector(max_chars=max_chars, max_blocks=max_blocks)
    walker = _Walker(styles, collector)
    walker.walk(reader.events(parts.main), "body", main=True)
    for label, entry in [*parts.notes, *parts.headers]:
        walker.walk(reader.events(entry), label)
    if not collector.blocks:
        raise ExtractionError(NO_TEXT_EXTRACTED)
    warnings = list(walker.warnings)
    if walker.borderline:
        warnings.append(BORDERLINE_TEXT)
    return ExtractionResult(
        kind="docx",
        bytes=len(data),
        language=detect_language("\n".join(block.text for block in collector.blocks)),
        pages=None,
        blocks=collector.blocks,
        ocr_pages=[],
        removed=collector.removed_list(),
        warnings=[Warning(code=code, page=None) for code in warnings],
    )
