# Tasks

Format: one task per block. Goal, owner, branch, acceptance criteria (AC), threats touched (see `docs/security/threat-model.md`).
Check a task only when it is merged to `main` with green CI.

Finished stages 0 to 5: `docs/agent/TASKS-archive.md`.

Next: stage 5b — see below.

## Stage 5b — Pseudonymization

Design: ADR 0008 (what is masked, pipeline, type gate, tests) and ADR 0015 (interfaces for this stage). Threats: T3, T5, T11. Every task here is security-critical: `security-reviewer` reviews every PR.

Order: S5b-T0 (corpus) first, in parallel with the S5b-T1 tests; S5b-T1 (detector in `/api/segment`); then S5b-T2 (safety check and type gate, backend) and S5b-T3 (preview and masking, frontend) in parallel; S5b-T4 (canary harness and eval) after T1–T3; S5b-T5 docs last.

### S5b-T0 Identifier corpus

- Owner: `domain-analyst`. Branch: `feat/s5b-detect` (corpus only, `backend/tests/fixtures/pseudo/`).
- Synthetic contracts (fictional values only; checksummed codes and IBANs must be **valid by checksum** but fictional) in UK, RU and EN, as `/api/segment` input blocks, each with the expected entities: class, `precision`, every span (block, start, end) of every occurrence, grouping of forms of the same value into one entity, requisites line decisions (`drop`/`keep`) and expected warnings. Cover every class of ADR 0008 point 1 and every location of ADR 0008 point 6 that exists as text (preamble, body, headings, footnotes, running headers, requisites, text boxes); UK/RU case forms, initials both orders, transliteration, female forms, non-declining surnames, double surnames, common-word surnames (Коваль, Мельник, Rose); ФОП (ORG and PERSON); quoted product names; defined terms equal to a masked name; obfuscated emails; IBAN with and without spaces; numbers that pass a checksum but are amounts (`12 345 678,00 грн`, `25 %`, `30 днів`) and must **not** be masked; a requisites section with identifier-only lines and one obligation line; placeholder look-alikes; zero-width-split, hyphen-split and homoglyph variants (after Layer 1 cleaning, homoglyphs remain). Also **negative controls**: role words (Страховик, Орендар, Buyer), city-level territory, dates of obligations, amounts. At least 25 files. `README.md` lists them.

### S5b-T1 Detector in `/api/segment` (backend)

- Owner: `backend-dev`. Tests first: `test-engineer`. Branch: `feat/s5b-detect` (worktree `/home/claude/wt/s5b-detect`).
- Threats: T5, T6, T11.

1. `app/pseudo/` per ADR 0015 point 2: preamble definitions and later occurrences (stem matching for UK/RU cases), legal forms + quoted names, "в особі / в лице / represented by", signature lines, format rules with checksums (ЄДРПОУ, РНОКПП, IBAN, Luhn) **only with a context keyword within 5 tokens or inside the requisites section**; amounts (currency, `%`, units, thousand separators, decimals) never match a code rule; a checksum match without context is a `normal` proposal; emails (incl. `(at)`/`[at]`), phones (UA/RU/intl formats), URLs and bare domains, VIN, UA/RU plates, passport/ID formats with context, document numbers after `№`/`No.` with a document word, cadastral numbers, addresses after address keywords up to the end of the line or sentence.
2. Matching view: de-hyphenated (line-end hyphens), NFKC + generated confusable skeleton (Latin/Cyrillic/Greek/digits; checked-in table, generator with `--check`, like Layer 1), with an exact offset map back to the cleaned blocks; masks always point to cleaned-block offsets.
3. Reply fields exactly as ADR 0015 point 1 (`detector_version`, `entities` with grouped spans and no value strings, `requisites`, `neutralized`, new clause warnings). Headings are detected like other text (they are inside clause spans). Running clauses too.
4. Requisites section (clauses with `section_kind: "requisites"`): line by line; drop only lines made entirely of identifiers, their labels, role words and signature lines; keep any line with an obligation marker (UK/RU/EN list in a checked-in table) or with more than 3 non-identifier, non-label tokens; kept → clause warning `requisites_condition`.
5. Caps: 5,000 entities and 50,000 spans per file → `422 too_many_identifiers`; the result-size test at the caps is extended with entities.
6. Linear time: patterns per line with `match` at token starts, no nested quantifiers (existing policy test extended to `app/pseudo/`); adversarial tests at the caps within the CPU limit.
7. Logging: counts only (entities per class), never values. Log canary extended: an identifier canary never in logs.
8. Corpus: every S5b-T0 fixture gives exactly the expected entities (class, precision, spans, grouping), requisites decisions and warnings; negative controls give no entity.

