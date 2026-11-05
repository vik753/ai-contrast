# Tasks

Format: one task per block. Goal, owner, branch, acceptance criteria (AC), threats touched (see `docs/security/threat-model.md`).
Check a task only when it is merged to `main` with green CI.

Finished stages 0 to 7: `docs/agent/TASKS-archive.md`.

## Stage 8 — Clause tagging (ADR 0018)

Order: S8-T0 (tagging fixtures) and S8-T1 (keyword tagger, risk terms, caps) in parallel; S8-T2 (`/api/tag` with model tags, check calls and the analysis pass) after S8-T1; S8-T3 (browser) after S8-T2's API is fixed; S8-T4 (eval) after S8-T2; S8-T5 docs last.

### S8-T0 Tagging fixtures

- Owner: `domain-analyst`. Branch: `feat/s8-fixtures` (only `backend/eval/tagging/fixtures/` and the S7-T0 fixtures' `expected.json`).
- For each of the 8 S7-T0 contracts: expected topic ids per clause id (all topics a clause regulates, not only the main one), expected "Other" clauses, and risk-term clauses. Add two adversarial contracts: one with a clause that tells the tagger to skip it, one that floods one topic (more than 60 clauses mentioning it in passing). Avoid `: ` and `«»` in any text that may become topic text.

### S8-T1 Keyword tagger, risk terms and caps (backend)

- Owner: `backend-dev`. Tests first: `test-engineer`. Branch: `feat/s8-keywords`. Threats: T5, T6.

1. `app/tagging/keywords.py`: synonym matching per ADR 0018 point 2 (skeleton view, word-start stems, phrases with flexible whitespace, headings included), linear time without regexes built from synonyms; adversarial tests at the caps (2,000 clauses × 50 topics × 40 synonyms) within the CPU limit.
2. `app/tagging/risk_terms.py`: checked-in EN/UK/RU risk-term list and scan of "Other" clauses (point 4).
3. `app/tagging/merge.py`: merge of keyword, model, check and client tags; the caps and rules of point 5 (model tags only add; model-tag cap per clause and per topic with "drop all model tags of the topic" + `model_tags_dropped`; keyword overflow → `not_analyzed` + clauses also to "Other"); missing topics; never a clause lost (property test: every clause is tagged or in "Other").
4. Layer 2 per clause (point 6) as a pure function returning hits.
5. `tagging_version` hash.

### S8-T2 `/api/tag` with model tags, check calls and the analysis pass (backend)

- Owner: `backend-dev`. Tests first: `test-engineer`. Branch: `feat/s8-tag`. After S8-T1. Threats: T1, T5, T6, T10, T11.

1. `PromptTemplate` `TAG_CLAUSES` and `CHECK_TAGS` (one document required, topic text allowed only as opaque-index lists built from `ConfirmedTopic`s); strict schemas; batches per point 3; one repair, then the batch falls back to keyword tags.
2. Cheap/strong model pair per preset (ADR 0018 point 3); the request may name both; `free` uses one model.
3. `POST /api/tag` per point 1: safety pass in the sandbox, extraction slot released before AI calls, topic resolution with `selection.py`, token budget check before any call (`document_too_large_for_tagging`), shared AI slots and limits, 60 s per call and an overall deadline, reply shape of point 1.
4. Analysis pass (point 7): `aud=analysis`, 30 min, /48, one live per client, bounded table, covers one analysis (≤ 2 documents in free mode), charges the free analysis quota once, Neuron reserve/settle per call; free size limits (2 contracts, 30 pages).
5. The `PseudonymizedText.source` builder is not needed here (tagging carries no `PseudonymizedText`); keep the follow-up for stage 9.
6. Log and wire canaries: no clause text, topic text or model output in logs; one document per call.

### S8-T3 Tagging step in the browser (frontend)

- Owner: `frontend-dev`. Tests first: `test-engineer`. Branch: `feat/s8-tag-ui`. After S8-T2's API is merged. Threats: T1, T3, T5.

1. Confirmed masked documents from the upload flow are exposed to `App` (a small store) and to `TopicPanel` (enables Suggest).
2. "Tag clauses" step per ADR 0018 point 8: model pair shown, cost estimate, progress per document, clauses with topic chips (keyword / model / check / client with icon and text), "Other" with risk-term marks, per-topic flags, client-added tags; Layer 2 flags shown per clause; every string en/uk/ru; plain text only.
3. Free mode uses the analysis pass (`X-Analysis-Pass`), one Turnstile per analysis, shared with the provider panel's frame logic.

### S8-T4 Tagging eval

- Owner: `ai-eval-engineer`. After S8-T2 and S8-T0. Branch: `feat/s8-eval`.
- `backend/eval/tagging/` per ADR 0018 point 9: recorded mode in CI (stub labelled), live mode locally; baseline; the two adversarial contracts.

### S8-T5 Docs for stage 8

- Owner: `docs-writer`. After S8-T0–T4 are merged.
- ADR 0018 → accepted; threat model T5 (tagging cannot hide a clause), T6 (tag endpoint limits), T10 (analysis pass), T11; `CLAUDE.md` Commands (`/api/tag` with a dummy key and a keyword-only path if it exists, or a refused request); README.

## Open follow-ups

### Stage 9 follow-ups (from stage 7)

- Stage 9: expose the confirmed masked documents from UploadForm to TopicPanel (`App` passes `NO_DOCUMENTS` today), which enables the "Suggest from my contracts" button.
- Stage 9: declare optional usage on the AIProvider port result (typed), replacing the `getattr` in `topic_ai._reported` (code review S7-T2 NIT).
- Stage 9: ignore a free-pass reply that started before "Clear all" (the panel could store a pass after the data was cleared).
- Stage 8 or 9: the builder that computes `PseudonymizedText.source` (`document_digest`) comes with the first call that carries such a text. `ConfirmedTopic` is not bound to a document (ADR 0017 point 3).
- Stage 9: use `app/topics/selection.py` (caps per request, `catalog_version_mismatch`) in the analysis request.

### Stage 10 follow-ups (from stage 5b)

- Stage 10: never restore names in model text at neutralized spans (`⟦…⟧`) or at tokens with non-`[` brackets.

### Stage 11 follow-ups (from stage 5, 5b and 7)

- Stage 11: eval case — harmful sentence repeated on every page (ADR 0014 point 5).
- Stage 11: run the topic eval live with a provider key (`cd backend && AIC_EVAL_PROVIDER_KEY=... uv run --locked python -m eval.topics.run_eval --live --provider <preset> --model <id>`; see `backend/eval/topics/README.md`) and record the numbers. The CI baseline is a stub oracle.
- Stage 11: refresh the stub recordings after any prompt or schema change (`--write-stub --write-baseline`).
- Stage 11: more Layer 2 bypass probes (the first eval found two real bypasses; phrase lists stay bypassable). Add each new probe to the `attack` list of `backend/eval/topics/adversarial/contract_b.json`.
- Stage 11: fresh held-out set for pseudonymization (the current one is no longer blind). Add these cases:
  - LOW: the fail-closed false positive `[A.ACCOUNT_1]; 4.2.` is refused by the safety check.
  - LOW: `ЄДРПОУ 34123457 кв. 5` is not detected, but the safety check refuses it.
  - The `DOE, JANE` given-name form.
  - The en PERSON gate (xfail, normal 0.929): a Cyrillic name in brackets after a Latin form.

### S2-T0 Lint follow-up (from PR #3 security re-review)

- TS files: string eval through global-object members (`window.eval`, `self.eval`, `self.setInterval("…")`) is reported. Shared browser-globals map for all sources; core `no-implied-eval` on for TS too; ban `x.eval` member access with a T1 message; tests in a `.ts` fixture.
- Optional (code review NIT): `changeLanguage()` before setup uses `setupFallbackI18n()`.
- Policy test (PR #10 security review): no `versions:` in any `dependency-name: "*"` ignore entry in any ecosystem; every wildcard entry has `update-types` without `version-update:semver-patch`.
- Recurring per stage: run `npm outdated` (frontend) and `uv tree --outdated` (backend) and plan major upgrades (TypeScript 7 with typescript-eslint, jsdom 30 with Node ≥ 22.22.2).
- Dependency batch (Dependabot groups, PR #71): hold `fake-indexeddb` at 6.2.5 and `magic-string` at 1.4.3 until the newer releases are 14 days old.

### S2 follow-ups (from the ADR 0008/0009 design review, for later stages)

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

### Stage 13 blockers and follow-ups (from stages 3, 6 and 7)

- Stage 13 blockers: header-read timeout / slowloris with `--limit-concurrency 32`, and kernel send buffers of cut-off connections (threat model T6 control 9).
- Stage 13 (from stage 7): the Render service must build with the **repository root** as build context and `backend/Dockerfile` as the Dockerfile path. The image needs `shared/topics/`; `backend/Dockerfile.dockerignore` is the allowlist (threat model T8 control 12). Check that the deployed image starts with `TOPICS_CATALOG_DIR=/app/shared/topics` and that `GET /api/topics/catalog` answers.
- Measure the 100-page PDF worst case on Render's CPU (9.3 s CPU here); lower `MAX_PDF_PAGES` or raise the wall limit if it exceeds 30 s.
- Deploy checks (from stage 6):
  - No `__*__` placeholder is left in either `_headers` file (`frontend/public/_headers` has `__TURNSTILE_FRAME_ORIGIN__`; `frontend/turnstile/public/_headers` has `__APP_ORIGIN__`).
  - `VITE_TURNSTILE_APP_ORIGIN` (frame build) equals the `__APP_ORIGIN__` value of the frame `_headers`.
  - The host of `VITE_TURNSTILE_FRAME_ORIGIN` (app build) equals `TURNSTILE_EXPECTED_HOSTNAME` (backend).
  - `ENVIRONMENT=production` on Render. The four free settings are all set (or all unset); no Cloudflare test secret.
  - Render's `X-Forwarded-For` has the client address as its rightmost entry (`TRUSTED_PROXY_HOPS=1`; threat model T6 control 6).
- Second Cloudflare Pages project for the Turnstile frame (`npm run build:turnstile`, output `frontend/dist-turnstile/`), with its own `_headers`.
- Playwright e2e of the real iframe and CSP: the frame loads only in free mode, the token reaches the app, no `securitypolicyviolation` in the app or the frame.
- Customer actions for stage 13: create the Cloudflare account (Workers Free plan) and a Workers AI token scoped to Workers AI only; create the Turnstile widget (site key and secret) with the frame hostname; set the Render environment variables `CF_ACCOUNT_ID`, `CF_AI_TOKEN`, `TURNSTILE_SECRET_KEY`, `TURNSTILE_EXPECTED_HOSTNAME`, `ALLOWED_ORIGINS`, `ENVIRONMENT=production`; set the Pages build variables `VITE_TURNSTILE_FRAME_ORIGIN`, `VITE_TURNSTILE_APP_ORIGIN` and `VITE_TURNSTILE_SITE_KEY`.
