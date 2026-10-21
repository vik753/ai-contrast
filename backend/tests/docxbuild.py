# ruff: noqa: RUF001 - Cyrillic contract samples are the point of these tests
"""In-memory DOCX builder for the S3-T2 extraction tests.

Every package is built in test code from XML strings: no binary fixture files and
only synthetic text. ``docx_parts`` returns the parts of a package; ``build_docx``
writes them with the standard library ``zipfile`` (deflated). Tests that break the
ZIP structure use ``tests/zipbuild.py`` and the layout helpers below.
"""

from __future__ import annotations

import io
import struct
import zipfile
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from xml.sax.saxutils import escape

from tests.zipbuild import (
    LFH_SIG,
    RawEntry,
    central_section,
    eocd_record,
    local_section,
    stored,
    zipfile_archive,
)

# --- Namespaces and constants ---------------------------------------------------------------

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
STRICT_W = "http://purl.oclc.org/ooxml/wordprocessingml/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

REL_OFFICE_DOCUMENT = R + "/officeDocument"
REL_OFFICE_DOCUMENT_STRICT = (
    "http://purl.oclc.org/ooxml/officeDocument/relationships/officeDocument"
)
REL_STYLES = R + "/styles"
REL_FOOTNOTES = R + "/footnotes"
REL_ENDNOTES = R + "/endnotes"
REL_HEADER = R + "/header"
REL_FOOTER = R + "/footer"
REL_ALT_CHUNK = R + "/aFChunk"
REL_SUBDOCUMENT = R + "/subDocument"
REL_OLE = R + "/oleObject"
REL_HYPERLINK = R + "/hyperlink"
REL_SETTINGS = R + "/settings"

CT_MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
CT_TEMPLATE = "application/vnd.openxmlformats-officedocument.wordprocessingml.template.main+xml"
CT_MACRO = "application/vnd.ms-word.document.macroEnabled.main+xml"
CT_MACRO_TEMPLATE = "application/vnd.ms-word.template.macroEnabledTemplate.main+xml"
CT_STYLES = "application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"
CT_FOOTNOTES = "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"
CT_ENDNOTES = "application/vnd.openxmlformats-officedocument.wordprocessingml.endnotes+xml"
CT_HEADER = "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"
CT_FOOTER = "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"
CT_SETTINGS = "application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"
CT_RELS = "application/vnd.openxmlformats-package.relationships+xml"

NS_DECL = (
    f'xmlns:w="{W}" xmlns:r="{R}" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    'xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
    'xmlns:v="urn:schemas-microsoft-com:vml" '
    'xmlns:o="urn:schemas-microsoft-com:office:office" '
    'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
    'xmlns:xu="urn:example:unknown-extension" '
    'mc:Ignorable="w14 wp"'
)
XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

MIB = 1024 * 1024

# --- WordprocessingML snippets ----------------------------------------------------------------


def t(text: str) -> str:
    return f'<w:t xml:space="preserve">{escape(text)}</w:t>'


def r(text: str = "", rpr: str = "", *, inner: str | None = None) -> str:
    """A run. ``rpr`` is the content of ``w:rPr``; ``inner`` replaces the text."""
    props = f"<w:rPr>{rpr}</w:rPr>" if rpr else ""
    body = t(text) if inner is None else inner
    return f"<w:r>{props}{body}</w:r>"


def p(*runs: str, ppr: str = "") -> str:
    """A paragraph. ``ppr`` is the content of ``w:pPr``."""
    props = f"<w:pPr>{ppr}</w:pPr>" if ppr else ""
    return f"<w:p>{props}{''.join(runs)}</w:p>"


def para(text: str, rpr: str = "", *, ppr: str = "") -> str:
    """A paragraph with one run of ``text``."""
    return p(r(text, rpr), ppr=ppr)


def document_xml(body: str, *, decl: str = NS_DECL, prolog: str = XML_DECL) -> bytes:
    return f"{prolog}<w:document {decl}><w:body>{body}</w:body></w:document>".encode()


def notes_xml(tag: str, notes: Sequence[str]) -> bytes:
    """``w:footnotes``/``w:endnotes`` with separator notes and one note per item."""
    item = tag[:-1]
    sep = (
        f'<w:{item} w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:{item}>'
        f'<w:{item} w:type="continuationSeparator" w:id="0">'
        f"<w:p><w:r><w:continuationSeparator/></w:r></w:p></w:{item}>"
    )
    body = "".join(f'<w:{item} w:id="{i}">{xml}</w:{item}>' for i, xml in enumerate(notes, 1))
    return f"{XML_DECL}<w:{tag} {NS_DECL}>{sep}{body}</w:{tag}>".encode()


