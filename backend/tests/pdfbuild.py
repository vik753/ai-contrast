# ruff: noqa: RUF001 - Cyrillic contract samples are the point of these tests
"""In-memory PDF builder for the S3-T3 extraction tests.

Every PDF is written in test code from raw objects: header, numbered objects,
a classic cross-reference table and a trailer. No binary fixture files, no test
dependency, synthetic text only.

Fonts (shared resources of every page):

- ``/F1`` is the standard Type1 font Helvetica (WinAnsiEncoding) for Latin text;
- ``/F2`` is a Type0 font with the Identity-H encoding and a ToUnicode CMap; the
  CID of a glyph is its Unicode code point (``CYR_CHARS``), the default width is
  500, combining marks have width 0. No font program is embedded: text extraction
  needs only the ToUnicode CMap.

Other shared resources: ``/Im0`` (an image XObject, 2 x 2 grey pixels),
``/GS0`` (ExtGState ``ca 0``), ``/GS1`` (``ca 0.5``), ``/P0`` (a shading pattern:
its colour cannot be compared with white).

Content helpers return content-stream source (``str``, ASCII only).
``incremental_update`` appends a revision (new objects, xref section, trailer
with ``/Prev``). ``Encryption`` writes the Standard security handler with RC4
(R2, R3) or AES-128 (R4, AESV2; needs ``cryptography``, which ``pdfminer.six``
brings in).
"""

from __future__ import annotations

import hashlib
import re
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

# --- Object numbers of the shared objects ------------------------------------------------------

CATALOG = 1
PAGES = 2
FONT_HELVETICA = 3
FONT_TYPE0 = 4
FONT_CID = 5
FONT_DESCRIPTOR = 6
TO_UNICODE = 7
IMAGE = 8
EXTRA = 5000  # first number for objects added with ``extra``
FIRST_PAGE = 9  # page i (0-based) is FIRST_PAGE + 2 * i, its content stream the next number

LETTER = (0.0, 0.0, 612.0, 792.0)
PAGE_AREA = 612.0 * 792.0

FILE_ID = bytes.fromhex("5ec7e7a1c0de0000a1b2c3d4e5f60718")

# Characters that /F2 can show: ASCII, Cyrillic, some punctuation, combining marks
# and one control character (for the Cc rule).
COMBINING = chr(0x0306) + chr(0x0308)
CYR_CHARS = (
    "".join(chr(c) for c in range(0x20, 0x7F))
    + "".join(chr(c) for c in range(0x0400, 0x0460))
    + "ґҐ«»—–№’"
    + COMBINING
    + chr(0x0007)
)


class FixtureError(ValueError):
    """The builder was asked for something it cannot write."""


def page_obj(index: int) -> int:
    return FIRST_PAGE + 2 * index


def content_obj(index: int) -> int:
    return FIRST_PAGE + 2 * index + 1


# --- Content-stream helpers ---------------------------------------------------------------------


