# Progress

How to resume after a break: read this file, then continue with the first unchecked task in `docs/agent/TASKS.md`.

## Stage status

| # | Stage | Status |
| --- | --- | --- |
| 0 | Project rules | done |
| 1 | Scaffold | done |
| 2 | File upload | planned |
| 3 | Text extraction | planned |
| 4 | Browser hash and cache | planned |
| 5 | Clause splitting | planned |
| 5b | Pseudonymization | planned |
| 6 | Model connection | planned |
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
