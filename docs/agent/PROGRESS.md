# Progress

How to resume after a break: read this file, then continue with the first unchecked task in `docs/agent/TASKS.md`.

## Stage status

| # | Stage | Status |
| --- | --- | --- |
| 0 | Project rules | done |
| 1 | Scaffold | done |
| 2 | File upload | done |
| 3 | Text extraction | done |
| 4 | Browser hash and cache | done |
| 5 | Clause splitting | done |
| 5b | Pseudonymization | done |
| 6 | Model connection | next |
| 7 | Topic catalog | planned |
| 8 | Clause tagging | planned |
| 9 | Analysis | planned |
| 10 | Result table | planned |
| 11 | Token economy and quality | planned |
| 12 | Security audit | planned |
| 13 | Deploy | planned |

## Customer decisions (2026-10-19)

- Stateless backend, BYOK, no database in v1 (ADR 0001).
- Official `anthropic` and `openai` SDKs instead of LiteLLM (ADR 0002).
- Frontend on Cloudflare Pages (ADR 0003).
- pdfplumber and python-docx instead of Docling (ADR 0004).
- License AGPL-3.0-only, public repository (ADR 0005).
- Agent team and review workflow (ADR 0006).
- Carte blanche for the tech lead. Report to the customer after each stage. Ask only on disputed questions and blockers.
- Free default model: demo mode + Cloudflare Workers AI `gpt-oss-120b` with our key and quotas + free Gemini key hint (ADR 0007).
- Pseudonymization before any AI call: all identifiers masked, documents labelled A/B/C, mandatory preview, names restored only in the browser, "OCR via AI" removed (ADR 0008).

## Log

- 2026-10-19 — Stage 0 done: `CLAUDE.md`, `README.md`, `SECURITY.md`, `LICENSE`, threat model, plan, ADR 0001–0006, eight agents in `.claude/agents/`. Secret scanning and push protection are on. Waiting for the customer: private vulnerability reporting, Dependabot alerts and security updates (S0-T5b).
- 2026-10-19 — ADR 0007 accepted (free default model). Obsidian sync pending: the customer's computer was offline.
- 2026-10-19 — Frontend lock file generated with npm 11.6.2: npm 10.9 (bundled with Node 22) crashed with `Cannot read properties of null (reading 'edgesOut')` on `npm install` (chain vitest → msw → vitest@*). `npm ci` works with npm 10.
- Lesson: never run two agents that call `npm ci` or `uv sync` in the same worktree at the same time.
- 2026-10-19 — PR #2 (frontend S1-T2, S1-T2b) merged after two approvals.
- 2026-10-20 — PR #1 (backend S1-T1, S1-T1b, S1-T1c) merged after two approvals. 263 backend tests.
- 2026-10-20 — PR #4 (S1-T3, S1-T4, S1-T4b: CI, Docker Compose, CodeQL, Dependabot, repository policy tests) merged after two approvals. 370 backend tests. Frontend: 266 tests on the lint branch (PR #3, not merged yet), 214 on `main`.
- 2026-10-20 — Stage 1 docs: `CLAUDE.md` Commands, README "Run locally", threat model updates for T3 and T4, T8 (supply chain).
- Lesson: scheduled wake-ups are queued while the session is at its usage limit and arrive only when the session resumes.
- 2026-10-20 — PR #3 (lint follow-ups) and PR #10 (Dependabot tuning) merged. Dependabot PRs #5–#8 answered with `@dependabot ignore` (planned upgrades). Stage 1 done.
- 2026-10-20 — ADR 0008 accepted (pseudonymization). New stage 5b.
- 2026-10-20 — ADR 0009 accepted (prompt injection defense in depth), on the customer's request.
- 2026-10-21 — PR #13: certifi 2026.10.19 (PYSEC-2026-4320, dev-only dependency); pip-audit in CI blocked every PR until the fix.
- 2026-10-21 — PR #11 merged: ADR 0008 and 0009 after two security design reviews. PR #12: uv 0.11.33 (setup-uv `version` updated by hand, as the policy test requires).
- 2026-10-21 — Customer enabled private vulnerability reporting, Dependabot alerts and security updates, and created the `main` ruleset (enforcement and check names still to fix).
- 2026-10-21 — Stage 2 started: ADR 0010 (raw-bytes upload, one file per request), tasks S2-T1, S2-T2, S2-T3.
- 2026-10-21 — PR #15 merged (S2-T1: `/api/extract`, upload limits, type detection) after two review rounds. 864 backend tests.
- 2026-10-21 — PR #16 merged (S2-T2: upload form in the browser). 662 frontend tests.
- 2026-10-21 — PR #17 merged: token economy rules in `CLAUDE.md`.
- 2026-10-21 — Stage 2 done: S2-T3 docs and threat model (T1, T3, T4, T6, T10, T11), README, `CLAUDE.md` Commands.
- Lesson: real-time upload tests and the memory test are CPU-sensitive. Run them under parallel load before approval.
- 2026-10-21 — Stage 3 started. Security reviewer approved the stage 3 dependencies with pinned versions and conditions (`defusedxml`, `pdfminer.six`, `pdfjs-dist`, `tesseract.js`, language data); python-docx and pdfplumber dropped (see `docs/agent/TASKS.md`, "Stage 3 dependencies").
- 2026-10-21 — PR #19 merged: stage 3 plan and ADR 0011 (parsing sandbox: one subprocess per file with OS limits).
- 2026-10-21 — PR #20 merged (S3-T1: sandbox, stage 3 response contract, plain text, language detection). Security review round 1: slot held until the response is sent, `RLIMIT_NPROC` = 0, control characters removed. Memory budget 468.2 MiB worst case. 1158 backend tests. Merged by the customer with a merge commit.
- 2026-10-21 — PR #22 merged (replaces #21, whose head GitHub did not sync): stage 13 blockers (slowloris with `--limit-concurrency`, kernel send buffers), S3-T2 and S3-T4 tasks.
- 2026-10-21 — S3-T2 (DOCX): 233 tests written, implementation in progress (`feat/s3-docx`). S3-T4 (preview): PR #23, code and security review approved; review fixes in progress.
- Lesson: GitHub can lag in syncing a PR head after a push; if CI does not start within minutes, push to a new branch and open a new PR.
- Lesson: start a new agent for a new task (fresh context is cheaper); resume the same agent only for its own review rounds.
- 2026-10-21 — PR #23 merged (S3-T4: preview of extracted text). Both reviews approved; fixes: preview caps (200 blocks or 50,000 characters per file), strict list caps in the client, focus after "Show all". 969 frontend tests.