def _fmt(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def latin_string(text: str) -> str:
    """A PDF literal string for /F1 (WinAnsi; Latin-1 subset only)."""
    out = []
    for ch in text:
        code = ord(ch)
        if ch in "()\\":
            out.append("\\" + ch)
        elif 0x20 <= code < 0x7F:
            out.append(ch)
        elif code < 0x100:
            out.append(f"\\{code:03o}")
        else:
            raise FixtureError(ch)
    return "(" + "".join(out) + ")"


def cid_string(text: str) -> str:
    """A hex string of 2-byte CIDs for /F2 (Identity-H, CID = code point)."""
    for ch in text:
        if ch not in CYR_CHARS:
            raise FixtureError(ch)
    return "<" + "".join(f"{ord(ch):04X}" for ch in text) + ">"


def text(  # noqa: PLR0913 - every keyword is one text-state property
    s: str,
    x: float = 72,
    y: float = 720,
    *,
    size: float = 12,
    cyr: bool | None = None,
    render: int | None = None,
    fill: str = "",
    gs: str | None = None,
    scale: float | None = None,
) -> str:
    """One text object that shows ``s`` at ``(x, y)``.

    ``cyr`` selects /F2 (default: when ``s`` is not Latin-1). ``fill`` is a raw
    colour operator such as ``"1 g"``, ``"1 1 1 rg"`` or ``"0 0 0 0 k"``.
    ``render`` sets ``Tr``; ``gs`` applies an ExtGState; ``scale`` sets ``Tz``.
    """
    if cyr is None:
        cyr = any(ord(ch) > 0xFF for ch in s)
    font, string = ("/F2", cid_string(s)) if cyr else ("/F1", latin_string(s))
    ops = ["q"]
    if gs:
        ops.append(f"/{gs} gs")
    if fill:
        ops.append(fill)
    ops.append("BT")
    ops.append(f"{font} {_fmt(size)} Tf")
    if render is not None:
        ops.append(f"{render} Tr")
    if scale is not None:
        ops.append(f"{_fmt(scale)} Tz")
    ops.append(f"{_fmt(x)} {_fmt(y)} Td")
    ops.append(f"{string} Tj")
    ops.append("ET")
    ops.append("Q")
    return "\n".join(ops) + "\n"


def lines(
    rows: Sequence[str], *, x: float = 72, top: float = 720, leading: float = 14, size: float = 12
) -> str:
    """Rows of text, one under another (one paragraph when ``leading`` is small)."""
    return "".join(text(row, x, top - i * leading, size=size) for i, row in enumerate(rows))


def paragraphs(
    paras: Sequence[str], *, x: float = 72, top: float = 720, gap: float = 60, size: float = 12
) -> str:
    """One-line paragraphs separated by a wide vertical gap."""
    return "".join(text(row, x, top - i * gap, size=size) for i, row in enumerate(paras))


def rect(x: float, y: float, w: float, h: float, fill: str = "0 0 0 rg") -> str:
    """A filled rectangle (painted before the text that follows it)."""
    return f"q {fill} {_fmt(x)} {_fmt(y)} {_fmt(w)} {_fmt(h)} re f Q\n"


def pattern_rect(x: float, y: float, w: float, h: float) -> str:
    """A rectangle filled with the shading pattern /P0."""
    return f"q /Pattern cs /P0 scn {_fmt(x)} {_fmt(y)} {_fmt(w)} {_fmt(h)} re f Q\n"


def image(x: float, y: float, w: float, h: float) -> str:
    """The image XObject /Im0 drawn into the box (x, y, w, h)."""
    return f"q {_fmt(w)} 0 0 {_fmt(h)} {_fmt(x)} {_fmt(y)} cm /Im0 Do Q\n"


def inline_image(x: float, y: float, w: float, h: float) -> str:
    """An inline 1 x 1 grey image drawn into the box (x, y, w, h)."""
    matrix = f"{_fmt(w)} 0 0 {_fmt(h)} {_fmt(x)} {_fmt(y)} cm"
    return f"q {matrix}\nBI /W 1 /H 1 /CS /G /BPC 8 ID \x80 EI\nQ\n"


def full_page_image() -> str:
    return image(0, 0, 612, 792)


# --- Annotations --------------------------------------------------------------------------------


def free_text_annot(value: str, rect_: str = "72 600 300 640") -> str:
    return (
        f"<< /Type /Annot /Subtype /FreeText /Rect [{rect_}] "
        f"/Contents {latin_string(value)} /DA (/Helv 12 Tf 0 g) >>"
    )


def text_annot(value: str, rect_: str = "500 700 520 720") -> str:
    return f"<< /Type /Annot /Subtype /Text /Rect [{rect_}] /Contents {latin_string(value)} >>"


def widget_annot(value: str, rect_: str = "72 500 300 520") -> str:
    return (
        f"<< /Type /Annot /Subtype /Widget /FT /Tx /T (field1) /V {latin_string(value)} "
        f"/Rect [{rect_}] /DA (/Helv 12 Tf 0 g) >>"
    )


def link_annot(rect_: str = "72 400 300 420") -> str:
    return (
        f"<< /Type /Annot /Subtype /Link /Rect [{rect_}] "
        "/A << /S /URI /URI (https://example.invalid/terms) >> >>"
    )


# --- Encryption (Standard security handler) ----------------------------------------------------

PASSWORD_PADDING = bytes.fromhex("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A")


def rc4(key: bytes, data: bytes) -> bytes:
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) % 256
        s[i], s[j] = s[j], s[i]
    i = j = 0
    out = bytearray()
    for byte in data:
        i = (i + 1) % 256
        j = (j + s[i]) % 256
        s[i], s[j] = s[j], s[i]
        out.append(byte ^ s[(s[i] + s[j]) % 256])
    return bytes(out)