def hdr_xml(body: str, tag: str = "hdr") -> bytes:
    return f"{XML_DECL}<w:{tag} {NS_DECL}>{body}</w:{tag}>".encode()


def settings_xml(inner: str = "") -> bytes:
    return f"{XML_DECL}<w:settings {NS_DECL}>{inner}</w:settings>".encode()


def style(
    style_id: str,
    *,
    kind: str = "paragraph",
    rpr: str = "",
    based_on: str | None = None,
) -> str:
    based = f'<w:basedOn w:val="{based_on}"/>' if based_on else ""
    props = f"<w:rPr>{rpr}</w:rPr>" if rpr else ""
    return (
        f'<w:style w:type="{kind}" w:styleId="{style_id}">'
        f'<w:name w:val="{style_id}"/>{based}{props}</w:style>'
    )


def styles_xml(*styles: str, default_rpr: str = "") -> bytes:
    defaults = (
        f"<w:docDefaults><w:rPrDefault><w:rPr>{default_rpr}</w:rPr></w:rPrDefault>"
        "<w:pPrDefault/></w:docDefaults>"
    )
    return f"{XML_DECL}<w:styles {NS_DECL}>{defaults}{''.join(styles)}</w:styles>".encode()


# --- Package -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Rel:
    rid: str
    type: str
    target: str
    external: bool = False

    def xml(self) -> str:
        mode = ' TargetMode="External"' if self.external else ""
        return (
            f'<Relationship Id="{self.rid}" Type="{self.type}" '
            f'Target="{escape(self.target, {chr(34): "&quot;"})}"{mode}/>'
        )


def rels_xml(rels: Sequence[Rel], *, prolog: str = XML_DECL) -> bytes:
    return (
        f'{prolog}<Relationships xmlns="{REL_NS}">{"".join(x.xml() for x in rels)}</Relationships>'
    ).encode()


def content_types_xml(overrides: Sequence[tuple[str, str]], *, prolog: str = XML_DECL) -> bytes:
    items = "".join(f'<Override PartName="{name}" ContentType="{ct}"/>' for name, ct in overrides)
    return (
        f'{prolog}<Types xmlns="{CT_NS}">'
        f'<Default Extension="rels" ContentType="{CT_RELS}"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f"{items}</Types>"
    ).encode()