### S5b-T2 Safety check and type gate (backend)

- Owner: `backend-dev`. Tests first: `test-engineer`. Branch: `feat/s5b-safety` (worktree `/home/claude/wt/s5b-safety`). After S5b-T1 is merged.
- Threats: T5, T11.

1. `app/pseudo/gate.py`: gate types per ADR 0015 point 5 (frozen, slots, sentinel); `safety_pass(untrusted: UntrustedMaskedDocument) -> PseudonymizedDocument` raising `SafetyError(code, spans)`.
2. `POST /api/safety-check` per ADR 0015 point 4: same transport rules as `/api/segment` (JSON, per-path body limit 4 MiB, slot before read, deadline and minimum rate, sandbox child, strict parsing). Checks in order: `409 detector_version_mismatch`; `422 input_not_clean` (Layer 1 would change the text); `422 invalid_placeholder` (any bracket token that looks like a placeholder but is not `[<label>.<CLASS>_<n>]` with this document's label and a known class); `422 unmasked_identifier` with clause-relative spans only (high-precision rules re-run on the masked text, placeholders skipped); `200 {"ok": true, "detector_version", "digest"}`. Error bodies never contain text.
3. AST policy test (ADR 0008 point 3): outside `app/pseudo/gate.py`, no constructor call, `cast`, `__new__`, `object.__setattr__` or sentinel use for gate types; no gate type in any Pydantic request model; a future `AIProvider` port module may import only gate types, enums and constants (test written now against a placeholder module list, extended in stage 6).
4. Tests for every check, for clause-relative span correctness, and that a masked document whose placeholders hide a high-precision value passes.

### S5b-T3 Preview and masking (frontend)

- Owner: `frontend-dev`. Tests first: `test-engineer`. Branch: `feat/s5b-preview` (worktree `/home/claude/wt/s5b-preview`). After S5b-T1 is merged; the safety-check call is wired when S5b-T2 is merged (mock until then).
- Threats: T3, T11.

1. Contract labels A, B, C… follow contract order in the form; file names never leave the browser and never appear in masked text.
2. Mandatory "Check replacements" step per contract after every row has clauses: the clause list with each entity highlighted (plain text, class label, placeholder preview), requisites lines that will be dropped shown struck through, kept requisites lines and other warnings shown; `high` entities cannot be unmasked (control disabled with an explanation); `normal` entities can be unmasked (all occurrences of that entity, or one occurrence); the client can select text inside a clause and mask it with a class (all equal occurrences in that document are offered).
3. Placeholders assigned in the browser in first-occurrence order per document and class (`[A.ORG_1]`); masked clauses built from cleaned blocks and spans; the mapping lives only in memory, dropped with the contract (ADR 0013 point 9a); never in storage, URL, console, announcements or any request.
4. "Everything is correct" calls `/api/safety-check` per contract; on `unmasked_identifier` the returned spans are pre-masked, highlighted and the client must confirm again; on `detector_version_mismatch` the contract is re-segmented and the review starts again; other errors shown with their own messages. A contract is "ready for analysis" only after `ok`; any later edit resets it.
5. Tests: highlight rendering, unmask rules, manual masking, placeholder numbering, masked text equals the expected text, the mapping and original values never in any `fetch` body (intercept all requests), the safety-check flow for every code, readiness reset, en/uk/ru.

### S5b-T4 Canary harness and detector eval

- Owner: `test-engineer` (harness) and `ai-eval-engineer` (eval). Branch: `feat/s5b-canary`. After S5b-T1–T3 are merged.
- Threats: T11.

1. Harness per ADR 0015 point 6 (every class × location × input path: PDF, DOCX, TXT, OCR-like blocks, Google export DOCX; text outside content: file name, DOCX `docProps`, PDF Info/XMP never reach blocks); the browser-equivalent masking in Python uses the same placeholder rules as S5b-T3 (shared JSON test vectors used by both Vitest and pytest).
2. Eval per ADR 0015 point 7 with a report script; gates enforced in CI; numbers recorded in the PR and in `docs/agent/PROGRESS.md`.

### S5b-T5 Docs for stage 5b

- Owner: `docs-writer`. After S5b-T1–T4 are merged.
- ADR 0015 → accepted; threat model T11 (controls as implemented, eval numbers, residual risk), T5 (placeholder look-alikes), T6 (`/api/safety-check` in the per-IP slot blocker); `CLAUDE.md` Commands (`/api/segment` example with entities, `/api/safety-check`); README ("names are replaced before any AI call; you check every replacement").

## Open follow-ups

### Stage 11 follow-ups (from stage 5)

- Stage 11: eval case — harmful sentence repeated on every page (ADR 0014 point 5).

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