def _md5(data: bytes) -> bytes:
    return hashlib.md5(data, usedforsecurity=False).digest()


def _pad(password: bytes) -> bytes:
    return (password + PASSWORD_PADDING)[:32]


@dataclass(frozen=True)
class Encryption:
    """Standard security handler. ``revision`` 2 (RC4 40), 3 (RC4 128) or 4 (AESV2)."""

    user_password: bytes = b""
    owner_password: bytes = b"synthetic-owner"
    revision: int = 3
    permissions: int = -4

    @property
    def key_length(self) -> int:
        return 5 if self.revision == 2 else 16

    def owner_value(self) -> bytes:
        digest = _md5(_pad(self.owner_password))
        if self.revision >= 3:
            for _ in range(50):
                digest = _md5(digest)
        key = digest[: self.key_length]
        value = rc4(key, _pad(self.user_password))
        if self.revision >= 3:
            for i in range(1, 20):
                value = rc4(bytes(b ^ i for b in key), value)
        return value

    def file_key(self) -> bytes:
        material = (
            _pad(self.user_password)
            + self.owner_value()
            + struct.pack("<i", self.permissions)
            + FILE_ID
        )
        digest = _md5(material)
        if self.revision >= 3:
            for _ in range(50):
                digest = _md5(digest[: self.key_length])
        return digest[: self.key_length]

    def user_value(self) -> bytes:
        key = self.file_key()
        if self.revision == 2:
            return rc4(key, PASSWORD_PADDING)
        value = rc4(key, _md5(PASSWORD_PADDING + FILE_ID))
        for i in range(1, 20):
            value = rc4(bytes(b ^ i for b in key), value)
        return value + bytes(16)

    def dictionary(self) -> str:
        o, u = self.owner_value().hex().upper(), self.user_value().hex().upper()
        if self.revision == 2:
            head = "/V 1 /R 2 /Length 40"
        elif self.revision == 3:
            head = "/V 2 /R 3 /Length 128"
        else:
            head = (
                "/V 4 /R 4 /Length 128 /StmF /StdCF /StrF /StdCF "
                "/CF << /StdCF << /CFM /AESV2 /AuthEvent /DocOpen /Length 16 >> >>"
            )
        return f"<< /Filter /Standard {head} /O <{o}> /U <{u}> /P {self.permissions} >>"

    def encrypt(self, num: int, data: bytes) -> bytes:
        salt = b"sAlT" if self.revision == 4 else b""
        material = self.file_key() + struct.pack("<I", num)[:3] + b"\x00\x00" + salt
        key = _md5(material)[: min(self.key_length + 5, 16)]
        if self.revision < 4:
            return rc4(key, data)
        from cryptography.hazmat.primitives import padding  # noqa: PLC0415 - optional
        from cryptography.hazmat.primitives.ciphers import (  # noqa: PLC0415
            Cipher,
            algorithms,
            modes,
        )

        iv = bytes(range(16))
        padder = padding.PKCS7(128).padder()
        padded = padder.update(data) + padder.finalize()
        encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        return iv + encryptor.update(padded) + encryptor.finalize()


# --- Writer -------------------------------------------------------------------------------------


@dataclass
class Obj:
    body: str  # a dictionary or any other object (for streams: the stream dictionary)
    stream: bytes | None = None


_LITERAL = re.compile(r"\((?:[^()\\]|\\.)*\)")
_ESCAPE = re.compile(r"\\([0-7]{3}|.)")


def _literal_bytes(literal: str) -> bytes:
    """The bytes of a literal string written by ``latin_string`` (no nesting)."""

    def unescape(match: re.Match[str]) -> str:
        value = match.group(1)
        return chr(int(value, 8)) if len(value) == 3 else value

    return _ESCAPE.sub(unescape, literal[1:-1]).encode("latin-1")