@dataclass
class Package:
    """A DOCX package description. ``parts()`` returns ``(name, bytes)`` pairs."""

    body: str = ""
    document: bytes | None = None  # replaces the generated main part
    main_part: str = "word/document.xml"
    main_content_type: str = CT_MAIN
    office_rel_type: str = REL_OFFICE_DOCUMENT
    root_rels: bytes | None = None
    content_types: bytes | None = None
    styles: bytes | None = None
    footnotes: Sequence[str] = ()
    endnotes: Sequence[str] = ()
    headers: Sequence[str] = ()
    footers: Sequence[str] = ()
    footnotes_part: str = "word/footnotes.xml"
    doc_rels: Sequence[Rel] = ()
    doc_rels_xml: bytes | None = None
    extra: Sequence[tuple[str, bytes]] = ()
    extra_overrides: Sequence[tuple[str, str]] = ()
    # Review round 0: only displayed parts are read.
    # ``sections``: the inner XML of each w:sectPr (header/footer references,
    # w:titlePg). ``None``: one section per header/footer index ``i`` with
    # default references to header ``i`` and footer ``i``.
    sections: Sequence[str] | None = None
    # A paragraph with a reference to every footnote and endnote (default on).
    note_refs: bool = True
    settings: bytes | None = None

    def _sections(self) -> list[str]:
        if self.sections is not None:
            return list(self.sections)
        out: list[str] = []
        for i in range(max(len(self.headers), len(self.footers))):
            refs = ""
            if i < len(self.headers):
                refs += f'<w:headerReference w:type="default" r:id="rIdH{i + 1}"/>'
            if i < len(self.footers):
                refs += f'<w:footerReference w:type="default" r:id="rIdF{i + 1}"/>'
            out.append(refs)
        return out

    def _main_body(self) -> str:
        refs = ""
        if self.note_refs:
            refs += "".join(
                f'<w:r><w:footnoteReference w:id="{i}"/></w:r>'
                for i in range(1, len(self.footnotes) + 1)
            )
            refs += "".join(
                f'<w:r><w:endnoteReference w:id="{i}"/></w:r>'
                for i in range(1, len(self.endnotes) + 1)
            )
        body = self.body + (f"<w:p>{refs}</w:p>" if refs else "")
        sections = self._sections()
        for inner in sections[:-1]:
            body += f"<w:p><w:pPr><w:sectPr>{inner}</w:sectPr></w:pPr></w:p>"
        if sections:
            body += f"<w:sectPr>{sections[-1]}</w:sectPr>"
        return body

    def _rel_dir(self) -> str:
        head, _, _ = self.main_part.rpartition("/")
        return head

    def _related(self, rel_target: str) -> str:
        """Part name of a target relative to the main part's folder."""
        folder = self._rel_dir()
        return f"{folder}/{rel_target}" if folder else rel_target

    def parts(self) -> list[tuple[str, bytes]]:
        out: list[tuple[str, bytes]] = []
        overrides: list[tuple[str, str]] = [("/" + self.main_part, self.main_content_type)]
        rels: list[Rel] = list(self.doc_rels)

        def add(rid: str, rel_type: str, target: str, data: bytes, ct: str) -> None:
            name = self._related(target)
            rels.append(Rel(rid, rel_type, target))
            overrides.append(("/" + name, ct))
            out.append((name, data))

        if self.styles is not None:
            add("rIdStyles", REL_STYLES, "styles.xml", self.styles, CT_STYLES)
        if self.footnotes:
            target = self.footnotes_part.removeprefix(self._rel_dir() + "/")
            add(
                "rIdFn", REL_FOOTNOTES, target, notes_xml("footnotes", self.footnotes), CT_FOOTNOTES
            )
        if self.endnotes:
            add(
                "rIdEn",
                REL_ENDNOTES,
                "endnotes.xml",
                notes_xml("endnotes", self.endnotes),
                CT_ENDNOTES,
            )
        for i, body in enumerate(self.headers, 1):
            add(f"rIdH{i}", REL_HEADER, f"header{i}.xml", hdr_xml(body, "hdr"), CT_HEADER)
        for i, body in enumerate(self.footers, 1):
            add(f"rIdF{i}", REL_FOOTER, f"footer{i}.xml", hdr_xml(body, "ftr"), CT_FOOTER)
        if self.settings is not None:
            add("rIdSettings", REL_SETTINGS, "settings.xml", self.settings, CT_SETTINGS)
        overrides.extend(self.extra_overrides)

        main = self.document if self.document is not None else document_xml(self._main_body())
        folder = self._rel_dir()
        base = self.main_part.rpartition("/")[2]
        rels_name = f"{folder}/_rels/{base}.rels" if folder else f"_rels/{base}.rels"
        root = self.root_rels
        if root is None:
            root = rels_xml([Rel("rId1", self.office_rel_type, self.main_part)])
        ct = self.content_types if self.content_types is not None else content_types_xml(overrides)
        head: list[tuple[str, bytes]] = [
            ("[Content_Types].xml", ct),
            ("_rels/.rels", root),
            (self.main_part, main),
        ]
        doc_rels = self.doc_rels_xml if self.doc_rels_xml is not None else rels_xml(rels)
        if rels or self.doc_rels_xml is not None:
            head.append((rels_name, doc_rels))
        return head + out + list(self.extra)


def build_docx(package: Package | None = None, **kwargs: object) -> bytes:
    """A DOCX written by ``zipfile`` (deflated). Keyword arguments go to ``Package``."""
    pkg = package if package is not None else Package(**kwargs)  # type: ignore[arg-type]
    return zipfile_archive(pkg.parts())


def body_docx(*paragraphs: str, **kwargs: object) -> bytes:
    return build_docx(Package(body="".join(paragraphs), **kwargs))  # type: ignore[arg-type]


# --- Raw ZIP layouts (AC1) ----------------------------------------------------------------------

LFH_FLAGS = 6
LFH_METHOD = 8
LFH_CRC = 14
LFH_CSIZE = 18
LFH_USIZE = 22
LFH_NAME = 30
FLAG_DESCRIPTOR = 0x0008
DESCRIPTOR_SIG = b"PK\x07\x08"


