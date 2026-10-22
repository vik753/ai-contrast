"""The PDF document layer of the PDF extractor (S3-T3 AC2, AC11; ADR 0009 Layer 0).

Runs inside the parsing child (ADR 0011). ``CheckedDocument`` is a pdfminer
``PDFDocument`` with three changes:

- **Cross-reference chain.** pdfminer follows ``/Prev`` (and ``/XRefStm``) by
  recursion, without a loop guard. Here the chain is walked in a loop: a section
  offset seen twice (a loop, also a section that points at itself) or more
  ``/Prev`` links than ``max_prev_chain`` → ``PdfDamagedError``. Sections are
  appended in pdfminer's order (each section, then its ``/XRefStm``, then the
  older revision), so object lookup still prefers the latest revision.
- **Unreadable objects.** pdfminer silently falls back to an older revision when
  the latest one lists an object it cannot parse, so viewers and pdfminer could read
  different text. Here any object that a cross-reference section lists but that
  cannot be parsed → ``PdfDamagedError``.
- **Facts for warnings:** ``fallback_used`` (the cross-reference table was
  rebuilt by scanning the file) and ``revisions`` (the number of revisions,
  without the extra section of a linearized file).

- **Freed and re-numbered objects.** An object that a newer revision frees but an
  older one still lists, or that has another generation in an older section, is
  read differently by pdfminer (old revision) and by viewers (nothing, or the new
  object) → ``PdfDamagedError``. Sections of one revision (a hybrid file's table
  and its ``/XRefStm``) count as one.

Encryption: only the empty **user** password is tried. pdfminer's owner-password
fallback (R2 to R4: the empty owner password decrypts the user password; R5, R6:
the owner hash is tried first) is switched off by the handler classes below, so a
file with a non-empty user password is never opened with a guessed owner password.
``PDFPasswordIncorrect`` and ``PDFEncryptionError`` reach the caller.
"""

from __future__ import annotations

import re
from typing import ClassVar, Final

from pdfminer.pdfdocument import (
    LITERAL_CATALOG,
    PDFBaseXRef,
    PDFDocument,
    PDFNoValidXRef,
    PDFStandardSecurityHandler,
    PDFStandardSecurityHandlerV4,
    PDFStandardSecurityHandlerV5,
    PDFXRef,
    PDFXRefFallback,
    PDFXRefStream,
)
from pdfminer.pdfparser import PDFParser, PDFSyntaxError
from pdfminer.pdftypes import PDFStream, resolve1
from pdfminer.psexceptions import PSEOF, PSException
from pdfminer.utils import nunpack

# A linearized file starts with a dictionary that holds /Linearized and the file
# length /L. Only the head of the file is searched.
LINEARIZED_HEAD_BYTES: Final = 1024
_LINEARIZED: Final = re.compile(rb"/Linearized\b")
_LINEARIZED_LENGTH: Final = re.compile(rb"/L\s+(\d{1,12})\b")
# Entries of one cross-reference subsection (a larger count is a damaged table).
MAX_SUBSECTION: Final = 10_000_000


class PdfDamagedError(Exception):
    """The file cannot be read safely (``pdf_damaged``). Holds no file content."""


def _offset(value: object) -> int:
    value = resolve1(value)
    if type(value) is not int or value < 0:
        raise PDFNoValidXRef
    return value