def _encrypt_strings(num: int, body: str, encryption: Encryption | None) -> str:
    """Strings outside streams are encrypted too (as hex strings)."""
    if encryption is None:
        return body

    def replace(match: re.Match[str]) -> str:
        return "<" + encryption.encrypt(num, _literal_bytes(match.group(0))).hex() + ">"

    return _LITERAL.sub(replace, body)


def _serialize(num: int, obj: Obj, encryption: Encryption | None) -> bytes:
    head = f"{num} 0 obj\n".encode()
    obj = Obj(_encrypt_strings(num, obj.body, encryption), obj.stream)
    if obj.stream is None:
        return head + obj.body.encode("latin-1") + b"\nendobj\n"
    data = obj.stream if encryption is None else encryption.encrypt(num, obj.stream)
    if not obj.body.startswith("<<"):
        raise FixtureError(obj.body)
    dictionary = f"<< /Length {len(data)} {obj.body[2:]}"
    return head + dictionary.encode("latin-1") + b"\nstream\n" + data + b"\nendstream\nendobj\n"


def _xref_table(
    entries: Mapping[int, int],
    *,
    with_free_head: bool,
    free: Sequence[int] = (),
    generations: Mapping[int, int] | None = None,
) -> bytes:
    """A classic xref table with one subsection per run of consecutive numbers.

    ``free`` lists object numbers written as free entries (generation 1);
    ``generations`` overrides the generation written for in-use entries.
    """
    out = [b"xref\n"]
    entries = {**entries, **dict.fromkeys(free, 0)}
    gens = generations or {}
    nums = sorted(entries)
    if with_free_head:
        nums = [0, *nums]
    runs: list[list[int]] = []
    for num in nums:
        if runs and runs[-1][-1] + 1 == num:
            runs[-1].append(num)
        else:
            runs.append([num])
    for run in runs:
        out.append(f"{run[0]} {len(run)}\n".encode())
        for num in run:
            if num == 0:
                out.append(b"0000000000 65535 f\r\n")
            elif num in free:
                out.append(b"0000000000 00001 f\r\n")
            else:
                out.append(f"{entries[num]:010d} {gens.get(num, 0):05d} n\r\n".encode())
    return b"".join(out)


def write_pdf(
    objects: Mapping[int, Obj],
    *,
    root: int = CATALOG,
    encryption: Encryption | None = None,
    startxref: int | None = None,
    version: str = "1.7",
) -> bytes:
    """Serialize numbered objects with an xref table and a trailer.

    ``startxref`` overrides the offset written after ``startxref`` (a broken value
    forces pdfminer to reconstruct the cross-reference table).
    """
    out = bytearray(f"%PDF-{version}\n%\xe2\xe3\xcf\xd3\n".encode("latin-1"))
    offsets: dict[int, int] = {}
    for num in sorted(objects):
        offsets[num] = len(out)
        out += _serialize(num, objects[num], encryption)
    size = max(objects) + 1
    encrypt_ref = ""
    if encryption is not None:
        offsets[size] = len(out)
        out += f"{size} 0 obj\n{encryption.dictionary()}\nendobj\n".encode()
        encrypt_ref = f" /Encrypt {size} 0 R"
        size += 1
    xref_at = len(out)
    out += _xref_table(offsets, with_free_head=True)
    file_id = FILE_ID.hex().upper()
    out += (
        f"trailer\n<< /Size {size} /Root {root} 0 R{encrypt_ref} /ID [<{file_id}> <{file_id}>] >>\n"
    ).encode()
    out += f"startxref\n{xref_at if startxref is None else startxref}\n%%EOF\n".encode()
    return bytes(out)


_STARTXREF = re.compile(rb"startxref\s+(\d+)\s+%%EOF\s*$")
_SIZE = re.compile(rb"/Size\s+(\d+)")


def last_startxref(data: bytes) -> int:
    match = _STARTXREF.search(data)
    if match is None:
        raise FixtureError(data[-64:])
    return int(match.group(1))