def layout_local(entry: RawEntry) -> bytes:
    """The local header and data of ``entry`` alone."""
    return local_section([entry])[0]


def stored_entries(pkg: Package | None = None) -> list[RawEntry]:
    return [stored(name, data) for name, data in (pkg or Package(body=para(CLAUSE))).parts()]


def local_offsets(entries: list[RawEntry]) -> list[int]:
    return local_section(entries)[1]


def patch(data: bytes, offset: int, new: bytes) -> bytes:
    return data[:offset] + new + data[offset + len(new) :]


def u16(value: int) -> bytes:
    return struct.pack("<H", value)


def u32(value: int) -> bytes:
    return struct.pack("<I", value & 0xFFFFFFFF)


def layout(  # noqa: PLR0913 - every keyword is one layout fault
    entries: list[RawEntry],
    *,
    locals_: list[bytes] | None = None,
    gaps: dict[int, bytes] | None = None,
    tail_gap: bytes = b"",
    cd_order: list[int] | None = None,
    offsets_override: dict[int, int] | None = None,
) -> bytes:
    """Write locals one by one with optional bytes before entry ``i`` (``gaps``) and
    before the central directory (``tail_gap``). The central directory lists
    ``cd_order`` (default: file order) and may point at other offsets."""
    gaps = gaps or {}
    blobs = locals_ if locals_ is not None else [local_section([e])[0] for e in entries]
    out = b""
    offsets: list[int] = []
    for i, blob in enumerate(blobs):
        out += gaps.get(i, b"")
        offsets.append(len(out))
        out += blob
    out += tail_gap
    for i, value in (offsets_override or {}).items():
        offsets[i] = value
    order = cd_order if cd_order is not None else list(range(len(entries)))
    cd = central_section([entries[i] for i in order], [offsets[i] for i in order])
    return out + cd + eocd_record(count=len(order), cd_size=len(cd), cd_offset=len(out))


def descriptor_local(
    entry: RawEntry,
    *,
    signature: bool = True,
    crc: int | None = None,
    sizes: tuple[int, int] | None = None,
) -> bytes:
    """A local header with bit 3 set, zero CRC and sizes, the data, then a data
    descriptor (``crc`` and ``sizes`` override the true values)."""
    name = entry.name_bytes()
    csize, usize = entry.sizes() if sizes is None else sizes
    header = LFH_SIG + struct.pack(
        "<HHHHHIIIHH",
        20,
        entry.flags | FLAG_DESCRIPTOR,
        entry.method,
        0,
        0,
        0,
        0,
        0,
        len(name),
        0,
    )
    value = entry.crc_value() if crc is None else crc
    desc = (DESCRIPTOR_SIG if signature else b"") + struct.pack("<III", value, csize, usize)
    return header + name + entry.data + desc


def with_descriptor_flag(entry: RawEntry) -> RawEntry:
    return RawEntry(
        name=entry.name,
        data=entry.data,
        method=entry.method,
        flags=entry.flags | FLAG_DESCRIPTOR,
        compressed_size=entry.compressed_size,
        uncompressed_size=entry.uncompressed_size,
        crc=entry.crc,
    )


def deflate_raw(data: bytes) -> bytes:
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    return compressor.compress(data) + compressor.flush()


def deflated_entry(
    name: str, data: bytes, *, declared_size: int | None = None, crc_of: bytes | None = None
) -> RawEntry:
    """A method-8 entry of ``data``; the declared size and CRC may lie."""
    packed = deflate_raw(data)
    return RawEntry(
        name=name,
        data=packed,
        method=8,
        compressed_size=len(packed),
        uncompressed_size=len(data) if declared_size is None else declared_size,
        crc=zlib.crc32(data if crc_of is None else crc_of),
    )


def zip_info_ratio(data: bytes) -> float:
    """Largest uncompressed / compressed ratio of one entry (detection precondition)."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return max(i.file_size / max(i.compress_size, 1) for i in archive.infolist())


# --- Synthetic text -------------------------------------------------------------------------------

CLAUSE = "Synthetic test contract. Clause 1. The Client pays each invoice within 30 days."
CLAUSE_UK = (
    "Синтетичний тестовий договір. Замовник сплачує кожен рахунок протягом тридцяти днів, "
    "а виконавець надає послуги належної якості."
)
