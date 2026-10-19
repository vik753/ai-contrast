# Tasks

Format: one task per block. Goal, owner, branch, acceptance criteria (AC), threats touched (see `docs/security/threat-model.md`).
Check a task only when it is merged to `main` with green CI.

## Stage 0 — Project rules

- [x] S0-T1 Project rules: `CLAUDE.md`, `README.md`, `SECURITY.md`, `LICENSE` (AGPL-3.0-only).
- [x] S0-T2 Threat model and plan: `docs/security/threat-model.md`, `docs/plan.md`.
- [x] S0-T3 ADR 0001–0006.
- [x] S0-T4 Agents: `.claude/agents/*.md`.
- [x] S0-T5a Secret scanning and push protection: enabled (verified through the API).
- [ ] S0-T5b **Customer action** (the session proxy cannot change repository settings): enable private vulnerability reporting, Dependabot alerts and Dependabot security updates in Settings → Security.

## Stage 1 — Scaffold

Pinned GitHub Actions (resolved 2026-10-19, use full SHA with a version comment):

| Action | Version | Commit SHA |
| --- | --- | --- |
| `actions/checkout` | v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| `actions/setup-node` | v7.1.0 | `949feb2413d6458794dcd2491c4babbbce0c15c1` |
| `astral-sh/setup-uv` | v10.3.0 | `1c37ad07a6a961277cf70c0d37d6f313000f5884` |
| `github/codeql-action` (`init`, `analyze`) | v4.39.0 | `6f2ac81f5cd81fe351a197ba0b00d91d03cd2aee` |

### S1-T1 Backend skeleton

- Owner: `backend-dev`. Tests first: `test-engineer`. Branch: `feat/s1-backend`.
- Goal: a stateless FastAPI app with safe defaults.
- Layout: `backend/pyproject.toml` (uv project, Python 3.13), `backend/uv.lock`, `backend/app/main.py` with `create_app()`, `backend/app/settings.py` (pydantic-settings), `backend/app/middleware/`, `backend/tests/`.
- Runtime dependencies (only these): `fastapi`, `uvicorn`, `pydantic-settings`. Dev: `pytest`, `httpx`, `ruff`, `mypy`, `pip-audit`.
- AC:
  1. `GET /api/health` returns `200` and `{"status": "ok", "version": "<package version>"}`.
  2. Every API response has `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.
  3. CORS allows only origins from the setting `ALLOWED_ORIGINS` (comma-separated). Allowed methods: `GET`, `POST`. Allowed request headers: `Content-Type`, `X-Provider-Key`. A request from another origin gets no `Access-Control-Allow-Origin`.
  4. Access log middleware logs one line per request: method, path (without query string), status, duration in ms. Uvicorn's own access log is disabled.
  5. Unhandled exceptions return `500` with body `{"error": "internal_error"}`. The log records only the exception class name and the request path — no exception message, no headers, no body.
  6. **Log canary:** requests with header `X-Provider-Key: sk-CANARY-<random>` (to `/api/health` and to a test-only route that raises) leave no trace of the canary in captured logs or responses.
  7. Settings: `ENVIRONMENT` (`development` | `production`), `ALLOWED_ORIGINS`, `ALLOW_PRIVATE_PROVIDER_URLS` (default `false`). OpenAPI docs (`/docs`, `/openapi.json`) are disabled in production.
  8. `ruff check`, `ruff format --check`, `mypy --strict` (on `app/`), `pytest` pass.
  9. `backend/Dockerfile`: multi-stage build with uv, `python:3.13-slim` base, non-root user, `uv sync --locked --no-dev`, listens on `$PORT` (default 8000), `--no-access-log`, `--proxy-headers` off unless documented.
- Threats: T1, T3, T6, T8.
- Public interface (contract between `test-engineer` and `backend-dev`):
  - `app/__init__.py` exports `__version__: str`.
  - `app/settings.py`: `class Settings(pydantic_settings.BaseSettings)` with fields `environment: Literal["development", "production"] = "development"`, `allowed_origins: list[str] = ["http://localhost:5173"]` (env `ALLOWED_ORIGINS`, comma-separated, whitespace trimmed), `allow_private_provider_urls: bool = False`. Tests may build `Settings(...)` directly or through environment variables.
  - `app/main.py`: `def create_app(settings: Settings | None = None) -> FastAPI` and a module-level `app = create_app()` for `uvicorn app.main:app`.
  - Loggers live under the `ai_contrast` namespace (for example `ai_contrast.access`, `ai_contrast.errors`). Tests capture all loggers with `caplog` at `DEBUG`.
  - Tests may add their own routes to an app from `create_app()` (for example a route that raises) and use `TestClient(app, raise_server_exceptions=False)`.
- Working directory: git worktree `/home/claude/wt/s1-backend` on branch `feat/s1-backend`.

### S1-T2 Frontend skeleton

- Owner: `frontend-dev`. Tests first: `test-engineer`. Branch: `feat/s1-frontend`.
- Goal: a React + TypeScript app shell with i18n and safe defaults.
- Layout: `frontend/` (Vite React TS), `frontend/src/i18n/` with `locales/en.json`, `uk.json`, `ru.json`, `frontend/public/_headers`.
- Dependencies: `react`, `react-dom`, `i18next`, `react-i18next`. Dev: Vite, TypeScript, ESLint (flat config, typescript-eslint, react-hooks), Prettier, Vitest, Testing Library, jsdom. No language-detector plugin, no UI kit, no web fonts (system font stack).
- AC:
  1. The page shows a header with "AI Contrast", a language switcher (EN / UK / RU), a main area with a short product description, and a footer.
  2. Default language is English on first visit, whatever the browser language is.
  3. Switching the language changes all UI text immediately and is remembered in `localStorage` (key `aic.lang`). A broken or blocked `localStorage` does not break the page.
  4. `<html lang>` follows the current language.
  5. Footer: "Source code" link to `https://github.com/vik753/ai-contrast` (AGPL section 13), `rel="noopener noreferrer"`; a one-line privacy note ("We store nothing on our server…").
  6. ESLint forbids `dangerouslySetInnerHTML` (rule `no-restricted-syntax` on the JSX attribute) — a test file or lint fixture proves the rule fires.
  7. No hard-coded UI strings in components: all text comes from i18n keys; all three locale files have the same keys (a unit test checks key parity).
  8. `frontend/public/_headers` contains the CSP and headers from threat model T9 (`connect-src 'self'` until the API domain is known).
  9. Vite dev server proxies `/api` to `VITE_API_PROXY_TARGET` (default `http://localhost:8000`).
  10. `npm run lint`, `npm run typecheck`, `npm test`, `npm run build` pass. `package-lock.json` committed.
