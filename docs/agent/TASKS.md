# Tasks

Format: one task per block. Goal, owner, branch, acceptance criteria (AC), threats touched (see `docs/security/threat-model.md`).
Check a task only when it is merged to `main` with green CI.

Finished stages 0 to 5b: `docs/agent/TASKS-archive.md`.

## Stage 6 — Model connection (ADR 0016)

Order: S6-T0 (dependency approval) first; then S6-T1 (`app/net/` on `httpx2`); then S6-T2 (port and adapters) and S6-T3 (limiter and client IP) in parallel; then S6-T4 (check endpoint and free mode); S6-T5 (browser) after S6-T4's API is fixed; S6-T6 docs last.

### S6-T0 Dependency approval

- [x] Done 2026-10-29: `security-reviewer` approved the versions now in ADR 0016 point 1 and the design changes of round 1.

### S6-T1 Outbound client on `httpx2` (backend)

- Owner: `backend-dev`. Tests first: `test-engineer` (port the existing guard and Google Docs tests). Branch: `feat/s6-net`.
- Threats: T2, T7, T8.

1. `app/net/` uses `httpx2`/`httpcore2`; the guarded network backend, client factory and Google Docs export behave exactly as before (every existing guard, redirect, size-cap and error-mapping test passes on the new packages).
2. TLS context `ssl.create_default_context(cafile=certifi.where())` passed as `verify=`; `certifi` pinned as runtime dependency; `truststore` never used; `trust_env=False`. Tests pin the context type and show `SSL_CERT_FILE`, `SSL_CERT_DIR`, `SSLKEYLOGFILE`, `HTTPS_PROXY`, `ALL_PROXY` have no effect. `[tool.uv] no-build = true`.
3. Policy tests: only `app/net/` imports `httpx2`/`httpcore2`; nothing in `app/` imports `httpx`/`httpcore`; no `opentelemetry-sdk` or exporter in `uv.lock`. `httpx2`/`httpcore2` loggers at `WARNING` in `log_config.json` and at startup.
4. `httpx` remains a dev dependency only; `pip-audit` clean.

### S6-T2 `AIProvider` port and adapters (backend)

- Owner: `backend-dev`. Tests first: `test-engineer`. Branch: `feat/s6-ai`. After S6-T1.
- Threats: T1, T2, T5, T11.

1. Port, `AIRequest`, `ModelJson`, `CheckResult` per ADR 0016 point 2; no `str` parameter on the port (AST policy test covers `app/ai/`); one document per `AIRequest` (policy test).
2. Prompt assembly with separate instruction and data messages, random per-block nonce delimiters, nonce never present in the block text.
3. Adapters per point 3: one SDK client per request on the guarded client; `max_retries=0`; explicit `base_url`; Anthropic tracing off; the environment variables of point 3 (base URLs, org/project, custom headers, log, `ANTHROPIC_OPEN_TELEMETRY_*`) have no effect (tests set canaries; no span recorded); every 3xx refused (`provider_bad_response`, test with a cross-host 307); no tool fields on the wire; `max_tokens` always set; timeouts and a 2 MiB response cap that fails closed. `PromptTemplate` is a closed type and the AST test checks `AIRequest` fields.
4. Error mapping to the codes of point 3 for every SDK error class and status; no SDK text, body or request ID in logs or errors (log canary).
5. Presets and model-ID grammar per point 4 (model ID only in the body); `base_url` refused for every preset except `custom`; custom base URL syntax checks with tests for user info, query, fragment, port, IP literals, single labels, `http`.
6. Wire canary (point 10): both adapters, `check()` and `complete_json()`, identifier and key canaries; the key only in the auth header.

### S6-T3 Rate limiter and client IP (backend)

- Owner: `backend-dev`. Tests first: `test-engineer`. Branch: `feat/s6-limits`. After S6-T1 (parallel to S6-T2).
- Threats: T6, T10.

