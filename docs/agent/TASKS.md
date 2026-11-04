# Tasks

Format: one task per block. Goal, owner, branch, acceptance criteria (AC), threats touched (see `docs/security/threat-model.md`).
Check a task only when it is merged to `main` with green CI.

Finished stages 0 to 6: `docs/agent/TASKS-archive.md`.

## Stage 7 — Topic catalog (ADR 0017)

Order: S7-T0 (catalog content) and S7-T1 (catalog loader, Layer 2, topic safety pass) in parallel; S7-T2 (AI topic endpoints and free pass) after S7-T1; S7-T3 (browser) after S7-T2's API is fixed; S7-T4 (eval) after S7-T2; S7-T5 docs last.

### S7-T0 Catalog content

- Owner: `domain-analyst`. Branch: `feat/s7-catalog` (only `shared/topics/` and `backend/eval/topics/fixtures/`).
- Four domain files per ADR 0017 point 1 (`kasko`, `osago`, `lease`, `property_insurance`) in EN/UK/RU: sides, 8–20 topics each with a description, typed attributes with directions per side, synonyms (stems for UK/RU case forms) for stage 8 keyword tags. Ukrainian law terms for UK/RU templates (КАСКО, ОСЦПВ/ОСАГО), neutral wording for EN.
- Synthetic test contracts for the eval (2 per domain, at least one in each language, fictional values only) with the expected topic list and, per topic, the expected attribute values with clause references (for stage 9 too).
- `README.md` in `shared/topics/` lists the domains, topic counts and the sources used.

### S7-T1 Catalog loader, Layer 2 and topic safety pass (backend)

- Owner: `backend-dev`. Tests first: `test-engineer`. Branch: `feat/s7-topics`. Threats: T5, T11.

1. `app/topics/catalog.py`: Pydantic models and caps of ADR 0017 point 1; loader that fails startup on an invalid file; `catalog_version`; `GET /api/topics/catalog`. Tests use small synthetic catalogs, not S7-T0 content.
2. `app/injection/`: Layer 2 per ADR 0017 point 4 (versioned pattern file, skeleton matching, linear-time, classes `heuristic`/`high`, spans), with the ADR 0009 token list and honest negatives.
3. `app/topics/safety.py` per point 3 (cleaning, grammar, placeholder-free on skeleton, identifier detector, Layer 2) with codes `invalid_topic_text`, `topic_contains_identifier` (spans), `topic_flagged`.
4. Gate: `ConfirmedTopic` holds the whole definition (point 3) with frozen `ConfirmedAttribute`; only `confirm_topic()` creates it; not bound to a document; the AST policy test is extended.
5. `AIRequest`: `document` optional; each `PromptTemplate` declares `requires_document` / `forbids_document`; enforced in `__post_init__`.
6. Stage 6 follow-up: the `tests/check` helpers pass hooks to `install()`; the `app.state.*` fallback in `CheckState` is deleted.

### S7-T2 AI topic endpoints and free pass (backend)

- Owner: `backend-dev`. Tests first: `test-engineer`. Branch: `feat/s7-topic-ai`. After S7-T1. Threats: T1, T5, T6, T10, T11.

1. Prompts and strict output schemas for `SUGGEST_TOPICS`, `PROPOSE_ATTRIBUTES`, `EXPAND_SYNONYMS` (point 5): caps, one repair attempt without the previous output, `ai_bad_output`.
2. Endpoints of point 6 with the provider selection, server-side safety passes (suggest: masked document as in `/api/safety-check`; others: topic definition), body caps, per-IP limits, 1 AI call in flight per client and 2 per server (shared with `/api/provider/check`), every model text through the topic safety pass; one document per call (wire canary).
3. Free pass (point 6): HMAC token, 15 min, same /48, at most 20 calls counted in memory, `FREE_PASS_KEY` in the "all or none" free settings; per-IP free quota and Neuron budget still charged.
4. Log canary: no topic text, model output, key or pass in logs.
5. `CLAUDE.md` Commands: `GET /api/topics/catalog` and one refused topic (`topic_flagged`) without any AI call.

### S7-T3 Topic panel in the browser (frontend)

- Owner: `frontend-dev`. Tests first: `test-engineer`. Branch: `feat/s7-topic-ui`. After S7-T2's API is merged. Threats: T1, T3, T5.

1. Topic panel per ADR 0017 point 7 (domain, side, template topics, suggested topics, own topics with attribute proposal and editing, confirm); every string in `en`/`uk`/`ru`; plain-text rendering of every model-provided string.
2. Own topics: memory by default, opt-in `localStorage` `aic.topics.v1`, removed by Clear all; export/import JSON with a 256 KiB cap and strict validation.
3. Errors `topic_contains_identifier` (highlight spans), `topic_flagged`, `ai_bad_output`, quota and busy codes mapped to messages.

### S7-T4 Topic eval (first AI eval)

- Owner: `ai-eval-engineer`. After S7-T2. Branch: `feat/s7-eval`.
- `backend/eval/topics/` per ADR 0017 point 8: recorded-response mode in CI, live mode locally; baseline file; numbers in the PR.

### S7-T5 Docs for stage 7

- Owner: `docs-writer`. After S7-T0–T4 are merged.
- ADR 0017 → accepted; threat model T5 (Layer 2 implemented, topic text rules), T10 (free pass), T11 (`ConfirmedTopic` as the only cross-document string); `CLAUDE.md` Commands; README (topics).

## Open follow-ups

### Stage 7 follow-ups (from stage 6)

- Stage 7 (in S7-T1): make the tests/check helpers pass hooks to `install()` and delete the `app.state.*` fallback in `CheckState` (`provider_transport`, `turnstile_transport`, `clock`; code review S6-T4).
- Stage 7 (in S7-T4): run the first AI eval (`ai-eval-engineer`) when the first real prompts arrive. Stage 6 has no real prompts, only the fixed connection probe.
- Stage 7 (revised by ADR 0017 point 3): `ConfirmedTopic` is **not** bound to a document (it is the one cross-document string, ADR 0009). The builder that computes `PseudonymizedText.source` comes with the first call that carries such a text (stage 8 or 9).

### Stage 10 follow-ups (from stage 5b)

- Stage 10: never restore names in model text at neutralized spans (`⟦…⟧`) or at tokens with non-`[` brackets.

### Stage 11 follow-ups (from stage 5 and 5b)

- Stage 11: eval case — harmful sentence repeated on every page (ADR 0014 point 5).
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

### Stage 13 blockers and follow-ups (from stages 3 and 6)

- Stage 13 blockers: header-read timeout / slowloris with `--limit-concurrency 32`, and kernel send buffers of cut-off connections (threat model T6 control 9).
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
