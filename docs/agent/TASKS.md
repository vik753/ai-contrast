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

### S1-T1b Backend hardening from review (PR #1)

- Owner: `backend-dev`. Tests first: `test-engineer`. Branch: `feat/s1-backend` (same PR #1).
- AC (from `code-reviewer` and `security-reviewer`):
  1. **Log redaction filter** `app.logging_filters.ExcInfoScrubber` attached to the `stderr` handler in `backend/log_config.json`: for every record it removes `exc_info`, `exc_text` and `stack_info` and appends only the exception type names (recursively for exception groups). Test: `logging.config.dictConfig` with `log_config.json`, then a record whose `exc_info` carries a canary formats without the canary.
  2. **Exception groups:** `ErrorCatcherMiddleware` handles `BaseExceptionGroup` whose leaves are `Exception`s like any other `Exception` (500, generic body, no re-raise). Test with a raw ASGI call and a canary.
  3. **FastAPI telemetry off:** `FastAPI(..., telemetry={"tracing": False, "metrics": False, "logs": False, "operation_spans": False, "auto_configure": False})`. Test asserts the setting.
  4. **Validation errors:** a `RequestValidationError` handler returns `422` with `{"error": "invalid_request", "fields": [<loc as list of strings>]}` — no `input`, `ctx`, `msg` or `url`. Canary test with a test route that has a constrained `X-Provider-Key` header and a constrained JSON body.
  5. **Settings errors hide input:** `hide_input_in_errors=True`; test that `str(ValidationError)` does not contain a marker value.
  6. **Origins:** each `ALLOWED_ORIGINS` entry must be `scheme://host[:port]` with no path, query, fragment, userinfo or wildcard; `null` rejected. In production: `https` only, and `ALLOWED_ORIGINS` must be set explicitly (no localhost default).
  7. **Fail closed:** the Docker runtime stage sets `ENV ENVIRONMENT=production`.
  8. **Access log accuracy:** if the app fails after the response started, the line shows the sent status plus ` aborted=1`; if no response started (cancel or disconnect), the status is `-`. Test with a `StreamingResponse` whose generator raises after the first chunk (canary in the message): no exception reaches the client, the canary is not logged, exactly one `unhandled_exception` line.
  9. Control characters in logged method and path are replaced with U+FFFD instead of `?`.
  10. `app/main.py` docstring shows the full run command with `--log-config log_config.json`.
- Threats: T1, T2, T3, T6, T8.

### S1-T1c Backend polish from re-review (PR #1)

- Owner: `backend-dev`. Tests first: `test-engineer`. Branch: `feat/s1-backend`.
- AC:
  1. **422 without client-chosen keys:** each location keeps its source (`body`, `header`, `query`, `path`) and only names declared by our code (route parameters and model field names) or list indexes; any other part (unknown extra field, dict key) becomes `"*"`; for `extra_forbidden` the last part is dropped. At most 20 entries (deduplicated), then one `"..."` entry. Each part at most 64 characters. Canary tests: canary as an unknown key and as a dict key; 5,000 invalid items give a small body. The docstring matches the real behavior (malformed JSON location).
  2. **Scrubber robustness:** works on a copy of the record (Python 3.12+ filter may return a new `LogRecord`); `getMessage()` errors fall back to `record.msg` plus ` log_format_error=1` with `args=None`; the message is right-stripped before ` exc_type=...` is appended; `logging.raiseExceptions = False` is set when `app.logging_filters` is imported. Tests: mismatched format args with and without `exc_info` neither raise at the call site nor print arguments to stderr.
  3. **Start command guard:** a test asserts the Dockerfile `CMD` contains `--log-config log_config.json`, `--no-access-log`, `--no-proxy-headers` and `--no-server-header`.
- Threats: T1, T3.

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

### S1-T2b Frontend hardening from review (PR #2)

- Owner: `frontend-dev`. Tests first: `test-engineer`. Branch: `feat/s1-frontend` (same PR #2).
- AC (from `code-reviewer` and `security-reviewer`):
  1. **Raw HTML sinks banned by lint** (`no-restricted-syntax`, each entry with a message citing T1): JSX attribute `dangerouslySetInnerHTML`; object property `dangerouslySetInnerHTML` (identifier or string key); member access `.dangerouslySetInnerHTML`; property `__html`; assignment to `innerHTML` / `outerHTML`; calls to `insertAdjacentHTML`, `createContextualFragment`, `setHTMLUnsafe`, `parseHTMLUnsafe`; `document.write` / `document.writeln`; `new DOMParser()`; JSX attribute `srcDoc` / `srcdoc`. One lint test case per sink, plus a clean component with no errors.
  2. **No inline disabling:** `linterOptions.noInlineConfig: true`. Test: a `// eslint-disable-next-line no-restricted-syntax` comment does not hide the error.
  3. **No install scripts:** `.npmrc` has `ignore-scripts=true`; `npm ci`, `npm run build` and `npm test` still pass from a clean `node_modules`.
  4. **Exact CSP assertions:** `script-src` is exactly `'self' 'wasm-unsafe-eval'`; `worker-src` is exactly `'self' blob:`; `frame-src 'none'`; `upgrade-insecure-requests`; headers `Cross-Origin-Resource-Policy: same-origin` and `X-Frame-Options: DENY` present.
  5. **Trusted Types:** CSP adds `require-trusted-types-for 'script'; trusted-types 'none'`. The tech lead verifies the built app in Chromium with the headers applied (no `securitypolicyviolation`).
  6. **Proxy (AC9 of S1-T2) tested:** `vite.config.ts` `server.proxy["/api"].target` is `http://localhost:8000` by default and follows `VITE_API_PROXY_TARGET`.
  7. **`<html lang>` follows every change:** a `languageChanged` listener registered once in `setupI18n()`; a direct `i18next.changeLanguage("uk")` call also updates `<html lang>`.
  8. **Resilient start:** if `setupI18n()` rejects, the app still renders in English.
  9. **Types:** `tsconfig.test.json` includes `src/**/*.d.ts`; `tsconfig.app.json` excludes `src/__lint_fixture__.tsx`.
  10. **npm version:** `package.json` has `"packageManager": "npm@11.6.2"`; no `engines.npm`. `PROGRESS.md` records the npm 10 crash.
  11. **Forced colors:** the active language button has a non-color marker (for example an underline or border) and a `forced-colors: active` style.
  12. **Hard-coded strings check** compares whole strings (exact text node match or explicitly allowed interpolations), not substrings.
  13. **Copy (ADR 0007):** `home.byok` describes both paths in all three languages — start free with the built-in model, or connect your own provider key; contract text goes only to the AI provider that processes it.
- Threats: T1, T8, T9.

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
  6. Docker base images pinned by digest (`python:3.13-slim@sha256:...` — the same digest in builder and runtime; `ghcr.io/astral-sh/uv:<version>@sha256:...`). CI job `docker` builds the backend image on every pull request and smoke-tests `/api/health` in a container.
  7. pip-audit in CI uses the PyPI and OSV sources. CI fails if `uv.lock` contains `opentelemetry-sdk` or `opentelemetry-exporter-*`.
  8. Note: `package-lock.json` was generated with npm 11 because npm 10 crashed on this tree; `npm ci` works with npm 10. Use npm 11 in CI if a regeneration is needed.
  5. CI is green on the pull request.
- Threats: T8.

### S1-T5 Reviews, docs and branch protection

- Owner: tech lead with `code-reviewer`, `security-reviewer`, `docs-writer`.
- AC:
  1. Both reviewers approve every Stage 1 pull request.
  2. `CLAUDE.md` "Commands" section and `README.md` "Run locally" section are filled with exact commands.
  3. Branch protection on `main`: pull request required, status checks `backend`, `frontend`, `CodeQL` required. **Customer action** — the tech lead sends exact steps.
  4. `PROGRESS.md` updated; Stage 1 report sent to the customer.