class _TrackedXRef(PDFXRef):
    """A classic table that also remembers its free entries."""

    def __init__(self) -> None:
        super().__init__()
        self.free: set[int] = set()

    def load(self, parser: PDFParser) -> None:
        while True:
            try:
                pos, line = parser.nextline()
                line = line.strip()
                if not line:
                    continue
            except PSEOF:
                raise PDFNoValidXRef from None
            if line.startswith(b"trailer"):
                parser.seek(pos)
                break
            head = line.split(b" ")
            if len(head) != 2:  # noqa: PLR2004
                raise PDFNoValidXRef
            try:
                start, count = int(head[0]), int(head[1])
            except ValueError:
                raise PDFNoValidXRef from None
            if count < 0 or count > MAX_SUBSECTION:
                raise PDFNoValidXRef
            for objid in range(start, start + count):
                try:
                    _, entry_line = parser.nextline()
                except PSEOF:
                    raise PDFNoValidXRef from None
                fields = entry_line.strip().split(b" ")
                if len(fields) != 3:  # noqa: PLR2004
                    raise PDFNoValidXRef
                offset, generation, kind = fields
                if kind == b"f":
                    self.free.add(objid)
                    continue
                if kind != b"n" or not offset.isdigit() or not generation.isdigit():
                    continue
                self.offsets[objid] = (None, int(offset), int(generation))
        self.load_trailer(parser)


def _free_ids(xref: PDFBaseXRef) -> set[int]:
    if isinstance(xref, _TrackedXRef):
        return xref.free
    if not isinstance(xref, PDFXRefStream):
        return set()
    free: set[int] = set()
    if xref.data is None or xref.entlen is None or xref.fl1 is None:
        return free
    data, width, type_width = xref.data, xref.entlen, xref.fl1
    for start, count in xref.ranges:
        for i in range(count):
            at = width * i
            if at + width > len(data):
                break
            if type_width and nunpack(data[at : at + type_width], 1) == 0:
                free.add(start + i)
    return free


def _used(xref: PDFBaseXRef) -> dict[int, int]:
    """In-use object numbers of one section with their generations."""
    out: dict[int, int] = {}
    for objid in xref.get_objids():
        try:
            _, _, generation = xref.get_pos(objid)
        except KeyError:
            continue
        out[objid] = generation
    return out


class _UserOnlyV2(PDFStandardSecurityHandler):
    def authenticate(self, password: str) -> bytes | None:
        return self.authenticate_user_password(password.encode("latin1"))


class _UserOnlyV4(PDFStandardSecurityHandlerV4):
    def authenticate(self, password: str) -> bytes | None:
        return self.authenticate_user_password(password.encode("latin1"))


class _UserOnlyV5(PDFStandardSecurityHandlerV5):
    def authenticate(self, password: str) -> bytes | None:
        password_b = self._normalize_password(password)
        if self._password_hash(password_b, self.u_validation_salt) != self.u_hash:
            return None
        key = self._password_hash(password_b, self.u_key_salt)
        from cryptography.hazmat.backends import default_backend  # noqa: PLC0415
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes  # noqa: PLC0415

        cipher = Cipher(algorithms.AES(key), modes.CBC(bytes(16)), backend=default_backend())
        return cipher.decryptor().update(self.ue)


def _load_section(parser: PDFParser, start: int) -> PDFBaseXRef:
    """One cross-reference section (a table with its trailer, or a stream).

    Raises ``PDFNoValidXRef`` when the section cannot be read (pdfminer then
    rebuilds the table by scanning the file).
    """
    try:
        parser.seek(start)
        parser.reset()
        pos, token = parser.nexttoken()
        xref: PDFBaseXRef
        if isinstance(token, int):
            parser.seek(pos)
            parser.reset()
            xref = PDFXRefStream()
        else:
            if token is parser.KEYWORD_XREF:
                parser.nextline()
            xref = _TrackedXRef()
        xref.load(parser)
    except (PSException, ValueError, TypeError, KeyError, IndexError, AssertionError):
        raise PDFNoValidXRef from None
    return xref