def incremental_update(  # noqa: PLR0913 - every keyword is one revision fault
    data: bytes,
    objects: Mapping[int, Obj],
    *,
    root: int = CATALOG,
    prev: int | None = None,
    self_loop: bool = False,
    raw_entries: Mapping[int, int] | None = None,
    free: Sequence[int] = (),
    generations: Mapping[int, int] | None = None,
    trailer_extra: str = "",
) -> bytes:
    """Append one revision: changed objects, an xref section and a trailer.

    ``prev`` overrides ``/Prev`` (default: the previous ``startxref``);
    ``self_loop`` makes ``/Prev`` point at this revision's own xref section;
    ``raw_entries`` adds xref entries (object number -> any byte offset);
    ``free`` marks object numbers free in this section; ``generations`` writes
    other generations into the xref entries (the objects keep generation 0);
    ``trailer_extra`` is added to the trailer dictionary.
    """
    out = bytearray(data if data.endswith(b"\n") else data + b"\n")
    offsets: dict[int, int] = {}
    for num in sorted(objects):
        offsets[num] = len(out)
        out += _serialize(num, objects[num], None)
    offsets.update(raw_entries or {})
    sizes = [int(m) for m in _SIZE.findall(data)]
    size = max([*sizes, max([*offsets, *free]) + 1])
    xref_at = len(out)
    prev_value = xref_at if self_loop else (last_startxref(data) if prev is None else prev)
    out += _xref_table(offsets, with_free_head=False, free=free, generations=generations)
    file_id = FILE_ID.hex().upper()
    out += (
        f"trailer\n<< /Size {size} /Root {root} 0 R /Prev {prev_value}{trailer_extra} "
        f"/ID [<{file_id}> <{file_id}>] >>\n"
    ).encode()
    out += f"startxref\n{xref_at}\n%%EOF\n".encode()
    return bytes(out)


# --- Documents ----------------------------------------------------------------------------------


@dataclass
class Page:
    content: str = ""
    media_box: tuple[float, float, float, float] = LETTER
    crop_box: tuple[float, float, float, float] | None = None
    annots: Sequence[str] = field(default_factory=tuple)
    resources: str | None = None  # default: RESOURCES (see ``resources``)


def _box(box: tuple[float, float, float, float]) -> str:
    return "[" + " ".join(_fmt(v) for v in box) + "]"


def _to_unicode_cmap() -> bytes:
    chars = list(CYR_CHARS)
    chunks = []
    for start in range(0, len(chars), 100):
        part = chars[start : start + 100]
        entries = "\n".join(f"<{ord(c):04X}> <{ord(c):04X}>" for c in part)
        chunks.append(f"{len(part)} beginbfchar\n{entries}\nendbfchar")
    body = "\n".join(chunks)
    return (
        "/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        "/CMapName /Synthetic-UCS def\n/CMapType 2 def\n"
        "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
        f"{body}\nendcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
    ).encode()


SHADING = (
    "<< /ShadingType 2 /ColorSpace /DeviceRGB /Coords [0 0 612 0] /Function << /FunctionType 2 "
    "/Domain [0 1] /C0 [0 0 0] /C1 [0 0 1] /N 1 >> >>"
)


def resources(  # noqa: PLR0913 - one keyword per resource category
    *,
    font: str = "",
    xobject: str = "",
    extgstate: str = "",
    colorspace: str = "",
    pattern: str = "",
    shading: str = "",
    properties: str = "",
) -> str:
    """The shared resources plus extra entries (raw ``/Name value`` pairs) per category."""
    out = (
        f"<< /Font << /F1 {FONT_HELVETICA} 0 R /F2 {FONT_TYPE0} 0 R {font}>> "
        f"/XObject << /Im0 {IMAGE} 0 R {xobject}>> "
        "/ExtGState << /GS0 << /Type /ExtGState /ca 0 >> /GS1 << /Type /ExtGState /ca 0.5 >> "
        f"{extgstate}>> "
        f"/Pattern << /P0 << /PatternType 2 /Shading {SHADING} >> {pattern}>> "
    )
    if colorspace:
        out += f"/ColorSpace << {colorspace} >> "
    if shading:
        out += f"/Shading << {shading} >> "
    if properties:
        out += f"/Properties << {properties} >> "
    return out + "/ProcSet [/PDF /Text /ImageB] >>"


