# AI Contrast — project rules

These rules apply to the tech lead (main session) and to every agent in `.claude/agents/`.

## What this is

AI Contrast compares two or more contracts clause by clause with AI. It shows a table:
what is the same, what is different, and a rating for the client:

- 🟢 green — favorable for the client;
- 🟡 yellow — pay attention;
- 🔴 red — unfavorable or dangerous for the client.

Every rating has an explanation and a verified quote from the contract.

Key properties of v1:

- **Stateless.** The server stores nothing: no contracts, no keys, no results. No database.
- **BYOK.** The client brings their own AI provider API key.
- **Multilingual.** Contracts and UI in English, Ukrainian and Russian. UI default: English.

People and roles:

- **Customer:** Ihor (GitHub `vik753`). Approves product decisions. Technical carte blanche is given to the tech lead.
- **Tech lead:** Claude, main session. Plans, assigns, merges, reports.
- **Team:** agents in `.claude/agents/` (see `docs/adr/0006-agent-team.md`).

## Read first

1. `docs/plan.md` — requirements and stages.
2. `docs/security/threat-model.md` — security rules. Mandatory for every task.
3. `docs/adr/` — architecture decisions.
4. `docs/agent/PROGRESS.md` and `docs/agent/TASKS.md` — current state and next task.

## Architecture (v1)

| Part | Technology |
| --- | --- |
| `frontend/` | React, TypeScript (strict), Vite, react-i18next (`en` default, `uk`, `ru`) |
| OCR | Tesseract.js + PDF.js in the browser, language data self-hosted (`eng`, `ukr`, `rus`) |
| Browser storage | IndexedDB behind the `CacheStore` port; SHA-256 via Web Crypto API |
| `backend/` | Python 3.13, FastAPI, stateless; progress and results via SSE |
| Text extraction | pdfplumber, python-docx |
| AI layer | `AIProvider` port; adapters on the official `anthropic` and `openai` SDKs. **No LiteLLM.** |
| Validation | Pydantic v2 |
| Rate limiting | slowapi (in memory) |
| Hosting | Cloudflare Pages (frontend, `_headers`), Render (backend, Docker, 512 MB RAM) |

## Hard security rules — never break

1. **No secrets in the repository. Ever.** The v1 server needs no secrets.
2. **Client API key:** only in the `X-Provider-Key` request header. Never in a URL, query string, log, error message or server-side storage. Type `pydantic.SecretStr`. Create SDK clients per request; no global clients holding a key.
3. **Logging:** never log request headers, request or response bodies, contract text, prompts or model output. Log only method, path, status, duration, sizes, counts and error codes.
4. **Outbound HTTP to user-supplied hosts** goes only through the SSRF guard: HTTPS and port 443 only, hostnames only, resolve DNS once and block private/loopback/link-local/multicast/reserved/ULA addresses, connect to the checked IP, no redirects, timeouts and size limits. Provider presets are an allowlist.
5. **Uploaded files:** processed in memory; limits on size, count and pages; type detected by magic bytes; DOCX archive checks (zip bomb); XML without external entities; parsing in a subprocess with time and memory limits.
6. **Untrusted text:** contract text and model output are rendered as plain text only. No `dangerouslySetInnerHTML`. No HTML or Markdown rendering of model output. Links are not clickable.
7. **Prompts:** instructions are separated from data (delimited document blocks). Strict JSON schema validated by Pydantic. Every quote is verified against the source text. The model gets no tools.
8. **Frontend:** no third-party scripts, analytics, fonts or CDNs. Strict CSP in `frontend/public/_headers`.
9. **Dependencies:** minimal. A new dependency needs approval of the tech lead and `security-reviewer`. Pinned in `uv.lock` / `package-lock.json`. Install only with `uv sync --locked` / `npm ci`.
10. **GitHub Actions:** pin every action by full commit SHA. Minimal `permissions:` per workflow.
11. **License AGPL-3.0-only:** the UI shows a "Source code" link to this repository (AGPL section 13).

## Workflow for one task

1. Tech lead writes the task in `docs/agent/TASKS.md`: goal, acceptance criteria, threats touched.
2. `test-engineer` writes tests from the acceptance criteria. It does not read the implementation.
3. `backend-dev` or `frontend-dev` implements on a branch `feat/s<stage>-<short-name>` until the tests pass.
4. `code-reviewer` and `security-reviewer` review the diff independently, each in a fresh context.
5. The developer fixes the findings. Repeat steps 3–5 until there are no blocking findings.
6. If prompts or the AI layer changed, `ai-eval-engineer` runs the eval. No quality regression is allowed.
7. Tech lead merges to `main` through a pull request (squash merge). CI must be green.
8. `docs-writer` updates repo docs and `docs/agent/PROGRESS.md`. Tech lead updates the customer's Obsidian notes.

Rules:

- The author never reviews their own work.
- **Escalation:** if an agent fails the same task twice, the tech lead reruns it with `effort: high`. This file explicitly authorizes that.
- Models and effort per agent are set in each agent file (see `docs/adr/0006-agent-team.md`).

## Conventions

- **Language:** code, comments, commits, repo docs — English. Customer reports and Obsidian notes — Russian, short sentences (ASD-STE100 style), with theory blocks.
- **Commits:** Conventional Commits: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`, `ci:`, `build:`. Security fixes: `fix(security): ...`.
- **Python:** ruff (lint and format), mypy (strict), pytest. Type hints everywhere.
- **TypeScript:** strict mode, ESLint, Prettier, Vitest; Playwright for end-to-end tests.
- **i18n:** no hard-coded UI strings. Keys live in `frontend/src/i18n/locales/{en,uk,ru}.json`.
- **Accessibility:** a rating color is always paired with an icon and a text label.
- **Ports and adapters:** application code depends on ports (`AIProvider`, `CacheStore`), never on a concrete SDK or storage.

## Commands

Filled in at stage 1 (scaffold).

## Definition of Done (every task)

- [ ] Acceptance criteria met. New tests added. All tests green.
- [ ] Security checklist in `docs/security/threat-model.md` passed.
- [ ] `code-reviewer` and `security-reviewer`: no blocking findings.
- [ ] Docs updated: `docs/agent/PROGRESS.md`, ADR if a decision was made.
- [ ] CI green.

## Customer communication

- After each stage the tech lead sends Ihor a report in Russian: what is done, how to check it (commands, links, expected result), plan changes, next stage.
- Ask Ihor only about disputed product questions and blockers.
- Customer notes live in his Obsidian vault, folder `AI Project - Agreements comparison`.

## Resume after a break

1. Read `docs/agent/PROGRESS.md`.
2. Continue with the first unchecked task in `docs/agent/TASKS.md`.
3. Update `PROGRESS.md` after each finished task.
