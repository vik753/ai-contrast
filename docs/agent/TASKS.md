# Tasks

Format: one task per block. Goal, owner, branch, acceptance criteria (AC), threats touched (see `docs/security/threat-model.md`).
Check a task only when it is merged to `main` with green CI.

Finished stages 0 and 1: `docs/agent/TASKS-archive.md`.

## Open follow-ups from stage 1

### S2-T0 Lint follow-up (from PR #3 security re-review)

- TS files: string eval through global-object members (`window.eval`, `self.eval`, `self.setInterval("…")`) is reported. Shared browser-globals map for all sources; core `no-implied-eval` on for TS too; ban `x.eval` member access with a T1 message; tests in a `.ts` fixture.
- Optional (code review NIT): `changeLanguage()` before setup uses `setupFallbackI18n()`.
- Policy test (PR #10 security review): no `versions:` in any `dependency-name: "*"` ignore entry in any ecosystem; every wildcard entry has `update-types` without `version-update:semver-patch`.
- Recurring per stage: run `npm outdated` (frontend) and `uv tree --outdated` (backend) and plan major upgrades (TypeScript 7 with typescript-eslint, jsdom 30 with Node ≥ 22.22.2).

## Stage 2 — File upload

Design: ADR 0010 (one file per request, raw bytes, no multipart). Threats: T3, T4, T6, T11.

### Limits (initial values; settings on the server, constants in the browser)

| Limit | Value | Enforced by |
| --- | --- | --- |
| File size | 10 MiB (10,485,760 bytes) | browser; server on `/api/extract` |
| Files per contract (main text plus annexes) | 5 | browser; server on the analysis request (stage 9) |
| Contracts per analysis | 5 (free mode: 2, stage 6) | browser; server on the analysis request (stage 9) |
| Total size of one analysis | 50 MiB | browser |
| Pages per document / per analysis | 100 / 300 (free mode: 30 in total) | server, stage 3 |
| JSON request body | 64 KiB | server, every route except `/api/extract` |
| Extractions in progress | 2 per server | server |
| ZIP entries | 2,000 | server |
| Declared uncompressed ZIP size | 100 MiB (the real size is enforced while decompressing, stage 3) | server |
| Compression ratio of one ZIP entry | 200 | server |
| Body read deadline / minimum average rate | 60 s / 32 KiB/s after a 5 s grace period | server (`/api/extract`) |

### API contract: `POST /api/extract` (stage 2; stage 3 adds the extracted text to the `200` response)

Request: the body is the raw bytes of one file. Headers: `Content-Type: application/octet-stream` (media type compared without parameters, case-insensitive) and `Content-Length`. No `Transfer-Encoding`. No file name anywhere.

| Status | Body | When |
| --- | --- | --- |
| 200 | `{"kind": "pdf" \| "docx" \| "text", "bytes": <int>}` | The file is accepted. `bytes` is the number of body bytes received. |
| 400 | `{"error": "length_mismatch"}` | The number of body bytes received differs from `Content-Length`. |
| 408 | `{"error": "upload_timeout"}` | The body is not complete within the deadline, or its average rate falls below the minimum after the grace period. |
| 411 | `{"error": "length_required"}` | No `Content-Length` header, a non-numeric one, or any `Transfer-Encoding` header (also together with `Content-Length`). |
| 413 | `{"error": "file_too_large"}` | `Content-Length` is above the limit (rejected before the body is read), or the body grows above the limit. |
| 415 | `{"error": "unsupported_media_type"}` | Any other `Content-Type`, or none. |
| 422 | `{"error": "empty_file"}` | Zero bytes. |
| 422 | `{"error": "unsupported_type"}` | Not PDF, DOCX or plain text: images, RTF, ODF, XLSX, PPTX, other ZIP files, binary data. |
| 422 | `{"error": "legacy_office_unsupported"}` | OLE2 container: an old `.doc` file or a password-protected Office file. |
| 422 | `{"error": "pages_unsupported"}` | Apple Pages archive. |
| 422 | `{"error": "archive_rejected"}` | A ZIP file fails a structure check. |
| 503 | `{"error": "busy"}` with `Retry-After: 5` | Too many extractions in progress. |

Every other route: a body above 64 KiB gets `413` with `{"error": "request_too_large"}`.

Every response sent before the whole body is read (400, 408, 411, 413, 415, 503) carries `Connection: close`. A `Content-Length` with more than 18 digits counts as too large (413), never as an error. CORS exposes `Retry-After` (`Access-Control-Expose-Headers`), because production is cross-origin.

### Detection rules (`detect_kind`)

1. `%PDF-` at offset 0 → `pdf`.
2. OLE2 signature `D0 CF 11 E0 A1 B1 1A E1` at offset 0 → `legacy_office_unsupported`.
3. `PK\x03\x04` at offset 0 → ZIP checks, in this order. Any failure → `archive_rejected`.
   1. Find the end-of-central-directory (EOCD) record by scanning back over at most the last 65,557 bytes. Its comment must end exactly at the end of the file, and the comment must not contain `PK\x05\x06`, `PK\x06\x06` or `PK\x06\x07` (so the chosen EOCD is the one Python `zipfile` chooses). One disk only. ZIP64 (a ZIP64 locator, or `0xFFFF` / `0xFFFFFFFF` in EOCD fields) is rejected.
   2. Check the entry count from the EOCD against the cap **before** any per-entry work. The central directory must end exactly at the EOCD (`cd_offset + cd_size == eocd_offset`, no gap): `zipfile` locates it as `eocd_offset - cd_size` and ignores `cd_offset`. The number of entries parsed must equal the EOCD entry count.
   3. Every central-directory entry: valid signature; not encrypted (flag bit 0 clear); method 0 (stored) or 8 (deflate); name 1–512 bytes of printable ASCII (0x20–0x7E; OPC part names are ASCII), no backslash, not absolute (no leading `/`, no drive letter `C:`), no `..` or `.` segment, no empty segment (a trailing `/` only for a directory entry of size 0), no segment ending in `.`; the sum of declared uncompressed sizes within the cap; compressed size 0 only when the uncompressed size is 0; uncompressed / compressed ≤ the ratio cap.
   4. No two names that are equal after `casefold()` (OPC part names are case-insensitive; duplicates let different readers see different parts).
   5. Classification by names only: any `Index/*.iwa` → `pages_unsupported`; `[Content_Types].xml` and `_rels/.rels` present and no name under `xl/` or `ppt/` → `docx`; any other ZIP (ODF `mimetype` included) → `unsupported_type`. Stage 3 confirms the main part through relationships (ADR 0009 Layer 0).
   6. Nothing is decompressed in stage 2. `zipfile` may be used only after steps 1 and 2, or not at all.
4. PNG, JPEG, GIF, TIFF, RIFF (WebP) or `{\rtf` signatures → `unsupported_type`.
5. Plain text: a UTF-16 BOM (`FF FE`, `FE FF`) with an even total length → `text` (odd length → `unsupported_type`). Otherwise (a UTF-8 BOM is skipped first), in the first 64 KiB: any NUL byte → `unsupported_type`; more than 1 % C0 control characters other than TAB, LF, CR and FF → `unsupported_type`; else → `text`. This only classifies the file: stage 3 decodes the whole file strictly (UTF-8, UTF-16, CP1251) and runs the control-character rule again on all of the text, failing closed.

Detection is a pure function on bytes in memory. It reads only fixed-size headers and a capped central directory, so its work is linear and bounded; it runs in-process. Stage 3 runs extraction in the parsing subprocess.

### S2-T1 Extract endpoint: upload, limits and type detection

- Status: **merged** (PR #15).
- Owner: `backend-dev`. Tests first: `test-engineer`. Branch: `feat/s2-extract-api` (worktree `/home/claude/wt/s2-extract-api`).
- Public interface (contract between `test-engineer` and `backend-dev`):
  - `app/extraction/detect.py`: `class FileKind(StrEnum)` with `PDF = "pdf"`, `DOCX = "docx"`, `TEXT = "text"`; `class DetectionError(Exception)` with a `code: str` attribute (one of the `422` codes above, never content); `def detect_kind(data: bytes, *, limits: ZipLimits) -> FileKind`; `@dataclass(frozen=True) class ZipLimits` with `max_entries`, `max_uncompressed_bytes`, `max_ratio`.
  - `app/api/extract.py`: router with `POST /api/extract`.
  - `app/extraction/limiter.py`: `class ExtractionLimiter` with `try_acquire() -> bool` and `release() -> None`; the app keeps one instance in `app.state.extraction_limiter`. Tests may take all slots to force `busy`.
  - `app/middleware/body_limit.py`: `BodySizeLimitMiddleware` (pure ASGI).
  - Settings (environment variables, positive integers, validated): `MAX_FILE_BYTES` (10485760), `MAX_JSON_BODY_BYTES` (65536), `MAX_CONCURRENT_EXTRACTIONS` (2), `MAX_ZIP_ENTRIES` (2000), `MAX_ZIP_UNCOMPRESSED_BYTES` (104857600), `MAX_ZIP_RATIO` (200), `EXTRACT_BODY_TIMEOUT_SECONDS` (60), `EXTRACT_MIN_RATE_BYTES_PER_SECOND` (32768; checked after a 5 s grace period).
  - `ExtractionLimiter` also offers a context manager `slot()` (or an equivalent token) that releases exactly once; the handler uses it. `release()` without a held slot raises.
- AC:
  1. `POST /api/extract` follows the API contract table exactly: status codes, JSON bodies, `Retry-After`.
  2. Detection follows the detection rules. Tests build every fixture in memory: a minimal valid DOCX (built with `zipfile`), XLSX-like and PPTX-like archives, an ODF archive, a Pages-like archive, an encrypted entry, ZIP64 markers, trailing data after the EOCD, an entry count above the cap, a declared size above the cap, a ratio above the cap, compressed size 0 with uncompressed size above 0, duplicate names (exact and case-folded), absolute names, `..` names, backslash names, a central directory outside the file, PDF, OLE2, PNG, JPEG, RTF, UTF-8 text, UTF-8 with BOM, UTF-16 LE and BE with BOM, CP1251 bytes (→ `text`), binary with NUL, text with many control characters.
  3. Robustness: random byte strings up to 64 KiB (seeded, at least 2,000 cases) and every truncation of a small valid DOCX either return a `FileKind` or raise `DetectionError`; nothing else is raised. The worst case at the caps (2,000 entries in a 10 MiB file) finishes in under 0.5 s.
  4. Body reading: the handler checks `Content-Length` before it reads; it then reads `request.stream()` into memory and counts bytes; above the limit it stops reading and answers `413`. The limiter slot is taken (without waiting) before the body is read and is released in `finally`, also on errors and on client disconnect.
  5. `BodySizeLimitMiddleware` sits between CORS and the error catcher. It rejects by `Content-Length` before the body is read, and by counting `http.request` chunks. Limits: `MAX_FILE_BYTES` for `/api/extract`, `MAX_JSON_BODY_BYTES` for every other path. A `413` to an allowed origin carries the CORS headers (test).
  6. Never on disk: policy tests fail if `app/` uses `UploadFile`, `request.form`, `tempfile` or `SpooledTemporaryFile`, or if `uv.lock` contains `python-multipart`.
  7. Privacy and logs: a request whose body contains a canary and that carries `Content-Disposition: attachment; filename="<canary>"` and `X-File-Name: <canary>` leaves no canary in captured logs (all loggers, `DEBUG`) or in the response. The access log line stays method, path, status, duration. Error responses carry codes only; `DetectionError` messages never contain input bytes.
  8. CORS: a preflight for `POST /api/extract` with `Content-Type` from an allowed origin succeeds; the allowed headers stay `Content-Type` and `X-Provider-Key`.
  9. CI: the Compose smoke test also sends a small text body through the frontend proxy (`http://localhost:5173/api/extract`) and expects `"kind":"text"`.
  10. ruff, ruff format, mypy strict and pytest are green. No new runtime or dev dependency.
- Review round 1 (PR #15) added to the AC: body deadline and minimum rate (408); `Connection: close` on early responses; `Transfer-Encoding` → 411; `received == Content-Length` (else 400); huge `Content-Length` → 413; `Retry-After` exposed by CORS; body accumulated in one `bytearray` (peak memory for 1-byte chunks below 2.5× the body); ZIP read the same way as `zipfile` (fixtures with a second central directory and with a fake EOCD in the comment are rejected; for valid archives `zipfile` sees the same names); stricter entry names; BOM rules; the handler's own 413 paths tested without the middleware; one `http.response.start` per response; `EXTRACT_PATH` and `declared_length` in a shared module (`app/http_limits.py`); the backend runs as a single worker (the limiter counts per process): policy test that the Dockerfile `CMD` has no `--workers`.
- Threats: T3, T4, T6, T11.

### S2-T2 Upload form in the browser

- Status: **merged** (PR #16).
- Owner: `frontend-dev`. Tests first: `test-engineer`. Branch: `feat/s2-upload-ui` (worktree `/home/claude/wt/s2-upload-ui`).
- Public interface:
  - `src/api/extract.ts`: `type FileKind = "pdf" | "docx" | "text"`; `type ExtractErrorCode` = every server code above plus `"request_too_large" | "network_error" | "timeout" | "aborted" | "unknown_error"`; `type ExtractResult = { ok: true; kind: FileKind; bytes: number } | { ok: false; code: ExtractErrorCode; retryAfterSeconds?: number }`; `function extractFile(file: Blob, options?: { signal?: AbortSignal; fetchImpl?: typeof fetch; timeoutMs?: number }): Promise<ExtractResult>`. It never throws.
  - `src/upload/limits.ts`: `MAX_FILE_BYTES = 10 * 1024 * 1024`, `MAX_FILES_PER_CONTRACT = 5`, `MAX_CONTRACTS = 5`, `MIN_CONTRACTS = 2`, `MAX_TOTAL_BYTES = 50 * 1024 * 1024`, `MAX_PARALLEL_REQUESTS = 2`.
  - `src/upload/state.ts`: pure reducer `uploadReducer(state, action)` and `initialUploadState` (two empty contracts). Actions: `contractAdded`, `contractRemoved { contractId }`, `filesAdded { contractId, files: { id, name, size }[] }`, `fileRemoved { contractId, fileId }`, `fileChecked { fileId, result: ExtractResult }`. File status: `"queued" | "checking" | "accepted" | "rejected"`; client-side rejection codes: `file_too_large`, `too_many_files`, `total_too_large`, `empty_file`, `pages_unsupported`, `legacy_office_unsupported`. Selectors: `contractLabel(index)` (`"A"`…`"E"`), `canAddContract`, `canRemoveContract`, `readiness(state)` → `{ ready: true; contracts: number } | { ready: false; reason: "contract_without_file" | "checking" }`.
  - `src/upload/UploadForm.tsx`: the form component, rendered in `App` after the intro.
- AC:
  1. Contracts: the form starts with "Contract A" and "Contract B". "Add contract" works up to 5 contracts. "Remove contract" is available only when there are more than 2. Labels follow the position (removing B turns C into B).
  2. Adding files: an "Add files" button per contract opens a file picker (`multiple`, `accept=".pdf,.docx,.txt"`). Dropping files on the contract card also adds them. Keyboard users can add files: the button is a real `<button>` that triggers a visually hidden `<input type="file">`.
  3. Client checks before any request: a file above 10 MiB → `file_too_large`; a sixth file in a contract and beyond → `too_many_files`; a file that would push the total above 50 MiB → `total_too_large`; a 0-byte file → `empty_file`; extension `.pages` → `pages_unsupported`; `.doc` → `legacy_office_unsupported`. Rejected files stay in the list with the reason and a "Remove" button. The server's magic-byte check is still the source of truth for every other file.
  4. Server check: every other file is sent with `extractFile`. At most 2 requests are in flight in the whole form; the rest wait as `queued`. `busy` is retried after `Retry-After` (capped at 10 s), at most 3 attempts in total. Timeout 60 s → `timeout`. Network failure → `network_error`.
  5. Request privacy (test intercepts `fetch`): the body is the `File`/`Blob` itself, never `FormData` or a string; the only request header set is `Content-Type: application/octet-stream`; the URL is exactly `/api/extract` with no query string; the file name appears nowhere in the request.
  6. Response handling: a `200` body must have `kind` in the allowed set and `bytes` equal to the file size, otherwise `unknown_error`. An error body `{"error": <string>}` is mapped through an allowlist of codes; anything else → `unknown_error`. Server text is never shown.
  7. Each file row shows: the file name (plain text), the size in localized units, and the status with an icon and a text label ("Waiting", "Checking…", "PDF", "Word document", "Text file", or the rejection reason). An actionable message per error code ("Save the file as .docx or PDF and try again"; for Pages: "Export to PDF: File → Export To → PDF"). Status changes are announced through one `aria-live="polite"` region.
  8. "Remove" on a file aborts its request and frees its slot; removing a contract aborts all its requests. After a removal, focus moves to the contract's "Add files" button.
  9. Readiness line: "Add at least one file to each contract", "Checking files…" or "Ready to compare: N contracts" (from `readiness()`). There is no "Continue" button in stage 2.
  10. Privacy note under the form: files are checked by our server and not stored; file names stay in the browser.
  11. i18n: every new string in `en`, `uk` and `ru` with the same keys; counts use i18next plural forms (`_one`, `_few`, `_many`, `_other` for `uk` and `ru`). `home.status` says that adding contracts works and comparison comes later.
  12. Accessibility: each contract is a `<section>` with a heading; button names include the contract label ("Add files to Contract A"); status uses icon plus text, never color alone.
  13. No new dependency; no HTML sinks; CSP unchanged (`connect-src 'self'` covers `/api/extract`). lint, typecheck, test, build and format checks are green.
- Review round 1 (PR #16) added to the AC:
  - `extractFile` accepts `400 length_mismatch` and `408 upload_timeout` (PR #15 contract); every server code only together with its status; the response body is read up to 4 KiB (`Content-Length` above it, or more streamed bytes → abort and `unknown_error`); a non-JSON `Content-Type` → `unknown_error`; tests pin `credentials: "omit"`, `redirect: "error"`, `cache: "no-store"` and no `keepalive` / `referrer`.
  - i18n sets `skipOnVariables: true` explicitly; a file name such as `$t(upload.title) {{label}}` appears word for word in the row, the Remove label and the live region. File names are wrapped in `<bdi>`.
  - Readiness: `readiness()` adds the reason `rejected_files` ("Remove the files that were not accepted"); order: `checking` → `rejected_files` → `contract_without_file` → ready.
  - Scheduler in a hook `useCheckScheduler(state, dispatch, check)`; when its effect starts again, `checking` files without a request in flight go back to `queued`; files rejected by the client keep no `File` reference.
  - Focus: after adding a contract, focus moves to the new contract's "Add files" button; after removing a contract, to "Add contract"; a focus target is applied only if the item exists. The queued → checking step is not announced.
  - Live region is cleared on a language change. "Files added" announcement uses plural forms.
  - Sizes round up (`10,485,761` bytes shows as "10.1 MB"); "MB" means 1024² (comment in `limits.ts` and `format.ts`); limits in messages are interpolated from `limits.ts`, never written into the strings.
  - Wording fixes in uk/ru from the code review.
- Threats: T1 (HTML sinks), T3, T6, T11 (file names).

### S2-T3 Docs and threat model for stage 2

- Status: **merged** (this PR).
- Owner: `docs-writer` after S2-T1 and S2-T2 are merged; tech lead checks.
- AC:
  1. Threat model: T4 control 1 shows the limits table above (separate limits for file size, files per contract, contracts per analysis, total size and pages); T10 control 5 says "2 contracts, 30 pages in total"; T6 control 3 names `BodySizeLimitMiddleware` and the extraction limiter; T3 control 1 and T11 control 8 say that uploads are raw bytes with no file name (ADR 0010).
  2. README "How it works" step 1 mentions several files per contract. `CLAUDE.md` Commands section: a `curl` example for `/api/extract` with the expected response.
  3. `PROGRESS.md` updated; stage 2 report sent to the customer.

### S2 follow-ups (from the ADR 0008/0009 design review, for later stages)

- Stage 3 (from the PR #15 security review): before any reader opens a ZIP — every local header at an offset below `cd_offset` with a valid signature, offsets strictly increasing from 0, no overlap and no gap, local name, flags, method, CRC and sizes equal to the central directory (data descriptor handled), real decompressed size enforced while streaming; OPC part-name grammar (ECMA-376 Part 2 §6.2.2: no percent-encoded unreserved characters or `/`) and duplicates checked after canonical decoding; extraction uses only the kind the server detected on the same bytes in the same request.
- Stage 6 / before stage 13 (**release blocker**): at most 1 extraction slot per client IP (T6 control 6 client-IP rule).
- Stage 3: test detection against a corpus of real UK/RU DOCX files (some generators store raw UTF-8 part names, now `archive_rejected`); the `archive_rejected` message tells the user to save the file again in Word or export to PDF.
- Effective upload minimum: a 10 MiB file needs about 1.4 Mbit/s to finish within 60 s; the `upload_timeout` message mentions a slow connection or a smaller file.
- Stage 3: pdfminer xref warnings, long or looping `Prev` chains (`RecursionError` → `pdf_damaged`) and an unreadable latest revision make the incremental-update warning material; local file header names must match the central directory.
- Stage 3 and 5b: tests on clean UK and RU contracts show no mixed-script and no overlap flags (combining marks excluded).
- Stage 10 polish: show limits in messages with the `upload.size.mb` template ("10 MB") and narrow the size test to `.file-row__size` (code review PR #16).
- Stage 8: model tags that push a topic over its cap are dropped; a topic not analyzed shows 🟡.
- Stage 9: global-override markers; "at most one document per call" policy test.

## Stage 3 — Text extraction

Design: ADR 0011 (parsing sandbox), ADR 0009 Layer 0 (read what the person reads), ADR 0004 revision. Threats: T3, T4, T5, T6, T11.

Order: S3-T1 first (sandbox and response contract). Then S3-T2 (DOCX) and S3-T3 (PDF), one after the other (both change `uv.lock`). S3-T4 (preview UI) can start after S3-T1. S3-T5 (browser OCR) after S3-T3. S3-T6 (Google Docs link) last. Detailed AC for S3-T2…T6 are written when each task starts.

### Response contract: `POST /api/extract` `200` from stage 3

```json
{
  "kind": "pdf" | "docx" | "text",
  "bytes": 12345,
  "language": "uk" | "ru" | "en" | "mixed" | "unknown",
  "pages": 3,
  "blocks": [{ "text": "…", "part": "body" | "footnote" | "endnote" | "header" | "footer" | "textbox", "page": 1 }],
  "ocr_pages": [2],
  "removed": [{ "reason": "<code>", "count": 4, "sample": "…" }],
  "warnings": [{ "code": "<code>", "page": 2 }]
}
```

- `pages` and `page` are `null` for DOCX and text. `ocr_pages` lists PDF pages with no text layer that the browser must OCR (stage 3, S3-T5); it is empty for other kinds.
- `removed` lists text that was dropped as provably invisible, by reason, with a short sample (at most 200 characters) for the preview. `warnings` use codes only (plus a page number).
- Every list and the total text have caps; a cap fails closed with an error code, never a truncated result.
- New error codes (`422` unless noted): `extraction_failed`, `extraction_timeout`, `too_many_pages`, `too_much_text`, `encrypted_unsupported`, `no_text_extracted`, `text_decoding_failed`, `suspicious_package`, `docx_strict_unsupported`, `pdf_damaged`.

### S3-T1 Parsing sandbox, response contract and plain text

- Owner: `backend-dev`. Tests first: `test-engineer`. Branch: `feat/s3-sandbox` (worktree `/home/claude/wt/s3-sandbox`).
- Public interface:
  - `app/extraction/sandbox.py`: `async def run_extraction(data: bytes, kind: FileKind, *, limits: SandboxLimits) -> ExtractionResult` (raises `ExtractionError(code)`); `@dataclass(frozen=True) class SandboxLimits` (`memory_bytes`, `cpu_seconds`, `wall_seconds`, `max_result_bytes`).
  - `app/extraction/worker.py`: the child entry point (`python -I -m app.extraction.worker`); `app/extraction/text.py`: `extract_text_file(data: bytes) -> ExtractionResult` (pure, runs inside the child).
  - `app/extraction/model.py`: Pydantic models for the response contract above (`ExtractionResult`, `Block`, `Removed`, `Warning`), strict, `extra="forbid"`.
  - Settings: `EXTRACT_WORKER_MEMORY_MB` (192), `EXTRACT_WORKER_CPU_SECONDS` (20), `EXTRACT_WORKER_WALL_SECONDS` (30), `EXTRACT_MAX_RESULT_BYTES` (8 MiB), `EXTRACT_MAX_TEXT_CHARS` (2,000,000), `EXTRACT_MAX_BLOCKS` (20,000).
- AC:
  1. ADR 0011: one subprocess per file; limits set by the child before it reads input (`RLIMIT_AS`, `RLIMIT_CPU`, `RLIMIT_FSIZE` = 0, `RLIMIT_NOFILE`, `RLIMIT_CORE` = 0); minimal environment; `-I`; stderr read and discarded, never logged.
  2. The parent kills the child on the wall deadline (`extraction_timeout`), on a non-zero exit or a signal (`extraction_failed`; memory or CPU limit included), and on a result above `EXTRACT_MAX_RESULT_BYTES` (`extraction_failed`, reading stops at the cap). No zombie processes remain (test). The extraction slot is held while the child runs.
  3. The child result is validated by the Pydantic model in the parent; invalid JSON or schema → `extraction_failed`.
  4. Plain text: strict UTF-8 (BOM optional), strict UTF-16 with BOM, otherwise strict CP1251; failure → `text_decoding_failed`. The control-character rule of detection runs again on the whole decoded text (fail closed). Newlines normalized to `\n`. Text is split into blocks by blank lines. `part` = `body`.
  5. Language: rule-based, no dependency: Ukrainian-only letters (і, ї, є, ґ) vs Russian-only letters (ы, э, ъ, ё) vs Latin share; `mixed` when two languages are both significant, `unknown` for too little text. Thresholds documented and tested with en/uk/ru samples.
  6. Caps: total characters above `EXTRACT_MAX_TEXT_CHARS` → `too_much_text`; blocks above `EXTRACT_MAX_BLOCKS` → `too_much_text`; zero characters after decoding → `no_text_extracted`.
  7. `POST /api/extract` returns the stage 3 contract for `text`. For `pdf` and `docx` it returns `501 {"error": "not_implemented"}` until S3-T2/S3-T3 (temporary; removed by those tasks).
  8. Robustness tests in the child: a test-only kind or hook that allocates memory beyond the limit, burns CPU, sleeps past the wall deadline, writes huge output, exits non-zero, and tries to write a file → each gives the right code; the server keeps working and the slot is free.
  9. Memory budget measured and written in ADR 0011: parent RSS plus two children at their limit stays under 512 MB.
  10. Logs: only the error code and duration; no child output, no text. Log canary test with a canary inside the text file.
  11. No new dependency. ruff, mypy strict, pytest green.
- Threats: T3, T4, T6.

### S3-T2 DOCX extraction (outline)

ZIP stage 3 checks (local headers equal to the central directory, no overlap or gap, first entry at 0, real decompressed size enforced while streaming, OPC part-name grammar), relationship resolution and package anomalies (ADR 0009 Layer 0), own walker (`defusedxml`) over main part, footnotes, endnotes, headers, footers, text boxes, content controls, tracked insertions, fields, `w:sym`; effective formatting for hidden text; symbol-font checkboxes; material "Not read" warnings (`altChunk`, OLE); strict OOXML rejected.

### S3-T3 PDF extraction (outline)

`pdfminer.six` with a custom device (render mode), provably invisible text dropped and reported, borderline text flagged, overlapping glyphs, page cap, `ocr_pages` for pages without text, encrypted PDFs rejected, xref fallback / parse warnings / long or looping `Prev` chain → `pdf_damaged` or a material warning, incremental updates warning, annotations with values → "Not read".

### S3-T4 Preview in the browser (outline)

Per contract: extracted text as plain text, part labels, removed text (expandable), warnings with icon and text, language; uses the stage 3 contract.

### S3-T5 OCR of scans in the browser (outline)

`tesseract.js` and `pdfjs-dist` self-hosted (worker, wasm, language data from our origin), `ocr_pages` and image-only PDFs, confidence per page, low confidence warning; CSP unchanged or changed with security review.

### S3-T6 Google Docs by public link (outline)

Strict link format, export URL built by the server, allowlisted Google hosts, size limit and timeout; the result goes through the same detection and extraction. Google Picker is out of v1 (it needs third-party scripts, CLAUDE.md rule 8).

