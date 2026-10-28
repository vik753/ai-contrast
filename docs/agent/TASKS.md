# Tasks

Format: one task per block. Goal, owner, branch, acceptance criteria (AC), threats touched (see `docs/security/threat-model.md`).
Check a task only when it is merged to `main` with green CI.

Finished stages 0 to 4: `docs/agent/TASKS-archive.md`.

Next: stage 5 — see below.

## Stage 5 — Clause splitting

Design: ADR 0014 (clause segmentation), ADR 0011 (sandbox), ADR 0009 (no clause hidden, caps fail closed, linear-time patterns), ADR 0008 point 2 (requisites headings). Threats: T3, T5, T6.

Order: S5-T0 (fixtures) and the S5-T1 tests in parallel; then S5-T1 (backend); S5-T2 (frontend) after S5-T1 is merged; S5-T3 docs last.

### S5-T0 Segmentation fixtures

- Owner: `domain-analyst`. Branch: `feat/s5-segment` (same branch as S5-T1; fixtures only).
- Synthetic contracts (no real names or identifiers) as JSON block lists in `backend/tests/fixtures/segment/`, each with the expected clause numbers, headings, `section_kind` and warnings: UK, RU and EN; decimal numbering to three levels; `Стаття`/`Статья`/`Article` styles; Roman sections; lettered sub-items (`а)`, `(a)`, `(i)`); all-caps and numbered headings; a preamble; a requisites section (`Реквізити та підписи сторін`, `Реквизиты и подписи сторон`, `Signatures`); footnotes; a PDF-like file with running headers and footers on every page and a clause across a page break; a file with no numbering; files with a numbering gap, a restart and a duplicate number; an annex with its own numbering. At least 15 files. A `README.md` in that folder lists them.

### S5-T1 Segmentation endpoint (backend)

- Owner: `backend-dev`. Tests first: `test-engineer`. Branch: `feat/s5-segment` (worktree `/home/claude/wt/s5-segment`).
- Threats: T1, T3, T5, T6.

1. **Pure function** `app/segment/segmenter.py`: `segment(blocks: Sequence[InputBlock], *, limits: SegmentLimits) -> SegmentResult` (raises `SegmentError(code)`). Deterministic. Rules exactly as ADR 0014 points 4–8.
2. **Output contract** (`200`):
   ```json
   {
     "clauses": [{
       "id": "c1", "number": "3.2" | null, "level": 2, "part_index": 0,
       "heading": "Страхова сума" | null, "section_kind": "requisites" | null,
       "part": "body" | "footnote" | "endnote" | "header" | "footer" | "textbox" | "running" | "preamble",
       "pages": [3, 4], "spans": [[0, 0, 120], [1, 0, 37]], "text": "…"
     }],
     "removed": [{ "reason": "<code>", "count": 1, "sample": "…" }],
     "warnings": [{ "code": "numbering_gap", "clause": "c7" }]
   }
   ```
   `id` is `c1…cN` in document order. `spans` are `[block_index, start, end]` into the cleaned input blocks; `text` equals the span texts joined with `\n`. `pages` is `[]` for DOCX and text. `level` 0 for preamble, running and fallback clauses.
3. **Cover test (property):** for every fixture and for random inputs, the spans of all clauses cover every non-white-space character of the cleaned input exactly once, in order (running-header duplicates: the repeated occurrences are covered by the one `running` clause, whose `spans` list every occurrence).
4. **Sandbox:** worker kind `segment` (ADR 0011): the JSON request is passed to the child as bytes; the child validates, cleans (the same `normalize` as extraction, `removed` reported), segments and replies. Same memory, CPU and wall limits as extraction; same result-size cap (`extract_max_result_bytes`). Errors map like extraction (`extraction_timeout` → `segment_timeout`, `extraction_failed` → `segment_failed`).
5. **Endpoint** `POST /api/segment`:
   - `Content-Type: application/json` (else `415`, header check before the slot, `early_error`);
   - body limit `SEGMENT_MAX_BODY_BYTES` (4 MiB) for this exact path (`413 request_too_large`); the slot is taken before the body is read (`503 busy` with `Retry-After`), the body is read within `SEGMENT_BODY_TIMEOUT_SECONDS` (30) → `408 upload_timeout`, then validated;
   - body `{"blocks": [{"text": str, "part": <extract part enum>, "page": int | null}]}` — no other fields; at most `extract_max_blocks` blocks and `extract_max_text_chars` characters in total, else `422 too_much_text`; `page` 1–`max_pdf_pages` or `null`; malformed → `422 invalid_request`; empty text overall → `422 no_text_extracted`; errors are `{"error": "<code>"}` and never echo input;
   - new error codes: `too_many_clauses`, `clause_too_long`, `segment_timeout`, `segment_failed` (`422`, `504` for the timeout, `500`-class never echoes);
   - `Cache-Control: no-store`; logging: method, path, status, duration, counts only. Extend the log canary test: a canary string inside a block never appears in logs.
