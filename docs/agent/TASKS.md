# Tasks

Format: one task per block. Goal, owner, branch, acceptance criteria (AC), threats touched (see `docs/security/threat-model.md`).
Check a task only when it is merged to `main` with green CI.

## Stage 0 — Project rules

- [x] S0-T1 Project rules: `CLAUDE.md`, `README.md`, `SECURITY.md`, `LICENSE` (AGPL-3.0-only).
- [x] S0-T2 Threat model and plan: `docs/security/threat-model.md`, `docs/plan.md`.
- [x] S0-T3 ADR 0001–0006.
- [x] S0-T4 Agents: `.claude/agents/*.md`.
- [x] S0-T5a Secret scanning and push protection: enabled (verified through the API).
- [x] S0-T5b **Customer action** (done 2026-10-21) (the session proxy cannot change repository settings): enable private vulnerability reporting, Dependabot alerts and Dependabot security updates in Settings → Security.

## Stage 1 — Scaffold

Pinned GitHub Actions (resolved 2026-10-19, use full SHA with a version comment):

| Action | Version | Commit SHA |
| --- | --- | --- |
| `actions/checkout` | v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| `actions/setup-node` | v7.1.0 | `949feb2413d6458794dcd2491c4babbbce0c15c1` |
| `astral-sh/setup-uv` | v10.3.0 | `1c37ad07a6a961277cf70c0d37d6f313000f5884` |
| `github/codeql-action` (`init`, `analyze`) | v4.39.0 | `6f2ac81f5cd81fe351a197ba0b00d91d03cd2aee` |

### S1-T1 Backend skeleton — merged in PR #1

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

### S1-T1b Backend hardening from review — merged in PR #1

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

### S1-T1c Backend polish from re-review — merged in PR #1

- Owner: `backend-dev`. Tests first: `test-engineer`. Branch: `feat/s1-backend`.
- AC:
  1. **422 without client-chosen keys:** each location keeps its source (`body`, `header`, `query`, `path`) and only names declared by our code (route parameters and model field names) or list indexes; any other part (unknown extra field, dict key) becomes `"*"`; for `extra_forbidden` the last part is dropped. At most 20 entries (deduplicated), then one `"..."` entry. Each part at most 64 characters. Canary tests: canary as an unknown key and as a dict key; 5,000 invalid items give a small body. The docstring matches the real behavior (malformed JSON location).
  2. **Scrubber robustness:** works on a copy of the record (Python 3.12+ filter may return a new `LogRecord`); `getMessage()` errors fall back to `record.msg` plus ` log_format_error=1` with `args=None`; the message is right-stripped before ` exc_type=...` is appended; `logging.raiseExceptions = False` is set when `app.logging_filters` is imported. Tests: mismatched format args with and without `exc_info` neither raise at the call site nor print arguments to stderr.
  3. **Start command guard:** a test asserts the Dockerfile `CMD` contains `--log-config log_config.json`, `--no-access-log`, `--no-proxy-headers` and `--no-server-header`.
- Threats: T1, T3.

### S1-T2 Frontend skeleton — merged in PR #2

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

### S1-T2b Frontend hardening from review — merged in PR #2

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

### S1-T2c Lint follow-ups (next frontend PR) — PR #3

- Owner: `frontend-dev`. Tests first: `test-engineer`.
- AC:
  1. The HTML-sink rule applies to all JS/TS extensions (`js, mjs, cjs, jsx, ts, mts, cts, tsx`); a fixture test with an `.mts` path.
  2. Extra selectors: `srcdoc` assignment; object properties `innerHTML`/`outerHTML`/`srcdoc`/`srcDoc` (covers `Object.assign`); member access to `insertAdjacentHTML`/`createContextualFragment`/`setHTMLUnsafe`/`parseHTMLUnsafe` (covers `.call`); `setAttribute("srcdoc" | "on*", ...)`; `new window.DOMParser()`; `document.write` without depending on `object.name`.
  3. `changeLanguage()` no longer sets `<html lang>` itself (the listener does).
- Threats: T1.

### S2-T0 Lint follow-up (from PR #3 security re-review)