1. `app/limits/` fixed-window limiter with a bounded table that fails closed; time injected for tests.
2. Client IP per ADR 0016 point 8 (rightmost `X-Forwarded-For` hop in production, peer in development; invalid → `unknown`; IPv6 keyed by /64); spoofed leftmost entries have no effect.
3. At most 1 extraction slot per IP across `/api/extract`, `/api/extract/google-doc`, `/api/segment`, `/api/safety-check`; `503 busy` with `Retry-After`; the shared pool of 2 stays. Closes the stage 13 blocker (T6 control 4).
4. No IP address is logged (counts and codes only).

### S6-T4 Connection check and free mode (backend)

- Owner: `backend-dev`. Tests first: `test-engineer`. Branch: `feat/s6-check`. After S6-T2 and S6-T3.
- Threats: T1, T2, T6, T10.

1. `POST /api/provider/check` per ADR 0016 point 6; body cap 4 KiB; `X-Provider-Key` rules of point 5 (`invalid_provider_key`, `unexpected_provider_key`); never returns model text; per-IP limits; 2 checks in flight.
2. Free mode per point 7: settings `CF_ACCOUNT_ID`, `CF_AI_TOKEN`, `TURNSTILE_SECRET_KEY`, `TURNSTILE_EXPECTED_HOSTNAME` as `SecretStr`/validated; `503 free_mode_unavailable` without them; Turnstile verification through `app/net/` (mocked in tests; Cloudflare's documented test secrets for local use); `hostname`, `action` and `challenge_ts` (300 s) checked; token reuse refused with a bounded replay table that fails closed; per-IP daily limit and global Neuron budget with `429 free_quota_exhausted`; reset at 00:00 UTC.
3. Log canary for `CF_AI_TOKEN`, Turnstile secret and the client key on every path.
4. `CLAUDE.md` Commands: a check request that returns `provider_blocked_host` for `https://127.0.0.1` without any network call, and one that returns `free_mode_unavailable` locally.

### S6-T5 Provider settings in the browser (frontend)

- Owner: `frontend-dev`. Tests first: `test-engineer`. Branch: `feat/s6-ui`. After S6-T4's API is merged.
- Threats: T1, T9, T10.

1. Settings panel per ADR 0016 point 9, all strings in `en`, `uk`, `ru`.
2. Key storage: `sessionStorage` default, opt-in `localStorage` with a warning, "Forget key", removed by "Clear all"; key only in `X-Provider-Key` with the pinned fetch options; tests check it never appears in a URL, IndexedDB or console output.
3. Turnstile isolated per ADR 0016 point 7: a static `turnstile.html` on a separate origin with its own CSP; the app embeds it as a sandboxed iframe only for free mode; `postMessage` with exact-origin checks both ways and a strict message shape; the app CSP adds only the frame origin to `frame-src` and never loads a Cloudflare script; tests prove nothing Cloudflare loads on page load or for other presets, and that messages from other origins or with other shapes are ignored; Cloudflare's test site key in development.
4. Free mode notice and Gemini hint with the data-use warning.

### S6-T6 Docs for stage 6

- Owner: `docs-writer`. After S6-T1–T5 are merged.
- ADR 0016 → accepted; threat model T1 (control 10: custom-header and OpenTelemetry variables), T2 (3xx refused on AI calls), T6 (per-IP slot blocker closed, IPv6 /64, Render header check at stage 13), T9 (Turnstile isolated origin), T10, T11 control 10; `CLAUDE.md` architecture row (own limiter, `httpx2`) and rule 8 exception note; README (providers, free mode, key storage); customer actions for stage 13 (Cloudflare account, Workers AI token, Turnstile widget, Render env vars).

## Open follow-ups

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

### S2 follow-ups (from the ADR 0008/0009 design review, for later stages)

- Stage 6 / before stage 13 (**release blocker**): at most 1 extraction slot per client IP (T6 control 6 client-IP rule). It covers `/api/safety-check` too.
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