6. **Linear time:** a test feeds adversarial input at the caps (1,000,000 characters: one line of digits and dots, `1.1.1.1…`, thousands of `а)` items, long all-caps lines, 20,000 tiny blocks) and the child finishes within the CPU limit. Patterns are anchored with bounded repetition; a policy test rejects nested quantifiers in `app/segment/`.
7. **Caps:** `SEGMENT_MAX_CLAUSES` (2,000) and `SEGMENT_MAX_CLAUSE_CHARS` (20,000), validated like other settings. Every cap has a test; nothing is truncated.
8. Fixtures from S5-T0: every fixture gives exactly the expected numbers, headings, `section_kind` and warnings.

### S5-T2 Clauses in the browser (frontend)

- Owner: `frontend-dev`. Tests first: `test-engineer`. Branch: `feat/s5-clauses` (worktree `/home/claude/wt/s5-clauses`). After S5-T1 is merged.
- Threats: T3 (control 7), T6.

1. After a row is accepted and has no OCR pages left, the browser calls `POST /api/segment` with that row's blocks (OCR blocks for scanned pages included, in page order), through the existing scheduler (at most two requests in flight, `busy` retry with a capped delay), with the same fetch options as uploads (`credentials: "omit"`, `redirect: "error"`, `cache: "no-store"`) and strict response validation with caps (clause count, spans inside the sent blocks, `text` equal to the joined spans — a mismatch is `invalid_response`).
2. Row states: the row shows "Splitting into clauses…" while the request runs, then the clause count. Segment errors are shown on the row with their own messages (all codes of S5-T1, all three languages); the row stays in the contract; "Try again" re-sends.
3. Clauses live only in memory next to the extracted text and are dropped with the row (T3 control 7); never in storage, URLs, the console or announcements.
4. Preview: a "Clauses" / "Text" switch. "Clauses" shows each clause as plain text with its number and heading, `part` label (footnote, running header, preamble…), a "Requisites" badge for `section_kind: "requisites"`, and the warnings. Long lists use the existing preview caps and "Show all".
5. Readiness: a contract is ready only when every row has clauses. Removing a row aborts its segment request.
6. Tests (Vitest): request body and options, validation failures, every error code shown, retry, abort on removal, preview switch, no storage writes.

### S5-T3 Docs for stage 5

- Owner: `docs-writer`. After S5-T1 and S5-T2 are merged.
- Threat model: T5 control 6 (segmentation in the sandbox, linear-time patterns, clause caps), T6 (new endpoint: body limit, slot, deadline; add to the stage 13 per-IP limit list). ADR 0014 → accepted. `CLAUDE.md` Commands: a `curl` check for `/api/segment`. README status.

## Open follow-ups

### S2-T0 Lint follow-up (from PR #3 security re-review)

- TS files: string eval through global-object members (`window.eval`, `self.eval`, `self.setInterval("…")`) is reported. Shared browser-globals map for all sources; core `no-implied-eval` on for TS too; ban `x.eval` member access with a T1 message; tests in a `.ts` fixture.
- Optional (code review NIT): `changeLanguage()` before setup uses `setupFallbackI18n()`.
- Policy test (PR #10 security review): no `versions:` in any `dependency-name: "*"` ignore entry in any ecosystem; every wildcard entry has `update-types` without `version-update:semver-patch`.
- Recurring per stage: run `npm outdated` (frontend) and `uv tree --outdated` (backend) and plan major upgrades (TypeScript 7 with typescript-eslint, jsdom 30 with Node ≥ 22.22.2).

### S2 follow-ups (from the ADR 0008/0009 design review, for later stages)

- Stage 6 / before stage 13 (**release blocker**): at most 1 extraction slot per client IP (T6 control 6 client-IP rule).
- Stage 3 (not yet checked, do it in stage 4 or 5): test detection against a corpus of real UK/RU DOCX files (some generators store raw UTF-8 part names, now `archive_rejected`); the `archive_rejected` message tells the user to save the file again in Word or export to PDF.
- Effective upload minimum: a 10 MiB file needs about 1.4 Mbit/s to finish within 60 s; the `upload_timeout` message mentions a slow connection or a smaller file.
- Stage 3 and 5b: tests on clean UK and RU contracts show no mixed-script and no overlap flags (combining marks excluded).
- Stage 10 polish: show limits in messages with the `upload.size.mb` template ("10 MB") and narrow the size test to `.file-row__size` (code review PR #16).
- Stage 8: model tags that push a topic over its cap are dropped; a topic not analyzed shows 🟡.
- Stage 9: global-override markers; "at most one document per call" policy test.

### Stage 9/10 follow-ups (from stage 4)

- Stage 10: subscribe the app's store to the `storage` event (`subscribeHistoryChanges`) and switch to `DisabledCacheStore` when history is turned off in another tab.
- Stage 9: one `CacheKey` type. The port uses `string`; the hash module uses a branded type. Unify them.
- Stage 9: `contractTextHash` stays `null` after a text-hash failure. Handle this case.
- Stage 10: `list()` parses every record (up to 100 × 2 MiB). Check the cost.

### Stage 13 blockers and follow-ups (from stage 3)

- Stage 13 blockers: header-read timeout / slowloris with `--limit-concurrency 32`, and kernel send buffers of cut-off connections (threat model T6 control 9).
- Measure the 100-page PDF worst case on Render's CPU (9.3 s CPU here); lower `MAX_PDF_PAGES` or raise the wall limit if it exceeds 30 s.