class CheckedDocument(PDFDocument):
    """A ``PDFDocument`` with a guarded cross-reference chain (see the module doc)."""

    security_handler_registry: ClassVar[dict[int, type[PDFStandardSecurityHandler]]] = {
        1: _UserOnlyV2,
        2: _UserOnlyV2,
        4: _UserOnlyV4,
        5: _UserOnlyV5,
    }

    def __init__(self, parser: PDFParser, *, data: bytes, max_prev_chain: int) -> None:
        self.max_prev_chain = max_prev_chain
        self.revisions = 1
        self._linearized_length = _linearized_length(data)
        self._size = len(data)
        try:
            super().__init__(parser, password="", caching=True, fallback=True)
        except PDFSyntaxError:
            # "No /Root object": the rebuilt table found no trailer.
            if self.catalog or not self.fallback_used:
                raise
            self.catalog = self._find_catalog()

    def _find_catalog(self) -> dict[str, object]:
        """The one catalog of a file whose trailer is lost (repair, as viewers do).

        None, more than one, or an encryption dictionary → ``PdfDamagedError``.
        """
        found: list[dict[str, object]] = []
        for xref in self.xrefs:
            for objid in xref.get_objids():
                obj = self.getobj(objid)
                if not isinstance(obj, dict):
                    continue
                if {"Filter", "O", "U"} <= obj.keys():
                    raise PdfDamagedError
                if obj.get("Type") is LITERAL_CATALOG:
                    found.append(obj)
        if len(found) != 1:
            raise PdfDamagedError
        return found[0]

    @property
    def fallback_used(self) -> bool:
        return any(isinstance(xref, PDFXRefFallback) for xref in self.xrefs)

    def read_xref_from(self, parser: PDFParser, start: int, xrefs: list[PDFBaseXRef]) -> None:
        seen: set[int] = set()
        freed: set[int] = set()
        generations: dict[int, int] = {}
        links = 0
        position = start
        while True:
            if position in seen:
                raise PdfDamagedError
            seen.add(position)
            xref = _load_section(parser, position)
            xrefs.append(xref)
            group = [xref]
            trailer = xref.get_trailer()
            if "XRefStm" in trailer:
                stream_at = _offset(trailer["XRefStm"])
                if stream_at in seen:
                    raise PdfDamagedError
                seen.add(stream_at)
                stream = _load_section(parser, stream_at)
                xrefs.append(stream)
                group.append(stream)
                if "Prev" in stream.get_trailer() and _offset(stream.get_trailer()["Prev"]) in seen:
                    raise PdfDamagedError
            self._check_revision(group, freed, generations)
            if "Prev" not in trailer:
                break
            links += 1
            if links > self.max_prev_chain:
                raise PdfDamagedError
            # The revision count is known before an older section fails to load.
            self.revisions = self._count_revisions(links)
            position = _offset(trailer["Prev"])
        self.revisions = self._count_revisions(links)

    @staticmethod
    def _check_revision(
        group: list[PDFBaseXRef], freed: set[int], generations: dict[int, int]
    ) -> None:
        """Compare one revision with the newer ones seen before (module doc)."""
        used: dict[int, int] = {}
        free_now: set[int] = set()
        for xref in group:
            used.update(_used(xref))
            free_now |= _free_ids(xref)
        for objid, generation in used.items():
            if objid == 0:
                continue
            if objid in freed or generations.setdefault(objid, generation) != generation:
                raise PdfDamagedError
        freed |= {objid for objid in free_now if objid not in used and objid != 0}

    def _count_revisions(self, links: int) -> int:
        # A linearized file that was not updated has two sections and one revision.
        if links and self._linearized_length == self._size:
            return links
        return links + 1

    def _getobj_parse(self, pos: int, objid: int) -> object:
        try:
            return super()._getobj_parse(pos, objid)
        except (PSEOF, PDFSyntaxError):
            # pdfminer would try an older revision: viewers may show other text.
            raise PdfDamagedError from None

    def _getobj_objstm(self, stream: PDFStream, index: int, objid: int) -> object:
        try:
            return super()._getobj_objstm(stream, index, objid)
        except (PSEOF, PDFSyntaxError):
            raise PdfDamagedError from None


def _linearized_length(data: bytes) -> int | None:
    head = data[:LINEARIZED_HEAD_BYTES]
    if not _LINEARIZED.search(head):
        return None
    match = _LINEARIZED_LENGTH.search(head)
    return int(match.group(1)) if match else None
