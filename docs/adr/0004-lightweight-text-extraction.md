# ADR 0004 — Lightweight text extraction: own DOCX walker and pdfminer.six

- Status: accepted
- Date: 2026-10-19

## Context

The first plan used Docling or Unstructured. Docling depends on PyTorch and layout models. It does not fit into the 512 MB RAM of the Render free tier.
PyMuPDF is fast but licensed under AGPL with a commercial option; we keep dependencies under permissive licenses where possible.

## Decision

- PDF with a text layer: `pdfminer.six` (MIT) with our own render-mode device. No pdfplumber (see the revision below).
- DOCX: our own reader and walker over the ZIP package, after archive checks (zip bomb, ZIP layout), with `defusedxml` (PSF) and `forbid_dtd=True`. No python-docx (see the revision below).
- Plain text: built-in decoding with charset detection limited to UTF-8, UTF-16 and CP1251.
- Scans: OCR in the browser with Tesseract.js. ("OCR via AI" was removed by ADR 0008: page images cannot be pseudonymized.)
- Parsing runs in a subprocess with time and memory limits.

## Consequences

- Small image, fits the free tier.
- Complex layouts (multi-column, tables) may extract worse than with ML-based tools. The eval set will measure this.

## Revision (2026-10-20, ADR 0008 and ADR 0009)

- DOCX parts are resolved through package relationships, as Word does: the main part is the target of the single `officeDocument` relationship in `_rels/.rels`; footnotes, endnotes, headers and footers are targets of the main part's relationships. A package with more than one `officeDocument` relationship, or with a `word/document.xml` that is not the target, is rejected as suspicious. Strict OOXML is rejected in v1. Zero extracted text is an error.
- DOCX text is read by our own walker over those parts (defusedxml, element allowlist), not by python-docx `paragraph.text`, which skips tracked insertions, content controls, text boxes, smart tags, custom XML and fields. python-docx is not used at all (decision of 2026-10-21, ADR 0011): the archive is read by our own checked ZIP reader (`app/extraction/docx_zip.py`) and every part is parsed by `defusedxml` with `forbid_dtd=True`, streaming, with depth and element caps.
- Hidden DOCX text is detected with effective formatting (docDefaults → styles → direct formatting).
- PDF text is extracted with a custom pdfminer device that records the text render mode (pdfplumber is not used: its characters do not carry the render mode); only provably invisible text is dropped. Cross-reference reconstruction (damaged PDF) produces a material "Not read" warning.
- Material content we do not read (`altChunk`, OLE objects, PDF FreeText/Text/Widget annotations with values, unreadable form values, image-heavy pages that are not the signature page) is reported as "Not read" per document (ADR 0009 Layer 0).
- Document metadata (DOCX `docProps`, PDF Info and XMP) and embedded files are never parsed into text.
- All cleaning and detection run inside the parsing subprocess with time and memory limits.
