# Tasks

Format: one task per block. Goal, owner, branch, acceptance criteria (AC), threats touched (see `docs/security/threat-model.md`).
Check a task only when it is merged to `main` with green CI.

Finished stages 0 to 3: `docs/agent/TASKS-archive.md`.

Next: stage 4 — see below.

## Stage 4 — Browser hash and cache

Design: ADR 0013 (browser cache and history), ADR 0001, ADR 0008 point 4. Threats: T3, T9, T11. Customer decision (2026-10-22): history is **off** by default.

Order: S4-T1 and S4-T2 in parallel (different modules; resolve conflicts in the locale files at merge). S4-T3 docs last. New development dependency for S4-T2 tests: `fake-indexeddb` (needs `security-reviewer` approval before `test-engineer` starts S4-T2).

### S4-T1 Hashes and duplicate detection

- Owner: `frontend-dev`. Tests first: `test-engineer`. Branch: `feat/s4-hash` (worktree `/home/claude/wt/s4-hash`).
- Threats: T3 (control 7), T11.

1. `src/hash/sha256.ts`: `sha256Hex(data: ArrayBuffer | Uint8Array | string): Promise<string>` through `crypto.subtle.digest("SHA-256", …)`; strings are UTF-8 encoded; result is 64 lower-case hex characters. No fallback implementation: if `crypto.subtle` is missing, it throws `HashUnavailableError` (the page needs a secure context anyway).
2. `src/hash/normalize.ts`: `normalizeForHash(text: string): string` exactly as ADR 0013 point 8 (NFC; CRLF and CR → LF; tabs and runs of spaces → one space; spaces at line ends removed; three or more line breaks → two; trim). Tests: a table of inputs, idempotence (`f(f(x)) === f(x)`), NFD vs NFC input gives the same hash, Cyrillic and Latin look-alikes give different hashes.
3. `src/hash/key.ts`: `canonicalJson(value)` (sorted object keys at every level, no spaces, arrays keep order, only strings, finite numbers, booleans, `null`, arrays and plain objects; anything else throws) and `buildKey(parts: Record<string, KeyPart>): Promise<CacheKey>` = `sha256Hex(canonicalJson({ v: 1, ...parts }))`. `CacheKey` is a branded string type. Tests: key order does not change the key; array order does; `undefined`, `NaN`, functions, `Date` throw.
4. **File hash before upload.** When a file is added, the browser hashes its bytes. The same bytes already in the same contract (any status except `rejected`) → the new row is refused as `duplicate_file` with no request to the server. The same bytes in another contract → the row is accepted and shows a warning "The same file is in Contract X" (i18n, all three languages).
5. **Text hash after extraction.** When a row becomes `accepted` (upload, OCR finished, or Google Docs), the browser hashes `normalizeForHash` of its text blocks joined with `\n\n` in order. A row with the same text hash as another accepted row in the same contract → a warning "Same text as another file in this contract"; in another contract → "Same text as a file in Contract X". Warnings only; nothing is refused after extraction. A Google Docs row with the same text as an uploaded file is detected this way.
6. `contractTextHash(contract)`: hash of the canonical JSON of the ordered text hashes of the accepted rows; `null` while any row is `queued` or `checking`. Exported for stage 9; tested now.
7. Hashes live only in memory (reducer state or component state), next to the extracted text, and are dropped with the row. Never in `localStorage`, `sessionStorage`, IndexedDB, the URL, the console or announcements. A test spies on the storage APIs.
8. Hashing a 10 MiB file must not block the UI thread for long: hash with `crypto.subtle` (asynchronous); the row stays `queued` until the hash is done; removing the row while hashing drops the result.

### S4-T2 `CacheStore`, history setting and clear all

- Owner: `frontend-dev`. Tests first: `test-engineer`. Branch: `feat/s4-cache` (worktree `/home/claude/wt/s4-cache`).
- Threats: T3 (controls 6, 7), T9 (CSP unchanged), T11 (mapping stored only with history on).

1. **Port** `src/storage/cacheStore.ts` (ADR 0013 points 3–6):
   ```ts
   interface CacheStore {
     get<T>(key: CacheKey, validate: (data: unknown) => data is T): Promise<CacheHit<T> | null>;
     put(key: CacheKey, kind: CacheKind, data: unknown): Promise<PutResult>; // "stored" | "disabled" | "too_large" | "storage_full" | "failed"
     list(): Promise<CacheEntryMeta[]>; // key, kind, createdAt, lastUsedAt, size; newest first
     delete(key: CacheKey): Promise<void>;
     clear(): Promise<void>;
     purgeExpired(): Promise<number>;
   }
   ```
   `CacheKind` is `"analysis"` for now. `get` updates `lastUsedAt` on a hit. Time comes from an injectable clock.