- 2026-10-22 — PR #26 merged (S3-T2: DOCX extraction with `defusedxml`). Three review rounds: toggle properties, displayed parts only, theme colours and table backgrounds (unresolved → kept with `borderline_text`), markup compatibility, hidden objects, data binding. Worst case 6 s CPU, 46 MiB child RSS. 1573 backend tests.
- 2026-10-22 — New task S3-T2b (list numbering labels) before stage 5: clause numbers in Word are often automatic.
- 2026-10-22 — PR #28 merged: developers, test-engineer and code-reviewer run on Sonnet; security-reviewer stays on Opus (customer request).
- 2026-10-22 — PR #29 merged (S3-T3: PDF extraction with `pdfminer.six`). One review round: unrenderable content → material warnings, exact colour resolution in all colour spaces (unresolved → borderline), freed objects rejected only when extraction resolves them, empty-user-password encryption only. Worst case 100 pages: about 10.7 s CPU. 1827 backend tests.
- Lesson: agent model changes in `.claude/agents/` take effect only in a new session; pass `model` explicitly when starting agents.
- 2026-10-22 — PR #31 merged (S3-T2b: DOCX list numbering labels). Word sequence rules, per-story counters, `w:lvl/w:pStyle`; a label passes the same visibility check as text; a paragraph counts by its paragraph mark (hidden, deleted or moved-from marks do not count). Unknown formats → decimal plus `numbering_approximate`.
- 2026-10-22 — S3-T6 written (Google Docs by public link): ID-only API, server-built export URL, SSRF guard as an `httpcore` network backend (ADR 0012), `httpx` 0.28.1 as a runtime dependency. Security reviewer approved the dependency and, after changes, the design (strict hostname rule, IPv6 rule beyond `is_global`, no proxy or Unix socket paths, `httpx` request log off, narrow `googleusercontent` host). Google Picker is not in v1.
- 2026-10-22 — PR #33 merged (docs): S3-T6 task, ADR 0012 (outbound HTTP through a guarded `httpx` client), threat model T2 and T7.
- 2026-10-22 — PR #32 merged (S3-T5: browser OCR of scanned PDF pages). Self-hosted pdf.js (legacy build: the modern build needs `Map.prototype.getOrInsertComputed`, which Chromium 141 lacks) and Tesseract.js with `ukr+rus+eng` LSTM data checked by SHA-256. CSP `worker-src 'self'` and a `trusted-types default` policy installed at startup that allows only our worker URLs. One OCR job at a time, 30 pages per file, 60 s limits for setup and per page, confidence warnings. Security reviewer ran a real-browser test (Chromium 141): OCR works with no CSP or Trusted Types violations. Compose: `public/ocr` is a named volume. 1123 frontend tests.
- 2026-10-22 — PR #35 merged (S3-T6a: Google Docs by public link, backend). Review round 1: code — the slot is taken before the body read, with its own short deadline `GOOGLE_BODY_TIMEOUT_SECONDS` (5 s), shared `app/api/common.py`, typed client factory; security — resolver `OSError` → `google_doc_unavailable` (was 500), `sni_hostname` refused in the transport, `SSLKEYLOGFILE` ignored. Every `httpx` timeout → `google_doc_timeout` (AC amended). 2351 backend tests. Merged by the customer.
- 2026-10-22 — PR #36 merged (S3-T6b: Google Docs link field in the upload form). Shared `postExtract` core; strict link parsing (WHATWG normalization pinned by tests); the full ID is kept only in component memory while its row exists; `readCapped` cancels the body on abort, also when aborted before reading. 1470 frontend tests. Merged by the customer.
- 2026-10-22 — Stage 3 done. Finished stages 2 and 3 moved to `docs/agent/TASKS-archive.md`; open follow-ups stay in `docs/agent/TASKS.md`.
- Lesson: in this session the tech lead cannot merge (permission classifier, "Merge Without Review"). The customer merges approved PRs. A local trial merge is blocked too. Rebase the second PR after the first is merged.
- Lesson: CI jobs `docker` and `compose` can fail transiently on the image build. Rerun failed jobs before you investigate.
- 2026-10-28 — PR #38 merged: stage 4 plan, ADR 0013, two security design rounds (multi-tab fail closed, mapping never stored).
- 2026-10-28 — PR #47 merged: all agents run on medium effort (customer request).
- 2026-10-28 — PR #48 merged: `filelock` 4.2.4 (six advisories, dev-only dependency). The advisories blocked all PRs until the fix.
- 2026-10-28 — PR #49 merged (S4-T1: hashes and duplicate detection). Hashing is sequential with a 30 s timeout. The test setup wraps `crypto.subtle.digest` with a Node hash, so fake-timer tests are stable.
- 2026-10-28 — PR #50 merged (S4-T2: `CacheStore`, history off by default, settings panel "Data and history", clear all, cached-result dialog). Race fix: a stale count overwrote 0 after "delete all". CI checks that `dist/` has no `fake-indexeddb`. 1721 frontend tests.
- 2026-10-28 — Stage 4 done. Finished stage 4 moved to `docs/agent/TASKS-archive.md`; ADR 0013 accepted; threat model T3, T8, T11 updated; README updated.
- Lesson: the weekly usage limit stopped two agents mid-task on 2026-10-22. Their uncommitted work survived. Resuming the same agents after the reset continued it.
- 2026-10-28 — PR #52 merged: stage 5 plan, ADR 0014, two security design rounds (cleaned blocks returned once with spans only, running-line and requisites abuse rules, parent never parses the body).
- 2026-10-28 — PR #53 merged (S5-T0 30 synthetic UK/RU/EN fixtures + S5-T1 `/api/segment`). Worst case about 2.5 s at the caps. 2950 backend tests.
- 2026-10-28 — PR #54 merged (S5-T1b shared Layer 1 cleaning). From the PR #53 security review: cleaning had been incomplete and different on the two endpoints. Python pinned to 3.13 after CI picked a newer Python with other Unicode tables.
- 2026-10-28 — PR #55 merged (S5-T2 clauses in the browser): Clauses/Text preview, strict reply validation including coverage, shared request budget of 2, code-point index. 1823 frontend tests.
- 2026-10-28 — A flaky log-canary test fixed: clause numbers such as "7.3" could match log durations.
- 2026-10-28 — Customer now confirms merges in chat ("ask" permission mode). The tech lead merges after two approvals and green CI.
- Lesson: a 5-hour usage limit stopped agents mid-task. Resuming the same agents kept their work.
- 2026-10-28 — Stage 5 done. ADR 0014 accepted; threat model T5, T6, T11 updated; finished stage 5 moved to `docs/agent/TASKS-archive.md`; README and `CLAUDE.md` Commands updated.
- 2026-10-28 — PR #57 merged: stage 5b plan, ADR 0015.
- 2026-10-28 — PR #58 (S5b-T0 corpus, S5b-T1 detector), #59 (flaky form tests), #60 (S5b-T2 safety check and type gate), #61 (S5b-T3 browser preview and masking), #62 (contained non-high hits count as acknowledged; bisect lookup) merged.
- 2026-10-29 — PR #63 (address stops before codes), #64 (canary harness, shared masking vectors, held-out corpus), #65 (detector round 2), #66 (eval gates and baseline), #67 (detector round 3: unit words, addresses) merged.
- Lesson: the held-out split found overfitting (round 2 held-out recall en 0.76). Round 3 used category briefs without values, and near-copies were removed from the held-out split.
- 2026-10-29 — Stage 5b done: detector in `/api/segment`, mandatory browser preview, `/api/safety-check` with the type gate (`app/pseudo/gate.py`, AST policy test), canary harness (`backend/tests/canary/`) and detector eval. Held-out numbers: recall en 64/66, ru 64/64, uk 57/57; precision 1.000 per language; 0 `must_not_mask` violations; one gate xfail (en PERSON normal 0.929). ADR 0015 accepted; threat model T5, T6, T11 updated; finished stage 5b moved to `docs/agent/TASKS-archive.md`; README updated. `CLAUDE.md` Commands now show detection and `/api/safety-check`. The per-IP limit is still a stage 13 blocker. Next: stage 6 (model connection).
