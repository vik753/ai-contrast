# ADR 0014 — Clause segmentation

- Status: proposed (tech lead, 2026-10-28; waiting for `security-reviewer`)
- Date: 2026-10-28
- Related: ADR 0008 (pseudonymization works on clauses and the requisites section), ADR 0009 (no clause can be hidden; every cap fails closed; linear-time patterns in the parsing subprocess), ADR 0011 (sandbox), threat model T5, T6

## Context

Stage 5 splits the text of each document into clauses by numbering and headings, without AI (`docs/plan.md`, pipeline step 4). Later stages depend on it: stage 5b masks identifiers per clause and processes the requisites section line by line; stage 8 tags clauses with topics; stage 9 rates them and verifies quotes; cross-references ("subject to clause 12") need clause numbers.

Text comes from two places: the `/api/extract` response (PDF text layer, DOCX, TXT, Google Docs) and browser OCR of scanned pages. OCR text exists only in the browser. The server stores nothing (ADR 0001).

## Decision

1. **One endpoint for every source:** `POST /api/segment`. The browser sends the blocks of **one file** (the `/api/extract` blocks, or the OCR blocks of a scanned file) and gets the clauses back. One file per request; the server keeps nothing. Stage 5b extends the same step with identifier detection, so the input always passes the same server code.
2. **Untrusted input.** The body is treated like an upload: JSON size limit 4 MiB for this path only, the same caps as extraction (1,000,000 characters, 20,000 blocks), strict schema (no extra fields), the extraction slot is taken before the body is read and held to the end, a body deadline. The server runs the same input cleaning as extraction (ADR 0009 Layer 1) and reports what it removed; OCR text is never trusted to be clean.
3. **Runs in the sandbox** (ADR 0011): a new worker kind `segment` in the same child process model, with the same memory, CPU and wall limits. All patterns are linear-time (anchored, no nested quantifiers, bounded repetition); a test runs adversarial inputs of the maximum size within the CPU limit.
4. **Deterministic and verbatim.** The same input always gives the same clauses. Clause text is never rewritten: each clause carries `spans` (block index, start, end) into the cleaned input, and its `text` is the exact concatenation of those spans joined with `\n`. Quotes (stage 9) and masks (stage 5b) map back to these offsets.
5. **No clause is lost.** Every non-empty character of the input belongs to exactly one clause (a test checks the cover). Text before the first numbered clause becomes a `preamble` clause. Footnotes, endnotes, text boxes, headers and footers become their own clauses with their `part` (ADR 0009). Lines repeated at the top or bottom of at least 3 pages and of at least half of the pages (PDF running headers and footers) become one clause with `part: "running"` and the list of pages, instead of one clause per page.
6. **Structure.** Clause starts: decimal numbering (`1.`, `1.2.`, `1.2.3`, `1)`, `1.2)`), article words (`Стаття 5`, `Статья 5`, `Article 5`, `Section 5`, `Розділ 2`, `Раздел 2`, `Пункт 3`, `§ 4`), Roman section numbers (`IV.`). Lettered items (`а)`, `б)`, `a)`, `(a)`, `(i)`) stay inside their parent clause, because they usually continue one obligation. Headings: a short line (at most 150 characters) without final punctuation that is a numbered section title, all capitals, or followed by numbered clauses. Each clause has `number` (as written, e.g. `3.2`), `level`, `heading` (the nearest section heading) and `section_kind` (`requisites` when the heading matches the ADR 0008 list, else `null`).
7. **Fallback.** If no numbering is found, each body block becomes a clause and the result has the warning `no_numbering_found`. Other warnings (codes only): `numbering_gap`, `numbering_restart`, `duplicate_number`.
8. **Caps fail closed.** At most 2,000 clauses per file (`too_many_clauses`, `422`); at most 20,000 characters per clause — a longer clause is split at block boundaries into parts with the same number and `part_index`; a single block over 20,000 characters is split at line breaks; if a line itself is longer, the request fails with `clause_too_long`. Nothing is truncated.
9. **Logging:** method, path, status, duration, counts only. Never clause text, numbers or headings.
10. **Browser.** After a file is accepted (and OCR is finished), the browser calls `/api/segment` through the same scheduler as uploads (at most two requests in flight, `busy` retry). The clauses live in memory next to the extracted text (T3 control 7) and are dropped with the row. The preview gets a "Clauses" view: number, heading and text as plain text, warnings, and the clause count.

## Consequences

- Positive: one path for every source; the server re-checks OCR text; offsets make quotes and masks exact; stage 5b adds detection in the same step.
- Negative: the text crosses the network a second time (the browser already has it). Accepted: the server stores nothing, and stage 5b needs the server pass anyway.
- Residual risk: numbering heuristics will mis-split some contracts (tables, unusual numbering). The "Clauses" view lets the client see this; a mis-split clause is still analyzed, because nothing is dropped.