2. **Adapters:** `IndexedDbCacheStore` (own wrapper, no `idb`; database `aic-cache` version 1, store `entries`, key path `key`, index `lastUsedAt`; `onversionchange` closes the connection; every write is one transaction), `MemoryCacheStore`, `DisabledCacheStore`. One contract test suite runs against all three (the disabled store has its own expectations).
3. **Validation on read:** unknown `schema` or `kind`, `createdAt` or `lastUsedAt` not a finite number or in the future by more than one day, `size` mismatch, or the caller's validator returns false → the entry is deleted and `get` returns `null`.
4. **Retention:** 90 days from `createdAt`. `purgeExpired` runs at start-up and inside `get` and `list`. An entry exactly 90 days old is expired.
5. **Caps (fail closed):** at most 2 MiB per entry (UTF-8 length of `JSON.stringify(data)`) → `too_large`, nothing written; `JSON.stringify` failure → `failed`; after a successful put, if there are more than 100 entries, delete the least recently used until 100 remain. `QuotaExceededError` or any transaction error → the transaction is aborted, nothing partial stays, result `storage_full` or `failed`.
6. **History setting** `src/storage/historySetting.ts`: `isHistoryEnabled()` reads `localStorage["aic.history"] === "on"` (any read error → off); `setHistoryEnabled(true)` writes `"on"`; `setHistoryEnabled(false)` removes the key and clears the store. `createCacheStore()` returns `DisabledCacheStore` when history is off or IndexedDB cannot be opened (open error, `null` `indexedDB`, security error), else `IndexedDbCacheStore`.
7. **Clear all** `clearAllData()`: deletes the `aic-cache` database (`indexedDB.deleteDatabase`) and every `localStorage` key that starts with `aic.` except `aic.lang`. Result `"cleared" | "blocked" | "failed"`; `blocked` when the deletion is blocked by another open connection.
8. **Settings panel** (`src/settings/`), reachable from the page header ("Data and history"), i18n `en`, `uk`, `ru`:
   - toggle "Save results in this browser" (default off, `role="switch"` with `aria-checked`), one-sentence explanation: results with contract quotes and real names are kept in this browser for 90 days, not encrypted; do not turn on on a shared computer;
   - turning it off when entries exist asks for confirmation ("Saved results will be deleted"); cancel keeps it on;
   - status line: number of saved results (from `list()`), or "History is not available in this browser" with the toggle disabled when IndexedDB is not available;
   - button "Delete all data in this browser" with a confirmation; on `blocked` the message asks to close other tabs of the app; after success the toggle shows off and the count is 0.
9. **"Already analyzed" dialog** `src/settings/CachedResultDialog.tsx` (used by stage 10; shipped and tested now with a fixture): shows the date of the saved result (formatted for the UI language) and two buttons, "Show saved result" and "Run a new analysis". `role="dialog"`, `aria-modal="true"`, labelled by its heading; focus moves to the first button; focus stays inside the dialog; Escape closes it with a third outcome `"cancel"`; focus returns to the element that opened it. Props: `savedAt`, `onChoice(choice: "cached" | "new" | "cancel")`.
10. Nothing in this task writes contract text, file bytes or extracted text to any storage (T3 control 7). CSP unchanged.
11. Tests (Vitest, `fake-indexeddb` for the IndexedDB adapter; inject a fresh `IDBFactory` per test): contract suite on all adapters, retention boundary, LRU eviction at 101 entries, 2 MiB boundary (exactly 2 MiB stored, one byte more refused), quota error leaves no entry, corrupt entry deleted, history off writes nothing (spy on `indexedDB.open`), clear all with a blocked deletion, settings panel behaviour, dialog keyboard behaviour.

### S4-T3 Docs for stage 4

- Owner: `docs-writer`. After S4-T1 and S4-T2 are merged.
- Threat model: T3 control 6 (history off by default, delete on turn-off, caps, retention, no encryption — residual risk), T11 (mapping stored only with history on). ADR 0013 status → accepted. `CLAUDE.md` architecture row unchanged unless the design changed. README: "Data and history" in "How it works".

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

### Stage 13 blockers and follow-ups (from stage 3)

- Stage 13 blockers: header-read timeout / slowloris with `--limit-concurrency 32`, and kernel send buffers of cut-off connections (threat model T6 control 9).
- Measure the 100-page PDF worst case on Render's CPU (9.3 s CPU here); lower `MAX_PDF_PAGES` or raise the wall limit if it exceeds 30 s.
