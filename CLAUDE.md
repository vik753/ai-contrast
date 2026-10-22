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
| Text extraction | One sandboxed subprocess per file (ADR 0011); own DOCX walker over relationship-resolved parts with `defusedxml`; `pdfminer.six` with a render-mode device (no pdfplumber, no python-docx; ADR 0004 revision, ADR 0009) |
| AI layer | `AIProvider` port; adapters on the official `anthropic` and `openai` SDKs. **No LiteLLM.** |
| Validation | Pydantic v2 |
| Rate limiting | slowapi (in memory) |
| Free default model | Cloudflare Workers AI `@cf/openai/gpt-oss-120b` via the `openai` adapter, our token, Turnstile, daily quotas (ADR 0007) |
| Demo mode | Built-in synthetic contracts with precomputed results (ADR 0007) |
| Pseudonymization | Identifiers replaced by typed placeholders before any AI call; mandatory preview; mapping only in the browser (ADR 0008) |
| Hosting | Cloudflare Pages (frontend, `_headers`), Render (backend, Docker, 512 MB RAM) |

## Hard security rules — never break

1. **No secrets in the repository. Ever.** The server holds only its own operational secrets for the free default model and Turnstile (ADR 0007), in hosting environment variables, typed `SecretStr`. It never stores client secrets.
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
12. **Pseudonymization (ADR 0008):** no identifier reaches an AI provider. The AI layer accepts only `PseudonymizedDocument` / `PseudonymizedText` / `ConfirmedTopic` (frozen dataclasses with a runtime sentinel, created only by the server safety pass, never a request model); the `AIProvider` port takes no `str`. File names, document metadata and the placeholder mapping never reach an AI provider. No page images are sent to an AI provider.
13. **Prompt injection (ADR 0009):** read what the person reads (DOCX parts resolved through relationships, own walker, material "Not read" warnings); clean input (default-ignorable and format characters, provably invisible PDF/DOCX text); **one document per AI call** — no call receives text of two documents, directly or through summaries; schema-first topics, comparison by code; random per-block nonce; every finding needs a verbatim quote, green also needs the deterministic exception rule and number checks; no clause can be hidden by tagging; **every cap fails closed**.

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

Token economy (customer request, 2026-10-21):

- `test-engineer` writes tests first for new acceptance criteria and for BLOCKER/HIGH/MAJOR review findings. For MINOR/NIT findings the developer adds the tests, and the reviewer checks them in the delta review.
- A repeat review is a **delta review** of the fix commits only, by the reviewer(s) who requested changes. A reviewer who approved does not review again unless the fix touches their area.
- No throwaway reference implementations or mutation runs unless the tech lead asks for them.
- Agent reports: at most 300 words. Reviewers list findings only (no "checked and correct" section); developers list changed files, check results and open points.
- Read only the sections you need: the current stage in `docs/agent/TASKS.md`, the named threat-model sections and ADRs. Finished stages are in `docs/agent/TASKS-archive.md`.
- Customer messages: short status (3–5 lines). Full report with theory blocks only at the end of a stage. Obsidian notes are synced once per stage.

## Conventions

- **Language:** code, comments, commits, repo docs — English. Customer reports and Obsidian notes — Russian, short sentences (ASD-STE100 style), with theory blocks.
- **Commits:** Conventional Commits: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`, `ci:`, `build:`. Security fixes: `fix(security): ...`.
- **Python:** ruff (lint and format), mypy (strict), pytest. Type hints everywhere.
- **TypeScript:** strict mode, ESLint, Prettier, Vitest; Playwright for end-to-end tests.
- **i18n:** no hard-coded UI strings. Keys live in `frontend/src/i18n/locales/{en,uk,ru}.json`.
- **Accessibility:** a rating color is always paired with an icon and a text label.
- **Ports and adapters:** application code depends on ports (`AIProvider`, `CacheStore`), never on a concrete SDK or storage.

## Commands

Run every command from the repository root unless the block starts with `cd`.
No secrets and no `.env` file are needed.

### Whole stack (Docker Compose)

Needs Docker Engine 28.0 or later, or Docker Desktop.

```bash
# Linux only, before the first `up`: you own frontend/node_modules, not root.
mkdir -p frontend/node_modules

# Build and start backend and frontend.
docker compose up --build
```

Expected: the backend becomes healthy, then the frontend starts.
Open http://localhost:5173 for the UI and http://localhost:8000/api/health for the backend health check.

```bash
# Rebuild only the backend after backend changes (there is no backend hot reload).
docker compose up --build backend

# Stop the stack.
docker compose down
```

Expected: `docker compose down` stops and removes the containers.
Add `-v` to also delete the `node_modules` and npm cache volumes.

### Backend (local, without Docker)

Needs Python 3.13 and uv.

```bash
cd backend
uv sync --locked
```

Expected: uv creates `backend/.venv` from `uv.lock` and prints no error.

```bash
cd backend
ENVIRONMENT=development ALLOWED_ORIGINS=http://localhost:5173 \
  uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload \
  --no-access-log --no-server-header --log-config log_config.json
```

Expected: uvicorn prints `Uvicorn running on http://127.0.0.1:8000`.
`curl http://127.0.0.1:8000/api/health` returns `{"status":"ok","version":"0.1.0"}`, and the log shows `GET /api/health 200 duration_ms=...`.
Check the upload endpoint (the body is raw bytes, no file name):

```bash
curl -sS -X POST -H 'Content-Type: application/octet-stream' --data-binary 'Hello, contract.' http://127.0.0.1:8000/api/extract
```

Expected: `{"kind":"text","bytes":16,"language":"unknown","pages":null,"blocks":[{"text":"Hello, contract.","part":"body","page":null}],"ocr_pages":[],"removed":[],"warnings":[]}` (`language` is `unknown` because the text is too short).

Always keep `--log-config log_config.json` (it installs the log redaction filter, threat model T1) and `--no-access-log` (our own access log omits query strings).

Backend checks (the same as CI):

```bash
cd backend
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy app
uv run --locked pytest -q
uv run --locked pip-audit --strict --vulnerability-service pypi
uv run --locked pip-audit --strict --vulnerability-service osv
```

Expected:

- `ruff check .` prints `All checks passed!`.
- `ruff format --check .` reports that all files are already formatted.
- `mypy app` prints `Success: no issues found`.
- `pytest -q` ends with all tests passed.
- `pip-audit` finds no known vulnerabilities.

To fix formatting, run `uv run --locked ruff format .`.

### Frontend (local, without Docker)

Needs Node 22.13 or later (npm 11.6.2 is set in `packageManager`).

```bash
cd frontend
npm ci --ignore-scripts
```

Expected: npm installs the locked dependencies and runs no lifecycle scripts.

```bash
cd frontend
npm run dev
```

Expected: Vite prints `Local: http://localhost:5173/`.
It proxies `/api` to http://localhost:8000, so start the backend first.

Frontend checks (the same as CI):

```bash
cd frontend
npm run lint
npm run typecheck
npm run test
npm run build
npm run format:check
npm audit --audit-level=high
```

Expected:

- `lint` ends with no warnings and no errors (`--max-warnings=0`).
- `typecheck` ends with no output.
- `test` ends with all tests passed.
- `build` writes `frontend/dist/`.
- `format:check` reports that all files use Prettier code style.
- `npm audit` reports no high or critical vulnerabilities.

To fix formatting, run `npm run format`.

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
