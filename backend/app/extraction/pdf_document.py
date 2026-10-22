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

Encryption is pdfminer's: the document is opened with the empty user password
only. ``PDFPasswordIncorrect`` and ``PDFEncryptionError`` reach the caller.
"""

from __future__ import annotations

import re
from typing import Final

from pdfminer.pdfdocument import (
    LITERAL_CATALOG,
    PDFBaseXRef,
    PDFDocument,
    PDFNoValidXRef,
    PDFXRef,
    PDFXRefFallback,
    PDFXRefStream,
)
from pdfminer.pdfparser import PDFParser, PDFSyntaxError
from pdfminer.pdftypes import PDFStream
from pdfminer.psexceptions import PSEOF, PSException

# A linearized file starts with a dictionary that holds /Linearized and the file
# length /L. Only the head of the file is searched.
LINEARIZED_HEAD_BYTES: Final = 1024
_LINEARIZED: Final = re.compile(rb"/Linearized\b")
_LINEARIZED_LENGTH: Final = re.compile(rb"/L\s+(\d{1,12})\b")


class PdfDamagedError(Exception):
    """The file cannot be read safely (``pdf_damaged``). Holds no file content."""


def _offset(value: object) -> int:
    from pdfminer.pdftypes import resolve1  # noqa: PLC0415 - keep the import list short

    value = resolve1(value)
    if type(value) is not int or value < 0:
        raise PDFNoValidXRef
    return value


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
            xref = PDFXRef()
        xref.load(parser)
    except (PSException, ValueError, TypeError, KeyError, IndexError, AssertionError):
        raise PDFNoValidXRef from None
    return xref


class CheckedDocument(PDFDocument):
    """A ``PDFDocument`` with a guarded cross-reference chain (see the module doc)."""

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
        links = 0
        position = start
        while True:
            if position in seen:
                raise PdfDamagedError
            seen.add(position)
            xref = _load_section(parser, position)
            xrefs.append(xref)
            trailer = xref.get_trailer()
            if "XRefStm" in trailer:
                stream_at = _offset(trailer["XRefStm"])
                if stream_at in seen:
                    raise PdfDamagedError
                seen.add(stream_at)
                xrefs.append(_load_section(parser, stream_at))
            if "Prev" not in trailer:
                break
            links += 1
            if links > self.max_prev_chain:
                raise PdfDamagedError
            # The revision count is known before an older section fails to load.
            self.revisions = self._count_revisions(links)
            position = _offset(trailer["Prev"])
        self.revisions = self._count_revisions(links)

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