- Threats: T1 (XSS), T8, T9.
- Public interface (contract between `test-engineer` and `frontend-dev`):
  - `src/App.tsx`: default export `App` (renders header, main and footer; expects i18n to be set up).
  - `src/i18n/index.ts` exports:
    - `SUPPORTED_LANGUAGES = ["en", "uk", "ru"] as const` and `type Language`;
    - `LANGUAGE_STORAGE_KEY = "aic.lang"`;
    - `setupI18n(): Promise<i18n>` — reads the stored language (falls back to `en` on missing, invalid or throwing storage), initializes i18next, sets `<html lang>`;
    - `changeLanguage(lang: Language): Promise<void>` — switches language, sets `<html lang>`, stores the choice (ignores storage errors).
  - Locale files `src/i18n/locales/{en,uk,ru}.json` contain at least these keys: `app.title`, `home.tagline`, `language.label`, `footer.source`, `footer.privacy`. `app.title` is `"AI Contrast"` in all languages.
  - Language switcher: a group labelled by `language.label` with three buttons whose accessible names are `EN`, `UK`, `RU`; the active one has `aria-pressed="true"`.
  - Footer link: accessible name = `footer.source` text; `href="https://github.com/vik753/ai-contrast"`; `rel` contains `noopener` and `noreferrer`.
  - ESLint flat config at `frontend/eslint.config.js`; tests may lint a code string with the ESLint Node API and a virtual file path `src/__lint_fixture__.tsx`.
  - Test runner: Vitest with jsdom and Testing Library; setup file `src/test/setup.ts`.
- Working directory: git worktree `/home/claude/wt/s1-frontend` on branch `feat/s1-frontend`.

### S1-T3 Local run with Docker Compose

- Owner: `backend-dev`. Branch: `feat/s1-compose` (after T1 and T2 are merged).
- AC:
  1. `docker compose up --build` starts the backend on `http://localhost:8000` and the frontend dev server on `http://localhost:5173`.
  2. The frontend reaches `/api/health` through the proxy.
  3. No secrets or `.env` files are required to start.
- Threats: T8.

### S1-T4 CI and dependency automation

- Owner: `backend-dev`. Branch: `feat/s1-ci` (after T1 and T2 are merged).
- AC:
  1. `.github/workflows/ci.yml` on `push` to `main` and on `pull_request`: job `backend` (uv sync --locked, ruff check, ruff format --check, mypy, pytest, pip-audit) and job `frontend` (npm ci, lint, typecheck, test, build, `npm audit --audit-level=high`).
  2. `.github/workflows/codeql.yml`: languages `python` and `javascript-typescript`, on push, pull request and weekly.
  3. All actions pinned by full SHA from the table above, with a version comment. Top-level `permissions: contents: read`; CodeQL job adds `security-events: write` only.
  4. `.github/dependabot.yml`: ecosystems `uv` (`/backend`), `npm` (`/frontend`), `github-actions` (`/`), `docker` (`/backend`); weekly; `cooldown` with `default-days: 7`.
  5. CI is green on the pull request.
- Threats: T8.

### S1-T5 Reviews, docs and branch protection

- Owner: tech lead with `code-reviewer`, `security-reviewer`, `docs-writer`.
- AC:
  1. Both reviewers approve every Stage 1 pull request.
  2. `CLAUDE.md` "Commands" section and `README.md` "Run locally" section are filled with exact commands.
  3. Branch protection on `main`: pull request required, status checks `backend`, `frontend`, `CodeQL` required. **Customer action** — the tech lead sends exact steps.
  4. `PROGRESS.md` updated; Stage 1 report sent to the customer.
