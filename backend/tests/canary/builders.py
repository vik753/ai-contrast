# ruff: noqa: E501 - XML snippets are easier to read on one line
"""Documents for every input path and location (ADR 0015 point 6).

Input paths: ``txt`` (UTF-8 upload), ``docx`` (built in the test), ``pdf`` (built with
``tests/pdfbuild.py``), ``ocr`` (blocks as the browser OCR would send them straight to
``/api/segment``) and ``gdoc`` (a Google export DOCX served by the fake transport).

A location is a place in the document where text exists. One document holds all
canaries of one location, so a run costs one extract, one segment and one safety call.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from tests.canary.catalogue import CANARIES, Canary
from tests.docxbuild import (
    Package,
    Rel,
    build_docx,
    p,
    para,
    r,
    rels_xml,
)
from tests.pdfbuild import CYR_CHARS, Obj, Page, build_pdf, lines, text

PATHS = ("txt", "ocr", "docx", "pdf", "gdoc")
REQUISITES_HEADINGS = {
    "uk": "Реквізити та підписи сторін",
    "ru": "Реквизиты и подписи сторон",
    "en": "Signatures",
}
TEXT_LOCATIONS = (
    "preamble",
    "body",
    "heading",
    *[f"requisites-{lang}" for lang in REQUISITES_HEADINGS],
)
DOCX_LOCATIONS = (
    *TEXT_LOCATIONS,
    "footnote",
    "endnote",
    "header",
    "footer",
    "textbox",
    "tracked-insertion",
    "content-control",
)
LOCATIONS: dict[str, tuple[str, ...]] = {
    "txt": TEXT_LOCATIONS,
    "ocr": (*TEXT_LOCATIONS, "wrapped"),
    "docx": DOCX_LOCATIONS,
    "pdf": (*TEXT_LOCATIONS, "running-header", "running-footer"),
    "gdoc": DOCX_LOCATIONS,
}
FILLER = "Загальні положення договору."


def pdf_can_show(canary: Canary) -> bool:
    return all(ch in CYR_CHARS or (ord(ch) <= 0xFF and ch != "­") for ch in canary.text) and (
        "\n" not in canary.text
    )


def applicable(path: str, location: str) -> list[Canary]:
    """The canaries planted in one cell."""
    chosen = [c for c in CANARIES if c.only_paths is None or path in c.only_paths]
    if location.startswith("requisites-"):
        lang = location.removeprefix("requisites-")
        chosen = [c for c in chosen if c.lang == lang]
    if path == "pdf":
        chosen = [c for c in chosen if pdf_can_show(c)]
        if location.startswith("running-"):
            chosen = [c for c in chosen if c.core]
    return chosen


def _units(location: str, canaries: Sequence[Canary]) -> list[str]:
    """Paragraph texts of the text-like locations."""
    if location.startswith("requisites-"):
        lang = location.removeprefix("requisites-")
        return [REQUISITES_HEADINGS[lang], *[c.text for c in canaries]]
    if location == "body":
        return [f"{i}. {c.text}" for i, c in enumerate(canaries, 1)]
    if location == "heading":
        return [f"Article {i}. {c.text}" for i, c in enumerate(canaries, 1)]
    return [c.text for c in canaries]  # preamble and everything else


def _wrap_soft(value: str) -> str:
    """OCR-like soft line wrap: the first space after column 40 becomes a line break."""
    match = re.search(r" ", value[40:])
    if match is None or "\n" in value:
        return value
    at = 40 + match.start()
    return value[:at] + "\n" + value[at + 1 :]


# ------------------------------------------------------------------------------ DOCX


def _textbox(value: str) -> str:
    inner = f"<w:txbxContent>{para(value)}</w:txbxContent>"
    choice = (
        '<mc:Choice Requires="wps"><w:drawing><wp:anchor><a:graphic><a:graphicData>'
        f"<wps:wsp><wps:txbx>{inner}</wps:txbx></wps:wsp>"
        "</a:graphicData></a:graphic></wp:anchor></w:drawing></mc:Choice>"
    )
    fallback = (
        f"<mc:Fallback><w:pict><v:shape><v:textbox>{inner}</v:textbox></v:shape></w:pict>"
        "</mc:Fallback>"
    )
    return p(r(inner=f"<mc:AlternateContent>{choice}{fallback}</mc:AlternateContent>"))


def _heading(value: str) -> str:
    return para(value, ppr='<w:pStyle w:val="Heading1"/>')


def _content_control(value: str) -> str:
    sdt = f'<w:sdt><w:sdtPr><w:alias w:val="Field"/></w:sdtPr><w:sdtContent>{r(value)}</w:sdtContent></w:sdt>'
    return f"<w:p>{sdt}</w:p>"


def _tracked(index: int, value: str) -> str:
    ins = f'<w:ins w:id="{index}" w:author="Test" w:date="2026-01-01T00:00:00Z">{r(value)}</w:ins>'
    return f"<w:p>{ins}</w:p>"


def docx_package(  # noqa: PLR0911 - one return per location
    location: str, canaries: Sequence[Canary], **extra: Any
) -> Package:
    texts = [c.text for c in canaries]
    units = _units(location, canaries)
    filler = para(FILLER)
    if location == "heading":
        return Package(body=filler + "".join(_heading(u) for u in units), **extra)
    if location == "footnote":
        return Package(body=filler, footnotes=[para(t) for t in texts], **extra)
    if location == "endnote":
        return Package(body=filler, endnotes=[para(t) for t in texts], **extra)
    if location == "header":
        return Package(body=filler, headers=["".join(para(t) for t in texts)], **extra)
    if location == "footer":
        return Package(body=filler, footers=["".join(para(t) for t in texts)], **extra)
    if location == "textbox":
        return Package(body=filler + "".join(_textbox(t) for t in texts), **extra)
    if location == "tracked-insertion":
        return Package(
            body=filler + "".join(_tracked(i, t) for i, t in enumerate(texts, 1)), **extra
        )
    if location == "content-control":
        return Package(body=filler + "".join(_content_control(t) for t in texts), **extra)
    first = filler if location != "preamble" and not location.startswith("requisites-") else ""
    return Package(body=first + "".join(para(u) for u in units), **extra)


def build_docx_for(location: str, canaries: Sequence[Canary]) -> bytes:
    return build_docx(docx_package(location, canaries))


# -------------------------------------------------------------------------------- PDF


def _chunks(value: str, width: int = 80) -> list[str]:
    words, rows, row = value.split(" "), [], ""
    for word in words:
        if row and len(row) + 1 + len(word) > width:
            rows.append(row)
            row = word
        else:
            row = f"{row} {word}".strip()
    rows.append(row)
    return rows


def _paragraph_pages(units: Sequence[str]) -> list[Page]:
    pages: list[Page] = []
    content, y = "", 740.0
    for unit in units:
        rows = _chunks(unit)
        need = len(rows) * 10 + 16
        if y - need < 50:
            pages.append(Page(content))
            content, y = "", 740.0
        content += lines(rows, x=36, top=y, leading=10, size=8)
        y -= need
    pages.append(Page(content))
    return pages


def build_pdf_for(location: str, canaries: Sequence[Canary]) -> bytes:
    if location.startswith("running-"):
        rows = [row for c in canaries for row in _chunks(c.text)]
        top = 780.0 if location == "running-header" else 20.0 + 10 * len(rows)
        furniture = lines(rows, x=36, top=top, leading=9, size=7)
        return build_pdf(
            [Page(furniture + text(f"{FILLER} Page {n}.", 72, 400)) for n in range(1, 4)]
        )
    return build_pdf(_paragraph_pages(_units(location, canaries)))


def pdf_with_metadata(canary: str) -> bytes:
    """A PDF whose Info dictionary and XMP stream hold the canary (text outside content)."""
    info = Obj(
        f"<< /Title ({canary}) /Author ({canary}) /Subject ({canary}) /Keywords ({canary}) >>"
    )
    xmp = (
        '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?><x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:title>{canary}</dc:title><dc:creator>{canary}</dc:creator></rdf:Description>"
        '</rdf:RDF></x:xmpmeta><?xpacket end="w"?>'
    ).encode()
    data = build_pdf(
        Page(text(FILLER, 72, 700)),
        extra={5000: info, 5001: Obj("<< /Type /Metadata /Subtype /XML >>", xmp)},
        catalog_extra=" /Metadata 5001 0 R",
    )
    return data.replace(b"/Root 1 0 R", b"/Root 1 0 R /Info 5000 0 R", 1)


def docx_with_properties(canary: str) -> bytes:
    """A DOCX whose docProps (core, app, custom) hold the canary."""
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:title>{canary}</dc:title><dc:creator>{canary}</dc:creator>"
        f"<cp:keywords>{canary}</cp:keywords><cp:lastModifiedBy>{canary}</cp:lastModifiedBy>"
        "</cp:coreProperties>"
    ).encode()
    app = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
        f"<Company>{canary}</Company><Manager>{canary}</Manager></Properties>"
    ).encode()
    custom = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties">'
        f'<property fmtid="{{D5CDD505-2E9C-101B-9397-08002B2CF9AE}}" pid="2" name="Client"><lpwstr>{canary}</lpwstr></property>'
        "</Properties>"
    ).encode()
    base = "http://schemas.openxmlformats.org"
    root = rels_xml(
        [
            Rel(
                "rId1",
                f"{base}/officeDocument/2006/relationships/officeDocument",
                "word/document.xml",
            ),
            Rel(
                "rId2",
                f"{base}/package/2006/relationships/metadata/core-properties",
                "docProps/core.xml",
            ),
            Rel(
                "rId3",
                f"{base}/officeDocument/2006/relationships/extended-properties",
                "docProps/app.xml",
            ),
            Rel(
                "rId4",
                f"{base}/officeDocument/2006/relationships/custom-properties",
                "docProps/custom.xml",
            ),
        ]
    )
    package = Package(
        body=para(FILLER),
        root_rels=root,
        extra=[
            ("docProps/core.xml", core),
            ("docProps/app.xml", app),
            ("docProps/custom.xml", custom),
        ],
    )
    return build_docx(package)


def ocr_blocks(location: str, canaries: Sequence[Canary]) -> list[dict[str, Any]]:
    units = _units(location, canaries)
    if location == "wrapped":
        units = [_wrap_soft(f"{i}. {c.text}") for i, c in enumerate(canaries, 1)]
    return [{"text": u, "part": "body", "page": 1 + i // 12} for i, u in enumerate(units)]


def txt_bytes(location: str, canaries: Sequence[Canary]) -> bytes:
    return "\n\n".join(_units(location, canaries)).encode("utf-8")
