# ADR 0004 — Lightweight text extraction: pdfplumber and python-docx

- Status: accepted
- Date: 2026-10-19

## Context

The first plan used Docling or Unstructured. Docling depends on PyTorch and layout models. It does not fit into the 512 MB RAM of the Render free tier.
PyMuPDF is fast but licensed under AGPL with a commercial option; we keep dependencies under permissive licenses where possible.

## Decision

- PDF with a text layer: `pdfplumber` (MIT).
- DOCX: `python-docx` (MIT), after archive checks (zip bomb) and with safe XML parsing.
- Plain text: built-in decoding with charset detection limited to UTF-8, UTF-16 and CP1251.
- Scans: OCR in the browser with Tesseract.js. ("OCR via AI" was removed by ADR 0008: page images cannot be pseudonymized.)
- Parsing runs in a subprocess with time and memory limits.

## Consequences

- Small image, fits the free tier.
- Complex layouts (multi-column, tables) may extract worse than with ML-based tools. The eval set will measure this.
