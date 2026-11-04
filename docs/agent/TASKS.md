# Tasks

Format: one task per block. Goal, owner, branch, acceptance criteria (AC), threats touched (see `docs/security/threat-model.md`).
Check a task only when it is merged to `main` with green CI.

Finished stages 0 to 6: `docs/agent/TASKS-archive.md`.

## Next: Stage 7 — Topic catalog

The tech lead writes the stage 7 tasks here before work starts (see `docs/plan.md`). Start with the follow-ups below.

## Open follow-ups

### Stage 7 follow-ups (from stage 6)

- Stage 7: make the tests/check helpers pass hooks to `install()` and delete the `app.state.*` fallback in `CheckState` (`provider_transport`, `turnstile_transport`, `clock`; code review S6-T4).
- Stage 7: run the first AI eval (`ai-eval-engineer`) when the first real prompts arrive. Stage 6 has no real prompts, only the fixed connection probe.
- Stage 7: bind `ConfirmedTopic` to its document, as `PseudonymizedText.source` is bound (`document_digest`), and add the builder that computes `source` in the safety pass (threat model T11 control 10a).

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