- TS files: string eval through global-object members (`window.eval`, `self.eval`, `self.setInterval("…")`) is reported. Shared browser-globals map for all sources; core `no-implied-eval` on for TS too; ban `x.eval` member access with a T1 message; tests in a `.ts` fixture.
- Optional (code review NIT): `changeLanguage()` before setup uses `setupFallbackI18n()`.
- Policy test (PR #10 security review): no `versions:` in any `dependency-name: "*"` ignore entry in any ecosystem; every wildcard entry has `update-types` without `version-update:semver-patch`.
- Recurring per stage: run `npm outdated` (frontend) and `uv tree --outdated` (backend) and plan major upgrades (TypeScript 7 with typescript-eslint, jsdom 30 with Node ≥ 22.22.2).

### S1-T6 Dependabot tuning after the first Dependabot run

- Owner: `backend-dev`. Tests first: `test-engineer`. Branch: `feat/s1-deps`. Review: `security-reviewer`.
- Context: the first Dependabot run opened #5 (typescript 6 → 7, breaks typescript-eslint), #6 (@types/node 22 → 26, does not match the Node 22 runtime), #7 (jsdom 29 → 30, needs Node ≥ 22.22.2 with `engine-strict`), #8 (uv 0.11 → 0.13: the `ignore` rule used `ghcr.io/astral-sh/uv`, but Dependabot names the dependency `astral-sh/uv`).
- AC:
  1. The uv ignore rule matches the name Dependabot uses (`astral-sh/uv`; keep `ghcr.io/astral-sh/uv` too).
  2. npm: ignore `version-update:semver-major` for all dependencies (`dependency-name: "*"`). Major upgrades are planned changes with their own task.
  3. Policy tests cover 1 and 2.
  4. After merge, the tech lead closes #5–#8 with a comment that explains the policy.
- Threats: T8.

### S1-T3 + S1-T4 delivery note

- Both tasks go into one branch `feat/s1-infra` and one pull request. Owner: `backend-dev`. Tests first: `test-engineer` (policy tests in `backend/tests/test_repo_policy.py`, plain text/regex checks — no new dependency).
- Extra AC for both:
  - Compose: backend `ENVIRONMENT=development`, `ALLOWED_ORIGINS=http://localhost:5173`; `read_only: true`, `tmpfs: /tmp` (noexec, size cap), `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]` on the backend; ports published only on `127.0.0.1` (the Vite dev server is never exposed beyond localhost); frontend runs `npm ci` (with `ignore-scripts`) and `npm run dev`; `VITE_API_PROXY_TARGET=http://backend:8000`.
  - CI also validates Compose (`docker compose config`) and runs a Compose smoke test: frontend proxy reaches `/api/health`.
  - Policy tests: every `uses:` in `.github/workflows/*.yml` is pinned by a 40-hex SHA with a version comment; every workflow has top-level `permissions:` with `contents: read`; no `pull_request_target`; Dockerfile `FROM` lines pinned by `@sha256:` digest (same Python digest in builder and runtime); Dependabot covers `uv`, `npm`, `github-actions`, `docker` with `cooldown`; Compose hardening options above.
  - Digests: the session proxy blocks Docker Hub and ghcr.io. Resolve them in the first CI run (a step that prints `docker buildx imagetools inspect --format '{{json .Manifest.Digest}}'` for both images), then pin them in the same PR.
  - Code-review NITs: comment in `app/api/validation_errors.py` naming the FastAPI internal `Dependant` API and the tests that guard it; docstring adds "request bodies should be Pydantic models" and the non-JSON Content-Type case (`["body"]`).

### S1-T4b Infra hardening from review (PR #4)

- Owner: `backend-dev`. Tests first: `test-engineer` (policy tests). Branch: `feat/s1-infra` (same PR #4).
- Implementation AC:
  1. Remove the `# syntax=` BuildKit frontend directive from `backend/Dockerfile` (unpinned image pulled at build time).
  2. CI non-root check parses the uid part of `Config.User` (`0`, `0:0`, `root`, `root:root` all fail).
  3. Dependabot: `ignore` semver-major and semver-minor updates for the `python`, `node` and `ghcr.io/astral-sh/uv` images (digest and patch updates only); add `docker` for `/frontend` if a frontend dev Dockerfile is added.
  4. Compose frontend runs as the non-root `node` user with `read_only: true`, `tmpfs: /tmp`, named volumes for `node_modules` and the npm cache; a small `frontend/Dockerfile.dev` (digest-pinned node base) prepares directories owned by `node`. Backend gets `mem_limit: 512m`. Compose comment: rebuild after backend changes; WSL2 needs polling for hot reload.
  5. CI polish: drop `-rfE` (keep `-ra` from addopts); pytest annotation fallback `pytest exited with status N`; one `docker compose config --quiet`; `cancel-in-progress` only for pull requests; quiet `curl -fs` inside wait loops; `uv run --locked` after `uv sync --locked`; CodeQL languages add `actions`; OpenTelemetry deny regex also blocks `opentelemetry-distro`, `logfire`, `sentry-sdk`.
  6. Docstring in `app/api/validation_errors.py`: non-JSON body gives `["body"]` with `model_attributes_type` (non-empty) or `missing` (empty); the guarding test id on one line.
- Policy test AC (`backend/tests/test_repo_policy.py`):
  1. Command checks match only inside `run:` blocks; no `continue-on-error` and no `|| true` in the `backend` and `frontend` jobs.
  2. No `${{` at all inside `run:` blocks.
  3. Triggers only `push`, `pull_request`, `schedule` (also `workflow_dispatch` allowed); no `pull_request_target`, no `workflow_run`.
  4. Job-level permissions only `read`/`none`, except `security-events: write` in `codeql.yml`; every `actions/checkout` step has `persist-credentials: false`.
  5. Dockerfiles: no `# syntax=` line unless digest-pinned; every `--from=` value is a stage alias or digest-pinned; every `FROM` digest-pinned (backend and frontend dev Dockerfiles).
  6. Compose: inline `# ...` comments stripped before port parsing; every service: no `privileged`, no `network_mode: host`, no `pid: host`, no `cap_add`, no `docker.sock` mount; every `image:` digest-pinned; frontend runs as a non-root user with `read_only: true`.
  7. Dependabot covers `docker-compose` at `/`; ignore rules exist for python, node and uv.
  8. setup-uv `version:` equals the uv tag in `backend/Dockerfile`.
  9. The OpenTelemetry guard in CI greps `uv.lock` with a deny regex and exits non-zero on a match.
  10. `.env*` files (except `.env.example`) are not tracked by git (`git ls-files`; skip if git is unavailable).
- Threats: T4.6, T8.

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

## Stage 2 — File upload

Design: ADR 0010 (one file per request, raw bytes, no multipart). Threats: T3, T4, T6, T11.

### Limits (initial values; settings on the server, constants in the browser)

| Limit | Value | Enforced by |
| --- | --- | --- |
| File size | 10 MiB (10,485,760 bytes) | browser; server on `/api/extract` |
| Files per contract (main text plus annexes) | 5 | browser; server on the analysis request (stage 9) |
| Contracts per analysis | 5 (free mode: 2, stage 6) | browser; server on the analysis request (stage 9) |
| Total size of one analysis | 50 MiB | browser |
| Pages per document / per analysis | 100 / 300 (free mode: 30 in total) | server, stage 3 |
| JSON request body | 64 KiB | server, every route except `/api/extract` |
| Extractions in progress | 2 per server | server |
| ZIP entries | 2,000 | server |
| Declared uncompressed ZIP size | 100 MiB (the real size is enforced while decompressing, stage 3) | server |
| Compression ratio of one ZIP entry | 200 | server |
| Body read deadline / minimum average rate | 60 s / 32 KiB/s after a 5 s grace period | server (`/api/extract`) |

### API contract: `POST /api/extract` (stage 2; stage 3 adds the extracted text to the `200` response)

Request: the body is the raw bytes of one file. Headers: `Content-Type: application/octet-stream` (media type compared without parameters, case-insensitive) and `Content-Length`. No `Transfer-Encoding`. No file name anywhere.

| Status | Body | When |
| --- | --- | --- |
| 200 | `{"kind": "pdf" \| "docx" \| "text", "bytes": <int>}` | The file is accepted. `bytes` is the number of body bytes received. |
| 400 | `{"error": "length_mismatch"}` | The number of body bytes received differs from `Content-Length`. |
| 408 | `{"error": "upload_timeout"}` | The body is not complete within the deadline, or its average rate falls below the minimum after the grace period. |
| 411 | `{"error": "length_required"}` | No `Content-Length` header, a non-numeric one, or any `Transfer-Encoding` header (also together with `Content-Length`). |
| 413 | `{"error": "file_too_large"}` | `Content-Length` is above the limit (rejected before the body is read), or the body grows above the limit. |
| 415 | `{"error": "unsupported_media_type"}` | Any other `Content-Type`, or none. |
| 422 | `{"error": "empty_file"}` | Zero bytes. |
| 422 | `{"error": "unsupported_type"}` | Not PDF, DOCX or plain text: images, RTF, ODF, XLSX, PPTX, other ZIP files, binary data. |
| 422 | `{"error": "legacy_office_unsupported"}` | OLE2 container: an old `.doc` file or a password-protected Office file. |
| 422 | `{"error": "pages_unsupported"}` | Apple Pages archive. |
| 422 | `{"error": "archive_rejected"}` | A ZIP file fails a structure check. |
| 503 | `{"error": "busy"}` with `Retry-After: 5` | Too many extractions in progress. |

Every other route: a body above 64 KiB gets `413` with `{"error": "request_too_large"}`.

Every response sent before the whole body is read (400, 408, 411, 413, 415, 503) carries `Connection: close`. A `Content-Length` with more than 18 digits counts as too large (413), never as an error. CORS exposes `Retry-After` (`Access-Control-Expose-Headers`), because production is cross-origin.

### Detection rules (`detect_kind`)

1. `%PDF-` at offset 0 → `pdf`.
2. OLE2 signature `D0 CF 11 E0 A1 B1 1A E1` at offset 0 → `legacy_office_unsupported`.
3. `PK\x03\x04` at offset 0 → ZIP checks, in this order. Any failure → `archive_rejected`.
   1. Find the end-of-central-directory (EOCD) record by scanning back over at most the last 65,557 bytes. Its comment must end exactly at the end of the file, and the comment must not contain `PK\x05\x06`, `PK\x06\x06` or `PK\x06\x07` (so the chosen EOCD is the one Python `zipfile` chooses). One disk only. ZIP64 (a ZIP64 locator, or `0xFFFF` / `0xFFFFFFFF` in EOCD fields) is rejected.
   2. Check the entry count from the EOCD against the cap **before** any per-entry work. The central directory must end exactly at the EOCD (`cd_offset + cd_size == eocd_offset`, no gap): `zipfile` locates it as `eocd_offset - cd_size` and ignores `cd_offset`. The number of entries parsed must equal the EOCD entry count.
   3. Every central-directory entry: valid signature; not encrypted (flag bit 0 clear); method 0 (stored) or 8 (deflate); name 1–512 bytes of printable ASCII (0x20–0x7E; OPC part names are ASCII), no backslash, not absolute (no leading `/`, no drive letter `C:`), no `..` or `.` segment, no empty segment (a trailing `/` only for a directory entry of size 0), no segment ending in `.`; the sum of declared uncompressed sizes within the cap; compressed size 0 only when the uncompressed size is 0; uncompressed / compressed ≤ the ratio cap.
   4. No two names that are equal after `casefold()` (OPC part names are case-insensitive; duplicates let different readers see different parts).
   5. Classification by names only: any `Index/*.iwa` → `pages_unsupported`; `[Content_Types].xml` and `_rels/.rels` present and no name under `xl/` or `ppt/` → `docx`; any other ZIP (ODF `mimetype` included) → `unsupported_type`. Stage 3 confirms the main part through relationships (ADR 0009 Layer 0).
   6. Nothing is decompressed in stage 2. `zipfile` may be used only after steps 1 and 2, or not at all.
4. PNG, JPEG, GIF, TIFF, RIFF (WebP) or `{\rtf` signatures → `unsupported_type`.
5. Plain text: a UTF-16 BOM (`FF FE`, `FE FF`) with an even total length → `text` (odd length → `unsupported_type`). Otherwise (a UTF-8 BOM is skipped first), in the first 64 KiB: any NUL byte → `unsupported_type`; more than 1 % C0 control characters other than TAB, LF, CR and FF → `unsupported_type`; else → `text`. This only classifies the file: stage 3 decodes the whole file strictly (UTF-8, UTF-16, CP1251) and runs the control-character rule again on all of the text, failing closed.

Detection is a pure function on bytes in memory. It reads only fixed-size headers and a capped central directory, so its work is linear and bounded; it runs in-process. Stage 3 runs extraction in the parsing subprocess.

### S2-T1 Extract endpoint: upload, limits and type detection

- Owner: `backend-dev`. Tests first: `test-engineer`. Branch: `feat/s2-extract-api` (worktree `/home/claude/wt/s2-extract-api`).
- Public interface (contract between `test-engineer` and `backend-dev`):
  - `app/extraction/detect.py`: `class FileKind(StrEnum)` with `PDF = "pdf"`, `DOCX = "docx"`, `TEXT = "text"`; `class DetectionError(Exception)` with a `code: str` attribute (one of the `422` codes above, never content); `def detect_kind(data: bytes, *, limits: ZipLimits) -> FileKind`; `@dataclass(frozen=True) class ZipLimits` with `max_entries`, `max_uncompressed_bytes`, `max_ratio`.
  - `app/api/extract.py`: router with `POST /api/extract`.
  - `app/extraction/limiter.py`: `class ExtractionLimiter` with `try_acquire() -> bool` and `release() -> None`; the app keeps one instance in `app.state.extraction_limiter`. Tests may take all slots to force `busy`.
  - `app/middleware/body_limit.py`: `BodySizeLimitMiddleware` (pure ASGI).
  - Settings (environment variables, positive integers, validated): `MAX_FILE_BYTES` (10485760), `MAX_JSON_BODY_BYTES` (65536), `MAX_CONCURRENT_EXTRACTIONS` (2), `MAX_ZIP_ENTRIES` (2000), `MAX_ZIP_UNCOMPRESSED_BYTES` (104857600), `MAX_ZIP_RATIO` (200), `EXTRACT_BODY_TIMEOUT_SECONDS` (60), `EXTRACT_MIN_RATE_BYTES_PER_SECOND` (32768; checked after a 5 s grace period).
  - `ExtractionLimiter` also offers a context manager `slot()` (or an equivalent token) that releases exactly once; the handler uses it. `release()` without a held slot raises.
- AC:
  1. `POST /api/extract` follows the API contract table exactly: status codes, JSON bodies, `Retry-After`.
  2. Detection follows the detection rules. Tests build every fixture in memory: a minimal valid DOCX (built with `zipfile`), XLSX-like and PPTX-like archives, an ODF archive, a Pages-like archive, an encrypted entry, ZIP64 markers, trailing data after the EOCD, an entry count above the cap, a declared size above the cap, a ratio above the cap, compressed size 0 with uncompressed size above 0, duplicate names (exact and case-folded), absolute names, `..` names, backslash names, a central directory outside the file, PDF, OLE2, PNG, JPEG, RTF, UTF-8 text, UTF-8 with BOM, UTF-16 LE and BE with BOM, CP1251 bytes (→ `text`), binary with NUL, text with many control characters.
  3. Robustness: random byte strings up to 64 KiB (seeded, at least 2,000 cases) and every truncation of a small valid DOCX either return a `FileKind` or raise `DetectionError`; nothing else is raised. The worst case at the caps (2,000 entries in a 10 MiB file) finishes in under 0.5 s.
  4. Body reading: the handler checks `Content-Length` before it reads; it then reads `request.stream()` into memory and counts bytes; above the limit it stops reading and answers `413`. The limiter slot is taken (without waiting) before the body is read and is released in `finally`, also on errors and on client disconnect.
  5. `BodySizeLimitMiddleware` sits between CORS and the error catcher. It rejects by `Content-Length` before the body is read, and by counting `http.request` chunks. Limits: `MAX_FILE_BYTES` for `/api/extract`, `MAX_JSON_BODY_BYTES` for every other path. A `413` to an allowed origin carries the CORS headers (test).
  6. Never on disk: policy tests fail if `app/` uses `UploadFile`, `request.form`, `tempfile` or `SpooledTemporaryFile`, or if `uv.lock` contains `python-multipart`.
  7. Privacy and logs: a request whose body contains a canary and that carries `Content-Disposition: attachment; filename="<canary>"` and `X-File-Name: <canary>` leaves no canary in captured logs (all loggers, `DEBUG`) or in the response. The access log line stays method, path, status, duration. Error responses carry codes only; `DetectionError` messages never contain input bytes.
  8. CORS: a preflight for `POST /api/extract` with `Content-Type` from an allowed origin succeeds; the allowed headers stay `Content-Type` and `X-Provider-Key`.
  9. CI: the Compose smoke test also sends a small text body through the frontend proxy (`http://localhost:5173/api/extract`) and expects `"kind":"text"`.
  10. ruff, ruff format, mypy strict and pytest are green. No new runtime or dev dependency.
- Review round 1 (PR #15) added to the AC: body deadline and minimum rate (408); `Connection: close` on early responses; `Transfer-Encoding` → 411; `received == Content-Length` (else 400); huge `Content-Length` → 413; `Retry-After` exposed by CORS; body accumulated in one `bytearray` (peak memory for 1-byte chunks below 2.5× the body); ZIP read the same way as `zipfile` (fixtures with a second central directory and with a fake EOCD in the comment are rejected; for valid archives `zipfile` sees the same names); stricter entry names; BOM rules; the handler's own 413 paths tested without the middleware; one `http.response.start` per response; `EXTRACT_PATH` and `declared_length` in a shared module (`app/http_limits.py`); the backend runs as a single worker (the limiter counts per process): policy test that the Dockerfile `CMD` has no `--workers`.
- Threats: T3, T4, T6, T11.

### S2-T2 Upload form in the browser

- Owner: `frontend-dev`. Tests first: `test-engineer`. Branch: `feat/s2-upload-ui` (worktree `/home/claude/wt/s2-upload-ui`).
- Public interface:
  - `src/api/extract.ts`: `type FileKind = "pdf" | "docx" | "text"`; `type ExtractErrorCode` = every server code above plus `"request_too_large" | "network_error" | "timeout" | "aborted" | "unknown_error"`; `type ExtractResult = { ok: true; kind: FileKind; bytes: number } | { ok: false; code: ExtractErrorCode; retryAfterSeconds?: number }`; `function extractFile(file: Blob, options?: { signal?: AbortSignal; fetchImpl?: typeof fetch; timeoutMs?: number }): Promise<ExtractResult>`. It never throws.
  - `src/upload/limits.ts`: `MAX_FILE_BYTES = 10 * 1024 * 1024`, `MAX_FILES_PER_CONTRACT = 5`, `MAX_CONTRACTS = 5`, `MIN_CONTRACTS = 2`, `MAX_TOTAL_BYTES = 50 * 1024 * 1024`, `MAX_PARALLEL_REQUESTS = 2`.
  - `src/upload/state.ts`: pure reducer `uploadReducer(state, action)` and `initialUploadState` (two empty contracts). Actions: `contractAdded`, `contractRemoved { contractId }`, `filesAdded { contractId, files: { id, name, size }[] }`, `fileRemoved { contractId, fileId }`, `fileChecked { fileId, result: ExtractResult }`. File status: `"queued" | "checking" | "accepted" | "rejected"`; client-side rejection codes: `file_too_large`, `too_many_files`, `total_too_large`, `empty_file`, `pages_unsupported`, `legacy_office_unsupported`. Selectors: `contractLabel(index)` (`"A"`…`"E"`), `canAddContract`, `canRemoveContract`, `readiness(state)` → `{ ready: true; contracts: number } | { ready: false; reason: "contract_without_file" | "checking" }`.
  - `src/upload/UploadForm.tsx`: the form component, rendered in `App` after the intro.
- AC:
  1. Contracts: the form starts with "Contract A" and "Contract B". "Add contract" works up to 5 contracts. "Remove contract" is available only when there are more than 2. Labels follow the position (removing B turns C into B).
  2. Adding files: an "Add files" button per contract opens a file picker (`multiple`, `accept=".pdf,.docx,.txt"`). Dropping files on the contract card also adds them. Keyboard users can add files: the button is a real `<button>` that triggers a visually hidden `<input type="file">`.
  3. Client checks before any request: a file above 10 MiB → `file_too_large`; a sixth file in a contract and beyond → `too_many_files`; a file that would push the total above 50 MiB → `total_too_large`; a 0-byte file → `empty_file`; extension `.pages` → `pages_unsupported`; `.doc` → `legacy_office_unsupported`. Rejected files stay in the list with the reason and a "Remove" button. The server's magic-byte check is still the source of truth for every other file.
  4. Server check: every other file is sent with `extractFile`. At most 2 requests are in flight in the whole form; the rest wait as `queued`. `busy` is retried after `Retry-After` (capped at 10 s), at most 3 attempts in total. Timeout 60 s → `timeout`. Network failure → `network_error`.
  5. Request privacy (test intercepts `fetch`): the body is the `File`/`Blob` itself, never `FormData` or a string; the only request header set is `Content-Type: application/octet-stream`; the URL is exactly `/api/extract` with no query string; the file name appears nowhere in the request.
  6. Response handling: a `200` body must have `kind` in the allowed set and `bytes` equal to the file size, otherwise `unknown_error`. An error body `{"error": <string>}` is mapped through an allowlist of codes; anything else → `unknown_error`. Server text is never shown.
  7. Each file row shows: the file name (plain text), the size in localized units, and the status with an icon and a text label ("Waiting", "Checking…", "PDF", "Word document", "Text file", or the rejection reason). An actionable message per error code ("Save the file as .docx or PDF and try again"; for Pages: "Export to PDF: File → Export To → PDF"). Status changes are announced through one `aria-live="polite"` region.
  8. "Remove" on a file aborts its request and frees its slot; removing a contract aborts all its requests. After a removal, focus moves to the contract's "Add files" button.
  9. Readiness line: "Add at least one file to each contract", "Checking files…" or "Ready to compare: N contracts" (from `readiness()`). There is no "Continue" button in stage 2.
  10. Privacy note under the form: files are checked by our server and not stored; file names stay in the browser.
  11. i18n: every new string in `en`, `uk` and `ru` with the same keys; counts use i18next plural forms (`_one`, `_few`, `_many`, `_other` for `uk` and `ru`). `home.status` says that adding contracts works and comparison comes later.
  12. Accessibility: each contract is a `<section>` with a heading; button names include the contract label ("Add files to Contract A"); status uses icon plus text, never color alone.
  13. No new dependency; no HTML sinks; CSP unchanged (`connect-src 'self'` covers `/api/extract`). lint, typecheck, test, build and format checks are green.
- Threats: T1 (HTML sinks), T3, T6, T11 (file names).

### S2-T3 Docs and threat model for stage 2

- Owner: `docs-writer` after S2-T1 and S2-T2 are merged; tech lead checks.
- AC:
  1. Threat model: T4 control 1 shows the limits table above (separate limits for file size, files per contract, contracts per analysis, total size and pages); T10 control 5 says "2 contracts, 30 pages in total"; T6 control 3 names `BodySizeLimitMiddleware` and the extraction limiter; T3 control 1 and T11 control 8 say that uploads are raw bytes with no file name (ADR 0010).
  2. README "How it works" step 1 mentions several files per contract. `CLAUDE.md` Commands section: a `curl` example for `/api/extract` with the expected response.
  3. `PROGRESS.md` updated; stage 2 report sent to the customer.

### S2 follow-ups (from the ADR 0008/0009 design review, for later stages)

- Stage 3 (from the PR #15 security review): before any reader opens a ZIP — every local header at an offset below `cd_offset` with a valid signature, offsets strictly increasing from 0, no overlap and no gap, local name, flags, method, CRC and sizes equal to the central directory (data descriptor handled), real decompressed size enforced while streaming; OPC part-name grammar (ECMA-376 Part 2 §6.2.2: no percent-encoded unreserved characters or `/`) and duplicates checked after canonical decoding; extraction uses only the kind the server detected on the same bytes in the same request.
- Stage 6 / before stage 13: at most 1 extraction slot per client IP (T6 control 7 client-IP rule).
- Stage 3: pdfminer xref warnings, long or looping `Prev` chains (`RecursionError` → `pdf_damaged`) and an unreadable latest revision make the incremental-update warning material; local file header names must match the central directory.
- Stage 3 and 5b: tests on clean UK and RU contracts show no mixed-script and no overlap flags (combining marks excluded).
- Stage 8: model tags that push a topic over its cap are dropped; a topic not analyzed shows 🟡.
- Stage 9: global-override markers; "at most one document per call" policy test.
