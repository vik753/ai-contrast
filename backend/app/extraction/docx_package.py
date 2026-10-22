"""DOCX package resolution (S3-T2 AC3; ADR 0009 Layer 0; threat model T4, T5).

Parts are found the way Word finds them, never by fixed part names:

- ``[Content_Types].xml`` and every ``.rels`` part are parsed with ``defusedxml``
  (``docx_xml``). Duplicate relationship ids in one ``.rels`` part →
  ``suspicious_package``.
- The main part is the target of the single ``officeDocument`` relationship in
  ``_rels/.rels`` (none or several → ``suspicious_package``; the strict OOXML
  relationship → ``docx_strict_unsupported``). Its content type must be the
  WordprocessingML main type (template or macro-enabled types →
  ``unsupported_type``). A ``word/document.xml`` that is not the target →
  ``suspicious_package``.
- Styles, settings, theme, footnotes, endnotes, headers and footers are targets of
  the main part's relationships only. A target outside the package, a missing
  target, the main part itself, or one part under two kinds →
  ``suspicious_package``.
- ``settings.xml`` (the main part's settings relationship only) gives
  ``w:evenAndOddHeaders``, ``w:displayBackgroundShape``, ``w:updateFields`` and
  ``w:clrSchemeMapping``.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Final
from urllib.parse import urlsplit

from app.extraction.detect import UNSUPPORTED_TYPE
from app.extraction.docx_styles import STANDARD_MAPPING, W, on_off
from app.extraction.docx_xml import END, START, XmlBudget, iter_xml, suspicious
from app.extraction.docx_zip import DocxArchive, ZipEntry, part_key
from app.extraction.model import DOCX_STRICT_UNSUPPORTED, ExtractionError, Part

_W: Final = "{" + W + "}"
R_NS: Final = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS: Final = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS: Final = "http://schemas.openxmlformats.org/package/2006/content-types"

REL_OFFICE_DOCUMENT: Final = R_NS + "/officeDocument"
REL_OFFICE_DOCUMENT_STRICT: Final = (
    "http://purl.oclc.org/ooxml/officeDocument/relationships/officeDocument"
)
REL_STYLES: Final = R_NS + "/styles"
REL_SETTINGS: Final = R_NS + "/settings"
REL_THEME: Final = R_NS + "/theme"
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

T_CT_DEFAULT: Final = "{" + CT_NS + "}Default"
T_CT_OVERRIDE: Final = "{" + CT_NS + "}Override"
T_RELATIONSHIP: Final = "{" + REL_NS + "}Relationship"

# Relationship types of the main part that are read; the rest are ignored.
_FOLLOWED: Final[dict[str, str]] = {
    REL_STYLES: "styles",
    REL_SETTINGS: "settings",
    REL_THEME: "theme",
    REL_FOOTNOTES: "footnote",
    REL_ENDNOTES: "endnote",
    REL_HEADER: "header",
    REL_FOOTER: "footer",
}
_SINGLE: Final = ("styles", "settings", "theme")
_PART_LABELS: Final[dict[str, Part]] = {
    "footnote": "footnote",
    "endnote": "endnote",
    "header": "header",
    "footer": "footer",
}


@dataclass(frozen=True)
class Rel:
    rid: str
    type: str
    target: str
    external: bool


@dataclass
class HeaderPart:
    part: Part
    entry: ZipEntry
    rids: set[str]


@dataclass
class Parts:
    main: ZipEntry
    single: dict[str, ZipEntry] = field(default_factory=dict)  # styles, settings, theme
    notes: list[tuple[Part, ZipEntry]] = field(default_factory=list)
    headers: list[HeaderPart] = field(default_factory=list)


@dataclass
class DocSettings:
    even_and_odd_headers: bool = False
    display_background: bool = False
    update_fields: bool = False
    color_mapping: dict[str, str] = field(default_factory=lambda: dict(STANDARD_MAPPING))


def rels_name(part: str) -> str:
    folder, _, base = part.rpartition("/")
    return f"{folder}/_rels/{base}.rels" if folder else f"_rels/{base}.rels"


def resolve_target(source: str, rel: Rel) -> str:
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


class Reader:
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
            content_type = item.get("ContentType")
            if content_type is None:
                continue
            if item.tag == T_CT_DEFAULT:
                extension = item.get("Extension")
                if extension is not None:
                    defaults.setdefault(extension.casefold(), content_type.strip().casefold())
            elif item.tag == T_CT_OVERRIDE:
                name = item.get("PartName")
                if name is not None:
                    key = part_key(name.removeprefix("/"))
                    overrides.setdefault(key, content_type.strip().casefold())
        return defaults, overrides

    def rels(self, part: str) -> list[Rel]:
        entry = self.entry(rels_name(part))
        if entry is None:
            return []
        out: list[Rel] = []
        ids: set[str] = set()
        for event, item in self.events(entry):
            if event == START and item.tag == T_RELATIONSHIP:
                rel_type = item.get("Type")
                target = item.get("Target")
                rid = (item.get("Id") or "").strip()
                if rel_type is None or target is None or not rid or rid in ids:
                    raise suspicious()
                ids.add(rid)
                mode = (item.get("TargetMode") or "Internal").strip().casefold()
                out.append(Rel(rid, rel_type.strip(), target.strip(), mode == "external"))
        return out


def _main_part(reader: Reader) -> str:
    office = [
        rel
        for rel in reader.rels("")
        if rel.type in (REL_OFFICE_DOCUMENT, REL_OFFICE_DOCUMENT_STRICT)
    ]
    if len(office) != 1:
        raise suspicious()
    if office[0].type == REL_OFFICE_DOCUMENT_STRICT:
        raise ExtractionError(DOCX_STRICT_UNSUPPORTED)
    return resolve_target("", office[0])


def _check_content_type(reader: Reader, main: str) -> None:
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


def resolve_package(reader: Reader) -> Parts:  # noqa: PLR0912 - one branch per check
    main = _main_part(reader)
    _check_content_type(reader, main)
    entry = reader.entry(main)
    if entry is None:
        raise suspicious()
    decoy = reader.entry("word/document.xml")
    if decoy is not None and decoy is not entry:
        raise suspicious()
    parts = Parts(main=entry)
    seen: dict[str, str] = {}
    headers: dict[str, HeaderPart] = {}
    for rel in reader.rels(main):
        label = _FOLLOWED.get(rel.type)
        if label is None:
            continue
        name = resolve_target(main, rel)
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
        if label in _SINGLE:
            if label in parts.single:
                raise suspicious()
            parts.single[label] = target
        elif label in ("footnote", "endnote"):
            if any(existing == label for existing, _ in parts.notes):
                raise suspicious()
            parts.notes.append((_PART_LABELS[label], target))
        else:
            headers[key] = HeaderPart(_PART_LABELS[label], target, {rel.rid})
            parts.headers.append(headers[key])
    # Footnotes before endnotes, headers before footers; relationship order otherwise.
    parts.notes.sort(key=lambda item: item[0] != "footnote")
    parts.headers.sort(key=lambda item: item.part != "header")
    return parts


def parse_settings(events: Iterator[tuple[str, Any]]) -> DocSettings:
    """The children of ``w:settings`` that change what is displayed."""
    settings = DocSettings()
    depth = 0
    for event, item in events:
        if event == START:
            depth += 1
            if depth != 2:  # noqa: PLR2004 - w:settings/*
                continue
            tag = item.tag
            if tag == _W + "evenAndOddHeaders":
                settings.even_and_odd_headers = bool(on_off(item.attrib))
            elif tag == _W + "displayBackgroundShape":
                settings.display_background = bool(on_off(item.attrib))
            elif tag == _W + "updateFields":
                settings.update_fields = bool(on_off(item.attrib))
            elif tag == _W + "clrSchemeMapping":
                for key in STANDARD_MAPPING:
                    value = item.get(_W + key)
                    if value is not None:
                        settings.color_mapping[key] = value.strip()
        elif event == END:
            depth -= 1
    return settings