RESOURCES = resources()


def pdf_objects(
    pages: Sequence[Page],
    *,
    xfa: bytes | None = None,
    acroform: bool = False,
    extra: Mapping[int, Obj] | None = None,
    catalog_extra: str = "",
) -> dict[int, Obj]:
    """The numbered objects of a document (before serialization).

    ``extra`` adds objects (numbers from ``EXTRA`` up); ``catalog_extra`` is added
    to the catalog dictionary.
    """
    objects: dict[int, Obj] = {}
    kids = " ".join(f"{page_obj(i)} 0 R" for i in range(len(pages)))
    objects[PAGES] = Obj(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>")
    objects[FONT_HELVETICA] = Obj(
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    objects[FONT_TYPE0] = Obj(
        f"<< /Type /Font /Subtype /Type0 /BaseFont /SyntheticSans /Encoding /Identity-H "
        f"/DescendantFonts [{FONT_CID} 0 R] /ToUnicode {TO_UNICODE} 0 R >>"
    )
    zero_widths = " ".join(f"{ord(c)} [0]" for c in COMBINING)
    objects[FONT_CID] = Obj(
        "<< /Type /Font /Subtype /CIDFontType2 /BaseFont /SyntheticSans "
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
        f"/FontDescriptor {FONT_DESCRIPTOR} 0 R /DW 500 /W [{zero_widths}] "
        "/CIDToGIDMap /Identity >>"
    )
    objects[FONT_DESCRIPTOR] = Obj(
        "<< /Type /FontDescriptor /FontName /SyntheticSans /Flags 32 "
        "/FontBBox [0 -200 1000 800] /ItalicAngle 0 /Ascent 800 /Descent -200 "
        "/CapHeight 700 /StemV 80 >>"
    )
    objects[TO_UNICODE] = Obj("<< >>", _to_unicode_cmap())
    objects[IMAGE] = Obj(
        "<< /Type /XObject /Subtype /Image /Width 2 /Height 2 /ColorSpace /DeviceGray "
        "/BitsPerComponent 8 >>",
        b"\x10\x80\x80\xf0",
    )
    next_num = page_obj(len(pages))
    for i, page in enumerate(pages):
        annot_refs = []
        for annot in page.annots:
            objects[next_num] = Obj(annot)
            annot_refs.append(f"{next_num} 0 R")
            next_num += 1
        crop = f" /CropBox {_box(page.crop_box)}" if page.crop_box else ""
        annots = f" /Annots [{' '.join(annot_refs)}]" if annot_refs else ""
        objects[page_obj(i)] = Obj(
            f"<< /Type /Page /Parent {PAGES} 0 R /MediaBox {_box(page.media_box)}{crop} "
            f"/Resources {page.resources or RESOURCES} /Contents {content_obj(i)} 0 R{annots} >>"
        )
        objects[content_obj(i)] = Obj("<< >>", page.content.encode("latin-1"))
    form = ""
    if xfa is not None:
        objects[next_num] = Obj("<< >>", xfa)
        form = f" /AcroForm << /Fields [] /XFA {next_num} 0 R >>"
        next_num += 1
    elif acroform:
        form = " /AcroForm << /Fields [] >>"
    objects[CATALOG] = Obj(f"<< /Type /Catalog /Pages {PAGES} 0 R{form}{catalog_extra} >>")
    for num, obj in (extra or {}).items():
        if num < EXTRA or num in objects:
            raise FixtureError(num)
        objects[num] = obj
    return objects


def build_pdf(  # noqa: PLR0913 - every keyword is one document property
    pages: Sequence[Page] | Page | str,
    *,
    encryption: Encryption | None = None,
    xfa: bytes | None = None,
    acroform: bool = False,
    startxref: int | None = None,
    extra: Mapping[int, Obj] | None = None,
    catalog_extra: str = "",
) -> bytes:
    """A complete PDF. A ``str`` is the content of a single page."""
    if isinstance(pages, str):
        pages = [Page(pages)]
    elif isinstance(pages, Page):
        pages = [pages]
    objects = pdf_objects(
        pages, xfa=xfa, acroform=acroform, extra=extra, catalog_extra=catalog_extra
    )
    return write_pdf(objects, encryption=encryption, startxref=startxref)


def text_pdf(*page_texts: str) -> bytes:
    """One paragraph per page, Latin or Cyrillic."""
    return build_pdf([Page(text(t)) for t in page_texts])


def replace_content(index: int, content: str) -> dict[int, Obj]:
    """Objects for an incremental update that replaces the content of page ``index``."""
    return {content_obj(index): Obj("<< >>", content.encode("latin-1"))}


XFA_PACKET = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n'
    b'<xdp:xdp xmlns:xdp="http://ns.adobe.com/xdp/"><template '
    b'xmlns="http://www.xfa.org/schema/xfa-template/3.3/"><subform name="form1">'
    b'<field name="clause"><value><text>Synthetic XFA clause.</text></value></field>'
    b"</subform></template></xdp:xdp>\n"
)


# --- Round 1 (PR #29) fixtures -------------------------------------------------------------------


def stream_obj(content: str, dictionary: str = "<< >>") -> Obj:
    return Obj(dictionary, content.encode("latin-1"))


def form_xobject(content: str, *, bbox: str | None = "0 0 612 792") -> Obj:
    """A Form XObject with the shared resources; ``bbox=None`` omits ``/BBox``."""
    box = f" /BBox [{bbox}]" if bbox is not None else ""
    return stream_obj(content, f"<< /Type /XObject /Subtype /Form{box} /Resources {RESOURCES} >>")


def tiling_pattern(content: str) -> Obj:
    """A coloured tiling pattern whose cell runs ``content``."""
    return stream_obj(
        content,
        "<< /Type /Pattern /PatternType 1 /PaintType 1 /TilingType 1 /BBox [0 0 612 792] "
        f"/XStep 612 /YStep 792 /Resources {RESOURCES} >>",
    )


def latin_to_unicode_cmap() -> bytes:
    """A 1-byte ToUnicode CMap: codes 0x20-0x7E map to themselves."""
    entries = "\n".join(f"<{c:02X}> <{c:04X}>" for c in range(0x20, 0x7F))
    return (
        "/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        "/CMapName /Synthetic-Latin def\n/CMapType 2 def\n"
        "1 begincodespacerange\n<00> <FF>\nendcodespacerange\n"
        f"95 beginbfchar\n{entries}\nendbfchar\n"
        "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"
    ).encode()


def type3_objects(
    base: int, *, font_matrix: float = 0.001, to_unicode: bool = False
) -> dict[int, Obj]:
    """A Type3 font at ``base`` (glyph: a 1000 x 1000 unit box for codes 0x20-0x7E).

    ``base + 1`` is the glyph procedure, ``base + 2`` the optional ToUnicode CMap.
    """
    differences = " ".join(["32", *["/box"] * 95])
    widths = " ".join(["1000"] * 95)
    cmap = f" /ToUnicode {base + 2} 0 R" if to_unicode else ""
    m = _fmt(font_matrix)
    objects = {
        base: Obj(
            f"<< /Type /Font /Subtype /Type3 /FontBBox [0 0 1000 1000] "
            f"/FontMatrix [{m} 0 0 {m} 0 0] /CharProcs << /box {base + 1} 0 R >> "
            f"/Encoding << /Type /Encoding /Differences [{differences}] >> "
            f"/FirstChar 32 /LastChar 126 /Widths [{widths}] /Resources << >>{cmap} >>"
        ),
        base + 1: stream_obj("1000 0 0 0 1000 1000 d1\n100 0 800 1000 re f\n"),
    }
    if to_unicode:
        objects[base + 2] = Obj("<< >>", latin_to_unicode_cmap())
    return objects


def annot_with_ap(subtype: str, ap: int, *, flags: int = 0, extra: str = "") -> str:
    """An annotation with a normal appearance stream (object ``ap``)."""
    return (
        f"<< /Type /Annot /Subtype /{subtype} /Rect [72 300 400 340] /F {flags} "
        f"/AP << /N {ap} 0 R >>{extra} >>"
    )


def appearance(words: str) -> Obj:
    """An appearance stream (Form XObject) that shows ``words``."""
    return form_xobject(f"BT /F1 12 Tf 4 14 Td {latin_string(words)} Tj ET\n", bbox="0 0 328 40")


def drop_trailer(data: bytes) -> bytes:
    """Remove the trailer dictionary and ``startxref`` (a lost trailer)."""
    cut = data.rindex(b"trailer")
    return data[:cut] + b"%%EOF\n"


def xrefstm_loop(data: bytes) -> bytes:
    """Append a hybrid revision whose ``/XRefStm`` stream has ``/Prev`` back to itself.

    The classic section's trailer names an xref stream with ``/XRefStm``; the
    stream's ``/Prev`` points at that classic section again.
    """
    out = bytearray(data if data.endswith(b"\n") else data + b"\n")
    sizes = [int(m) for m in _SIZE.findall(data)]
    num = max(sizes)
    stm_at = len(out)
    entries = bytes([1]) + struct.pack(">I", 0) + bytes(2)  # W [1 4 2], one dummy entry
    placeholder = "0" * 10

    def stream(prev: str) -> bytes:
        head = (
            f"{num} 0 obj\n<< /Type /XRef /Size {num + 1} /Index [{num} 1] /W [1 4 2] "
            f"/Prev {prev} /Length {len(entries)} >>\nstream\n"
        ).encode()
        return head + entries + b"\nendstream\nendobj\n"

    xref_at = stm_at + len(stream(placeholder))
    out += stream(f"{xref_at:010d}")
    out += b"xref\n0 0\n"
    out += (
        f"trailer\n<< /Size {num + 1} /Root {CATALOG} 0 R /Prev {last_startxref(data)} "
        f"/XRefStm {stm_at} >>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


def linearized_pdf(page_text: str) -> bytes:
    """A one-page PDF laid out like a linearized file: one revision, two xref sections.

    Layout: header, linearization dictionary, first-page xref section (with
    ``/Prev`` to the main section), the objects, the main xref section and the
    final ``startxref`` that points at the first-page section. Numbers that refer
    forward are zero-padded, so a second pass with the real offsets keeps every
    length.
    """
    objects = pdf_objects([Page(text(page_text))])
    lin = max(objects) + 1
    first_nums = [lin, CATALOG, page_obj(0), content_obj(0)]
    main_nums = [n for n in sorted(objects) if n not in first_nums]
    file_id = FILE_ID.hex().upper()

    def layout(total: int, main_xref: int, offsets: Mapping[int, int]) -> tuple[bytes, int]:
        out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
        lin_at = len(out)
        out += (
            f"{lin} 0 obj\n<< /Linearized 1 /L {total:010d} /H [0 0] /O {page_obj(0)} "
            f"/E {total:010d} /N 1 /T {main_xref:010d} >>\nendobj\n"
        ).encode()
        first_xref = len(out)
        entries = {n: offsets.get(n, 0) for n in first_nums}
        entries[lin] = lin_at
        out += _xref_table(entries, with_free_head=False)
        out += (
            f"trailer\n<< /Size {lin + 1} /Root {CATALOG} 0 R /Prev {main_xref:010d} "
            f"/ID [<{file_id}> <{file_id}>] >>\nstartxref\n0\n%%EOF\n"
        ).encode()
        for n in sorted(objects):
            offsets_out[n] = len(out)
            out += _serialize(n, objects[n], None)
        main_at = len(out)
        out += _xref_table({n: offsets_out[n] for n in main_nums}, with_free_head=True)
        out += f"trailer\n<< /Size {lin + 1} >>\nstartxref\n{first_xref}\n%%EOF\n".encode()
        return bytes(out), main_at

    offsets_out: dict[int, int] = {}
    draft, main_at = layout(0, 0, {})
    final, _ = layout(len(draft), main_at, dict(offsets_out))
    if len(final) != len(draft):
        raise FixtureError(len(final))
    return final
