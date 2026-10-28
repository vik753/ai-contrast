# Tasks archive

Finished stages, moved from `docs/agent/TASKS.md` to keep the working file short.

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

- Status: **merged** (PR #15).
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

- Status: **merged** (PR #16).
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
- Review round 1 (PR #16) added to the AC:
  - `extractFile` accepts `400 length_mismatch` and `408 upload_timeout` (PR #15 contract); every server code only together with its status; the response body is read up to 4 KiB (`Content-Length` above it, or more streamed bytes → abort and `unknown_error`); a non-JSON `Content-Type` → `unknown_error`; tests pin `credentials: "omit"`, `redirect: "error"`, `cache: "no-store"` and no `keepalive` / `referrer`.
  - i18n sets `skipOnVariables: true` explicitly; a file name such as `$t(upload.title) {{label}}` appears word for word in the row, the Remove label and the live region. File names are wrapped in `<bdi>`.
  - Readiness: `readiness()` adds the reason `rejected_files` ("Remove the files that were not accepted"); order: `checking` → `rejected_files` → `contract_without_file` → ready.
  - Scheduler in a hook `useCheckScheduler(state, dispatch, check)`; when its effect starts again, `checking` files without a request in flight go back to `queued`; files rejected by the client keep no `File` reference.
  - Focus: after adding a contract, focus moves to the new contract's "Add files" button; after removing a contract, to "Add contract"; a focus target is applied only if the item exists. The queued → checking step is not announced.
  - Live region is cleared on a language change. "Files added" announcement uses plural forms.
  - Sizes round up (`10,485,761` bytes shows as "10.1 MB"); "MB" means 1024² (comment in `limits.ts` and `format.ts`); limits in messages are interpolated from `limits.ts`, never written into the strings.
  - Wording fixes in uk/ru from the code review.
- Threats: T1 (HTML sinks), T3, T6, T11 (file names).

### S2-T3 Docs and threat model for stage 2

- Status: **merged** (this PR).
- Owner: `docs-writer` after S2-T1 and S2-T2 are merged; tech lead checks.
- AC:
  1. Threat model: T4 control 1 shows the limits table above (separate limits for file size, files per contract, contracts per analysis, total size and pages); T10 control 5 says "2 contracts, 30 pages in total"; T6 control 3 names `BodySizeLimitMiddleware` and the extraction limiter; T3 control 1 and T11 control 8 say that uploads are raw bytes with no file name (ADR 0010).
  2. README "How it works" step 1 mentions several files per contract. `CLAUDE.md` Commands section: a `curl` example for `/api/extract` with the expected response.
  3. `PROGRESS.md` updated; stage 2 report sent to the customer.

### S2 follow-ups done in stage 3 (from the ADR 0008/0009 design review)

- Stage 3 (from the PR #15 security review): before any reader opens a ZIP — every local header at an offset below `cd_offset` with a valid signature, offsets strictly increasing from 0, no overlap and no gap, local name, flags, method, CRC and sizes equal to the central directory (data descriptor handled), real decompressed size enforced while streaming; OPC part-name grammar (ECMA-376 Part 2 §6.2.2: no percent-encoded unreserved characters or `/`) and duplicates checked after canonical decoding; extraction uses only the kind the server detected on the same bytes in the same request. (Done in S3-T2, AC 1 and 2.)
- Stage 3: pdfminer xref warnings, long or looping `Prev` chains (`RecursionError` → `pdf_damaged`) and an unreadable latest revision make the incremental-update warning material; local file header names must match the central directory. (Done in S3-T3 and S3-T2.)

## Stage 3 — Text extraction

Design: ADR 0011 (parsing sandbox), ADR 0009 Layer 0 (read what the person reads), ADR 0004 revision. Threats: T3, T4, T5, T6, T11.

Order: S3-T1 first (sandbox and response contract). Then S3-T2 (DOCX) and S3-T3 (PDF), one after the other (both change `uv.lock`). S3-T4 (preview UI) can start after S3-T1. S3-T5 (browser OCR) after S3-T3. S3-T6 (Google Docs link) last. Detailed AC for S3-T2…T6 are written when each task starts.

### Stage 3 dependencies (approved by `security-reviewer`, 2026-10-21)

| Package | Version | Conditions |
| --- | --- | --- |
| `defusedxml` | 0.7.1 | `forbid_dtd=True`; any DTD → `suspicious_package`. |
| `pdfminer.six` | 20260107 (adds `cryptography` 50.0.2, `cffi`, `pycparser`) | CMaps as JSON only (this version); `CMAP_PATH` unset; `pdfminer` logger at ERROR (messages contain PDF data); encrypted PDFs opened only when the empty user password works, otherwise "Not read" / `encrypted_unsupported`. |
| `pdfjs-dist` | 6.4.299 (not ≤ 4.1.392: CVE-2024-4367; not 5.6.83–6.2.107: CVE-2026-16633) | Same-origin `workerPort`; `enableXfa: false`, `disableFontFace: true`, `useSystemFonts: false`; self-hosted cMap, font, wasm and ICC URLs; no text or annotation layer; do not ship `quickjs-eval.*` or `pdf.sandbox`; render with `AnnotationMode.ENABLE` so OCR reads form values. |
| `tesseract.js`, `tesseract.js-core` | 7.0.0 both, pinned exactly | `workerBlobURL: false`, `cacheMethod: 'none'`, LSTM only (ship only `*-lstm.wasm.js`); input only canvas or ImageData, never URL strings. |
| `@tesseract.js-data/{eng,ukr,rus}` | 1.0.0, copy only `4.0.0_best_int` | SHA-256 manifest test: eng `45b4cb346724ac1774f1c36f42f182b887bcdb28ebe63e6fff90ac41f3fcff91`, ukr `ea2789a0ad99ff84bfd252a7410a1e8661a7bc5acaa41573d23b54b71446aa4c`, rus `f51f5edc992249ff9b70a227b22f242dfa47b2b1bbc7ae0ea74908640c101f6a`. |
| `httpx` | 0.28.1 as a runtime dependency (already locked as a dev dependency with `httpcore` 1.0.9, `h11`, `anyio`, `certifi`, `idna`) | Approved 2026-10-22 (S3-T6, ADR 0012). Only in `app/net/`; guarded network backend; `trust_env=False`, `follow_redirects=False`, `retries=0`, HTTP/1.1 only; new client per request; no `h2`, no `socksio`; loggers `httpx` and `httpcore` at `WARNING`; any version change of `httpx`, `httpcore` or `h11` needs a security review. |

CSP (S3-T5): no `'unsafe-eval'`; remove `blob:` from `worker-src`; Trusted Types `default` policy with `createScriptURL` only and an exact URL allowlist; the OCR worker uses our classic wrapper that sets the same policy before `importScripts`.
Doc updates with S3-T2/T3/T5: T9 (no `isEvalSupported`, exact-URL policy, no `blob:`), T4 (encrypted PDF rule, pdfminer logging), T8 (language-data hash manifest), ADR 0004 title and `CLAUDE.md` architecture row (no pdfplumber, no python-docx).

### Response contract: `POST /api/extract` `200` from stage 3

```json
{
  "kind": "pdf" | "docx" | "text",
  "bytes": 12345,
  "language": "uk" | "ru" | "en" | "mixed" | "unknown",
  "pages": 3,
  "blocks": [{ "text": "…", "part": "body" | "footnote" | "endnote" | "header" | "footer" | "textbox", "page": 1 }],
  "ocr_pages": [2],
  "removed": [{ "reason": "<code>", "count": 4, "sample": "…" }],
  "warnings": [{ "code": "<code>", "page": 2 }]
}
```

- `pages` and `page` are `null` for DOCX and text. `ocr_pages` lists PDF pages with no text layer that the browser must OCR (stage 3, S3-T5); it is empty for other kinds.
- `removed` lists text that was dropped as provably invisible, by reason, with a short sample (at most 200 characters) for the preview. `warnings` use codes only (plus a page number).
- Every list and the total text have caps; a cap fails closed with an error code, never a truncated result.
- New error codes (`422` unless noted): `extraction_failed`, `extraction_timeout`, `too_many_pages`, `too_much_text`, `encrypted_unsupported`, `no_text_extracted`, `text_decoding_failed`, `suspicious_package`, `docx_strict_unsupported`, `pdf_damaged`.

### S3-T1 Parsing sandbox, response contract and plain text

- Owner: `backend-dev`. Tests first: `test-engineer`. Branch: `feat/s3-sandbox` (worktree `/home/claude/wt/s3-sandbox`).
- Public interface:
  - `app/extraction/sandbox.py`: `async def run_extraction(data: bytes, kind: FileKind, *, limits: SandboxLimits) -> ExtractionResult` (raises `ExtractionError(code)`); `@dataclass(frozen=True) class SandboxLimits` (`memory_bytes`, `cpu_seconds`, `wall_seconds`, `max_result_bytes`).
  - `app/extraction/worker.py`: the child entry point (started with the `-I -c` bootstrap of ADR 0011); `app/extraction/text.py`: `extract_text_file(data: bytes) -> ExtractionResult` (pure, runs inside the child).
  - `app/extraction/model.py`: Pydantic models for the response contract above (`ExtractionResult`, `Block`, `Removed`, `Warning`), strict, `extra="forbid"`.
  - Settings: `EXTRACT_WORKER_MEMORY_MB` (192), `EXTRACT_WORKER_CPU_SECONDS` (20), `EXTRACT_WORKER_WALL_SECONDS` (30), `EXTRACT_MAX_RESULT_BYTES` (4 MiB), `EXTRACT_MAX_TEXT_CHARS` (1,000,000), `EXTRACT_MAX_BLOCKS` (20,000).
- AC:
  1. ADR 0011: one subprocess per file; limits set by the child before it reads input (`RLIMIT_AS`, `RLIMIT_CPU`, `RLIMIT_FSIZE` = 0, `RLIMIT_NOFILE`, `RLIMIT_CORE` = 0); minimal environment; `-I`; stderr read and discarded, never logged.
  2. The parent kills the child on the wall deadline (`extraction_timeout`), on a non-zero exit or a signal (`extraction_failed`; memory or CPU limit included), and on a result above `EXTRACT_MAX_RESULT_BYTES` (`extraction_failed`, reading stops at the cap). No zombie processes remain (test). The extraction slot is held while the child runs.
  3. The child result is validated by the Pydantic model in the parent; invalid JSON or schema → `extraction_failed`.
  4. Plain text: strict UTF-8 (BOM optional), strict UTF-16 with BOM, otherwise strict CP1251; failure → `text_decoding_failed`. The control-character rule of detection runs again on the whole decoded text (fail closed). Newlines normalized to `\n`. Text is split into blocks by blank lines. `part` = `body`.
  5. Language: rule-based, no dependency: Ukrainian-only letters (і, ї, є, ґ) vs Russian-only letters (ы, э, ъ, ё) vs Latin share; `mixed` when two languages are both significant, `unknown` for too little text. Thresholds documented and tested with en/uk/ru samples.
  6. Caps: total characters above `EXTRACT_MAX_TEXT_CHARS` → `too_much_text`; blocks above `EXTRACT_MAX_BLOCKS` → `too_much_text`; zero characters after decoding → `no_text_extracted`.
  7. `POST /api/extract` returns the stage 3 contract for `text`. For `pdf` and `docx` it returns `501 {"error": "not_implemented"}` until S3-T2/S3-T3 (temporary; removed by those tasks).
  8. Robustness tests in the child: a test-only kind or hook that allocates memory beyond the limit, burns CPU, sleeps past the wall deadline, writes huge output, exits non-zero, and tries to write a file → each gives the right code; the server keeps working and the slot is free.
  9. Memory budget measured and written in ADR 0011: parent RSS plus two children at their limit stays under 512 MB.
  10. Logs: only the error code and duration; no child output, no text. Log canary test with a canary inside the text file.
  11. No new dependency. ruff, mypy strict, pytest green.
- Review round 1 (PR #20) added to the AC:
  - The extraction slot is held until the last response byte is sent (a response class that releases the slot in `finally`), with a send deadline `EXTRACT_SEND_TIMEOUT_SECONDS` (30): a client that does not read is cut off and the slot is freed. The Dockerfile `CMD` has `--limit-concurrency 32` (policy test). Caps lowered: result 4 MiB, text 1,000,000 characters. The memory budget is measured again with two results at the cap made of non-BMP characters and written in ADR 0011.
  - The child sets `RLIMIT_NPROC` = 0 (no `fork`; the container user is not root); a test checks that `fork` fails in the child (skipped when the tests run as root).
  - Plain text: control characters (Cc) other than TAB and LF are removed and counted in `removed` (reason `control_characters`); NEL (U+0085), LS (U+2028) and PS (U+2029) become `\n`.
  - Starting the child can fail (`OSError`) → `extraction_failed`, no traceback. The parent waits for the process and drains the pipes together (no hang on Python 3.13.0). The app root is appended to `sys.path`, not inserted first.
- Threats: T3, T4, T6.

- S3-T1 follow-up (security delta review, PR #20): in plain text, form feed (FF) and vertical tab (VT) become `\n` instead of being removed (words must not run together) — do it in S3-T2 with the shared text normalization.
- Server list caps to match the browser (S3-T4): `removed` ≤ 1,000 items, `warnings` ≤ 1,000 items, `pages` ≤ 100, `ocr_pages` strictly increasing, warning pages strictly increasing per warning code — add to the result model in S3-T2 or S3-T3.
- Stage 13 blockers: header-read timeout / slowloris with `--limit-concurrency 32`, and kernel send buffers of cut-off connections (threat model T6 control 9). (Still open: see "Open follow-ups" in `TASKS.md`.)

### S3-T2 DOCX extraction

- Owner: `backend-dev`. Tests first: `test-engineer`. Branch: `feat/s3-docx` (worktree `/home/claude/wt/s3-docx`). New dependency: `defusedxml==0.7.1` (approved, conditions above).
- Public interface: `app/extraction/docx.py`: `extract_docx(data: bytes, *, max_chars: int, max_blocks: int, limits: DocxLimits) -> ExtractionResult` (runs inside the child); `@dataclass(frozen=True) class DocxLimits` (`max_part_bytes`, `max_total_bytes`, `max_xml_depth`, `max_elements`). Settings: `MAX_DOCX_PART_BYTES` (32 MiB), `MAX_DOCX_XML_DEPTH` (256), `MAX_DOCX_ELEMENTS` (2,000,000); the total uses `MAX_ZIP_UNCOMPRESSED_BYTES`.
- AC:
  1. **ZIP, before any reader opens a part:** every local header has a valid signature at an offset below `cd_offset`; offsets strictly increase from 0; entries do not overlap and leave no gap (local header + name + extra + compressed data + optional data descriptor ends where the next begins; the last ends at `cd_offset`); local name, flags, method, CRC and sizes equal the central directory (data descriptor handled). Real decompressed size enforced while streaming, CRC checked. Any failure → `archive_rejected`.
  2. **OPC part names** (ECMA-376 Part 2 §6.2.2): percent-encoded unreserved characters or `/` → `archive_rejected`; duplicates compared after percent-decoding and `casefold()`.
  3. **Package (ADR 0009 Layer 0):** `[Content_Types].xml` and every `.rels` parsed with `defusedxml`, `forbid_dtd=True`; any DTD → `suspicious_package`. Exactly one `officeDocument` relationship in `_rels/.rels` (the strict OOXML relationship type or namespaces → `docx_strict_unsupported`); its target is internal and its content type is `wordprocessingml.document.main+xml` (macro-enabled or template types → `unsupported_type`); a `word/document.xml` that exists but is not the target, more than one `officeDocument` relationship, or a target outside the package → `suspicious_package`. Footnotes, endnotes, headers and footers come only from the main part's relationships.
  4. **Walker** (streaming, `iterparse`, elements cleared; depth and element caps → `suspicious_package`): `w:t`; `w:tab` → TAB; `w:br`, `w:cr` → `\n`; one block per paragraph; `w:ins` and `w:moveTo` included, `w:del` and `w:moveFrom` excluded; `w:sdtContent` (inline and block); `w:txbxContent` with `mc:AlternateContent` read once (`mc:Choice` when its `Requires` namespaces are known, else `mc:Fallback`); `w:fldSimple` and complex field results (between `separate` and `end`; field codes excluded); `w:smartTag`, `w:customXml`; `w:noBreakHyphen` → `-`, `w:softHyphen` dropped. `part`: `body`, `footnote`, `endnote`, `header`, `footer`, `textbox`. Header and footer lines that hold only a page number or repeat across header parts are dropped with a count.
  5. **Hidden text by effective formatting** (docDefaults → paragraph style with `basedOn` chain (cycle guard) → character style → direct `w:rPr`): `w:vanish`, `w:specVanish`, `w:webHidden` → removed (`hidden_formatting`); white text on no or white shading, or text colour equal to the shading fill → removed (`same_color`); `w:sz` ≤ 2 half-points or `w:w` < 20 % → removed (`tiny_text`); `w:sz` ≤ 8 half-points, near-white colour, negative `w:spacing` or `w:position` → kept, warning `borderline_text`. Removed text goes to `removed` with a sample.
  6. **Symbols:** `w:sym` with Wingdings/Symbol checkbox codes (F0FE, F0FD, F0A8, F06F, F078) → ☒, ☑, ☐; `w14:checkbox` content controls → ☐/☒ by `w14:checked`.
  7. **"Not read" (material):** `w:altChunk`, OLE objects (`w:object`, `o:OLEObject`), external `w:subDoc` → warnings `not_read_altchunk`, `not_read_object`, `not_read_subdocument`.
  8. **Text normalization** shared with plain text: FF and VT → `\n` (S3-T1 follow-up); Cc rule of S3-T1.
  9. Language detection; `pages` and `page` null; zero text → `no_text_extracted`; caps of S3-T1.
  10. Fixtures built in tests (`zipfile` + XML strings), synthetic text only. A worst-case DOCX at the caps finishes inside the child limits.
  11. Docs: threat model T4 (DTD rule), ADR 0004 title and `CLAUDE.md` architecture row (no pdfplumber, no python-docx).
- Review round 0 (tech lead, before code review) added to the AC:
  - **Toggle properties** (ECMA-376 §17.7.3): `w:vanish` and the other toggle properties XOR across the style hierarchy (table style, paragraph style, character style); direct formatting sets the value. Replaces the plain-override rule.
  - **Only displayed parts are read.** Headers and footers: the default ones; first-page ones only with `w:titlePg` in that section; even-page ones only with `w:evenAndOddHeaders` in `settings.xml`. Footnotes and endnotes: only those referenced from the read parts; separator and continuation notes excluded. Not displayed parts go to `removed` (reason `not_displayed`).
  - Server list caps matching the browser: `removed` ≤ 1,000, `warnings` ≤ 1,000 (overflow → `too_much_text`); `removed.count` counts characters.
- Review round 1 (PR #26) added to the AC. Principle: remove text only when its invisibility is resolved exactly; when an input cannot be resolved, keep the text and add `borderline_text`.
  1. **Colour and background:** text colour from `w:val` or `w:themeColor` resolved through the theme part, `w:clrSchemeMapping`, `w:themeTint` / `w:themeShade`; `auto` is never same-colour. Background: run shading → paragraph shading → table cell `tcPr/w:shd` → table style (default table style included); a table style with conditional formatting (`w:tblStylePr`) → borderline, not removed. Page background only with `w:displayBackgroundShape`. Runs with `w:cs` or `w:rtl` use `w:szCs`. Size values with units (`1pt`) are parsed.
  2. **Markup compatibility:** `mc:Choice Requires` allowlist of the namespaces Word supports (`wps`, `wpg`, `wpc`, `wpi`, `w14`, `w15`, `w16`, `w16se`, `w16cid`, `w16cex`, `w16du`, `w16sdtdh`, `a14`); an unknown `Requires` → `suspicious_package`. Elements in an `mc:Ignorable` namespace we do not know are skipped; if they contain text (`w:t`) → `suspicious_package`.
  3. **Content controls:** `w:dataBinding` → text kept plus material warning `not_read_data_binding`. Checkbox controls output the state symbol and all other runs; no symbol when the control is hidden.
  4. **Hidden objects:** a `w:drawing`, `w:pict` or `w:object` inside a hidden run is removed with the run's reason. VML `visibility:hidden` and DrawingML `docPr hidden="1"` → removed (`hidden_object`). Table rows deleted with tracked changes (`w:trPr/w:del`) are excluded like `w:del`. Duplicate note ids or duplicate relationship ids → `suspicious_package`.
  5. **Shown content we cannot read:** legacy form fields output their state (checkbox ☐/☒, dropdown selected entry); `w:sym` with the Symbol font is mapped by a table, other unmapped symbols → material warning `not_read_symbol`; SmartArt, charts and WordArt (`v:textpath`) → material warnings `not_read_diagram`, `not_read_chart`, `not_read_wordart`.
  6. `w:webHidden` is visible in print layout: not removed. Fields with `w:dirty` or document `w:updateFields` → warning `field_may_update` (not material).
  7. Code quality: `iterparse` detaches cleared elements (peak memory test); hidden and not-displayed text is collected with a character cap (sample head only); `docx.py` split (`docx_styles.py`, new `docx_package.py`); one source for cap defaults; the repeat filter works per header/footer kind across parts (documented).
  8. Follow-up task **S3-T2b — list numbering labels** (before stage 5): render `w:numPr` labels from `numbering.xml` (`lvlText`, `numFmt`, start, restart, overrides), because clause numbers are often automatic.
  9. Threat model T5 residual risks for DOCX: layout-dependent headers and footers, text-box overflow and off-page anchors, field updates on open, data binding, markup compatibility.
- Threats: T4, T5, T11.

### S3-T3 PDF extraction

- Owner: `backend-dev`. Tests first: `test-engineer`. Branch: `feat/s3-pdf` (worktree `/home/claude/wt/s3-pdf`). New dependency: `pdfminer.six==20260107` (approved, conditions in "Stage 3 dependencies"; it adds `cryptography`, `cffi`, `pycparser`). No pdfplumber.
- Public interface: `app/extraction/pdf.py`: `extract_pdf(data: bytes, *, max_chars: int, max_blocks: int, limits: PdfLimits) -> ExtractionResult` (runs inside the child); `@dataclass(frozen=True) class PdfLimits` (`max_pages`, `max_prev_chain`). Settings: `MAX_PDF_PAGES` (100), `MAX_PDF_PREV_CHAIN` (32).
- AC:
  1. In the child: the `pdfminer` logger at ERROR (its messages contain PDF data); `CMAP_PATH` unset; logs never contain PDF content.
  2. Encrypted PDF: opened only when the empty user password works; otherwise `encrypted_unsupported`.
  3. Page count checked before extraction: above `MAX_PDF_PAGES` → `too_many_pages`.
  4. A custom pdfminer device records per glyph: text, size, render mode (`Tr`), fill colour with its colour space, alpha (`ca` from ExtGState when present), box, and the page crop box.
  5. **Provably invisible text removed** and reported in `removed`: render mode 3 or 7 (`invisible_render_mode`); fully outside the crop box (`outside_page`); glyph height or width under 1 pt (`tiny_text`); exact white fill on a page without filled shapes behind the text (Gray 1, RGB 1/1/1, CMYK 0/0/0/0) (`same_color`); alpha 0 (`transparent`).
  6. **Borderline kept** with `borderline_text`: near-white colours (luminance above 0.9), size 1–4 pt, text over a filled shape whose colour we cannot compare.
  7. **Overlap:** NFC first, combining marks (Mn) excluded; identical glyphs at the same position merged (fake bold); different characters overlapping by more than half → kept, warning `overlapping_text`.
  8. **Blocks:** lines grouped into paragraphs per page (pdfminer layout), `part` = `body`, `page` = 1-based. Running headers and footers: a line repeated at the top or bottom of at least half of the pages is kept once (`removed` reason `repeated_header_footer` for the rest); page-number-only lines dropped (`page_number`).
  9. **Scans:** a page with no text and with images → in `ocr_pages`; a document where every page is like this returns `200` with all pages in `ocr_pages` (not `no_text_extracted`). A page with little text and a large image area → material warning `not_read_image_page`, except the signature page rule (each image under 15 % of the page area and together under 30 %).
  10. **Annotations and forms:** FreeText, Text and Widget annotations with a non-empty value → material warning `not_read_annotation` (Link ignored); XFA forms → `not_read_xfa`.
  11. **Damage and revisions:** cross-reference reconstruction (pdfminer fallback) or any pdfminer parse warning → material warning `damaged_pdf`; more than one revision → warning `pdf_edited` (not material); a `Prev` chain longer than `MAX_PDF_PREV_CHAIN`, a loop, or a `RecursionError` → `pdf_damaged`; the latest revision unreadable → `pdf_damaged`.
  12. **References to documents not provided** (all kinds: text, DOCX, PDF; shared post-processing): EN/UK/RU patterns ("згідно з Правилами страхування", "відповідно до Правил", "согласно Правилам", "General Terms and Conditions", "incorporated by reference", "є невід'ємною частиною", "является неотъемлемой частью") → warning `external_reference` with the page (null for DOCX and text).
  13. List caps as for DOCX; `pages` = page count; shared normalization and Cc rule.
  14. Fixtures: a small PDF builder in tests (raw PDF objects, standard Type1 fonts for Latin text, a Type0/Identity-H font with a ToUnicode CMap for Cyrillic; no new test dependency). Worst case at the caps (100 pages, dense text) inside the child limits.
  15. Docs: threat model T4 (encrypted-PDF rule, pdfminer logging rule), ADR 0004 aligned.
- Tech lead decisions (implementation round): the `pdfminer` logger stays at ERROR (AC1 wins over AC11's "any parse warning"); `damaged_pdf` comes from our own checks (xref reconstruction, counted ERROR records that are never written, unreadable listed objects → `pdf_damaged`). Thresholds: header/footer band 8 % of the page height; "little text" under 200 characters; an OCR page needs images over at least 1 % of the page. Form XObjects inherit the graphics state; blend modes and soft masks turn white-text removal into `borderline_text`.
- Review round 1 (PR #29) added to the AC. Principle: remove only when invisibility is exact; otherwise keep + `borderline_text`; content we cannot render → material warning.
  1. **Content pdfminer does not run:** any visible annotation (not Link or Popup, not Hidden or NoView) with an `/AP /N` appearance → material `not_read_annotation`; tiling patterns with text operators → material `not_read_pattern`; Type3 fonts without ToUnicode → material `not_read_type3`; Form XObjects without `BBox` are run without a clip; `/Font` set through ExtGState is honoured.
  2. **Colour spaces:** CalGray, CalRGB, Lab and ICCBased (by component count) resolved where exact; Indexed through its lookup table; Separation and DeviceN with tint 0 = no ink (white); any other unresolved colour (Pattern included) → borderline. Alpha below 0.2 (but above 0) → borderline. A render mode outside 0–7 → borderline.
  3. **Revisions:** an object that is free in a newer cross-reference section but in use in an older one, or a generation mismatch → `pdf_damaged`.
  4. **Encryption:** only the empty user password is tried; the owner-password fallback is disabled (test: non-empty user + empty owner → `encrypted_unsupported`).
  5. **Backgrounds and sizes:** stroked paths and `sh` shadings count as possible backgrounds; light text on a known fill with a small luminance difference → borderline; Type3 glyph size measured through `FontMatrix`.
  6. Text behind a zero-area clip, outside a form `BBox`, or in an optional content group that is OFF → borderline.
  7. Code review: tests for every tech-lead decision and cap (Form XObject graphics state, blend/soft mask, counted ERROR records, lost-trailer repair, `/XRefStm` loop guard, linearized revision count, hidden/NoView annotations, widget value from a parent field, `MAX_FILLS`, `MAX_CELL_GLYPHS`, `MAX_FLOW_BOXES`, `MAX_ANNOTATIONS`, every UK/RU/EN reference phrase); OCR decision after header/footer removal; result model checks `pages` ≤ 100 and `block.page` ≤ `pages`; references found across two adjacent blocks; small dataclass instead of `list[str | int]` records; NITs.
  8. Threat model: T4 (free-entry rule, owner-password rule); T5 residual risks (Type3 CharProcs, transfer functions, overprint).
- Stage 13 follow-up: measure the 100-page worst case on Render's CPU (9.3 s CPU here); lower `MAX_PDF_PAGES` or raise the wall limit if it exceeds 30 s. (Still open: see "Open follow-ups" in `TASKS.md`.)
- Threats: T4, T5.

### S3-T2b List numbering labels (before stage 5)

- Owner: `backend-dev`. Tests first: `test-engineer`. Branch: `feat/s3-numbering`.
- AC: paragraphs with `w:numPr` (direct or from the style) get their label from `numbering.xml`: `w:abstractNum` levels with `lvlText` (`%1.%2.`), `numFmt` (decimal, lowerLetter, upperLetter, lowerRoman, upperRoman, bullet, `decimalZero`, Cyrillic `russianLower`/`russianUpper` and Ukrainian equivalents where defined), `start`, `lvlRestart`, `isLgl`, `w:num` overrides (`lvlOverride`, `startOverride`); counters per `numId` in document order, hidden and deleted paragraphs do not count; the label is prefixed to the block text with one space. Unknown formats → decimal plus warning `numbering_approximate`. Caps on levels (9) and definitions.
- Threats: T5 (labels are what the person reads; clause references depend on them).
- Review round 1 (PR #31) added to the AC:
  1. **Label visibility:** the label goes through the same visibility check as text, with run properties merged in this order: paragraph style, paragraph mark (`w:pPr/w:rPr`), level (`w:lvl/w:rPr`). A hidden label is not emitted; its text goes to `removed`.
  2. **Counting follows the paragraph mark:** a numbered paragraph counts unless its mark is hidden or deleted (`w:pPr/w:rPr/w:vanish` by effective formatting, `w:pPr/w:rPr/w:del`), whatever its runs contain.
  3. **Level from the style:** a paragraph whose style gives `numId` without `ilvl` takes the level whose `w:lvl/w:pStyle` names that style (legal templates link headings this way).
  4. **Caps:** `lvlText` at most 255 characters and an expanded label at most 256 characters; above → `suspicious_package`. Duplicate `abstractNumId` or `numId` → `suspicious_package`.
  5. **Approximate cases** (label kept as decimal, warning `numbering_approximate`): `w:numStyleLink`/`w:styleLink` that cannot be resolved through one style; roman numerals above 3999; `ilvl` above 8 or not an integer (level 0 used).
  6. **Sequences:** separate counters per story (body with its text boxes; each header or footer part; footnotes; endnotes). A `w:num` whose `lvlOverride` has its own `w:lvl` or start begins its own sequence.
  7. NITs: escaped private-use bullet characters, explicit set of upper-case formats, `nonlocal` instead of the list closure. Threat model T5: "numbering labels follow the visibility of the level and the paragraph mark; whether a paragraph counts follows its mark".

### S3-T4 Preview in the browser

- Owner: `frontend-dev`. Tests first: `test-engineer`. Branch: `feat/s3-preview` (worktree `/home/claude/wt/s3-preview`). No new dependency.
- AC:
  1. `extractFile` validates the stage 3 `200` contract strictly (all fields, enums, caps); a `200` body may be up to 4 MiB + 64 KiB (error bodies stay capped at 4 KiB); anything invalid → `unknown_error`. `501 not_implemented` maps to "PDF and Word support is coming" (temporary).
  2. An accepted file keeps its extraction result in memory (never in storage in this stage).
  3. Per contract, a "Preview" section (collapsed by default): the files in order (main text, then annexes) with their language label, then the blocks as plain text with part labels (Body, Footnote, Endnote, Header, Footer, Text box) and page numbers when present. Long text: the first 200 blocks, then "Show all" (no rendering of 1,000,000 characters by default).
  4. **Removed text** (expandable): count per reason with the sample, labelled "Hidden text removed". **Warnings**: icon + text per code (`not_read_*`, `borderline_text`, `pdf_edited`, `external_reference`, and unknown codes as a generic "Some content could not be read"). `ocr_pages` shows "Pages N need text recognition" (OCR comes in S3-T5).
  5. All text is plain text (no HTML sinks), inside `<bdi>` where it is untrusted; i18n en/uk/ru; accessible headings and disclosure buttons.
- Threats: T1, T3, T5.

### S3-T5 OCR of scans in the browser

- Owner: `frontend-dev`. Tests first: `test-engineer`. Branch: `feat/s3-ocr` (worktree `/home/claude/wt/s3-ocr`). New dependencies (approved, exact pins and conditions in "Stage 3 dependencies"): `pdfjs-dist@6.4.299`, `tesseract.js@7.0.0`, `tesseract.js-core@7.0.0`, `@tesseract.js-data/eng@1.0.0`, `@tesseract.js-data/ukr@1.0.0`, `@tesseract.js-data/rus@1.0.0`.
- AC:
  1. **Self-hosted assets:** a script `frontend/scripts/copy-ocr-assets.mjs` copies the pdf.js worker, the Tesseract worker, the LSTM-only wasm core files and the `4.0.0_best_int` language data into `frontend/public/ocr/` (git-ignored) and verifies each language file against the SHA-256 manifest (fails the build on a mismatch). It runs explicitly from the `build` and `dev` scripts (npm lifecycle hooks do not run because of `ignore-scripts`). No CDN, no `blob:` workers, no `quickjs-eval.*`, no `pdf.sandbox`.
  2. **CSP and Trusted Types** (`frontend/public/_headers`, security review required): `worker-src 'self'` (no `blob:`); `trusted-types default`; a `default` policy with `createScriptURL` only, allowing an exact list of our worker URLs; every other sink still throws. The OCR worker is our classic wrapper that installs the same policy before `importScripts`.
  3. **pdf.js settings:** same-origin `workerPort`; `enableXfa: false`, `disableFontFace: true`, `useSystemFonts: false`; self-hosted cMap, font, wasm and ICC URLs; no text or annotation layer; render with `AnnotationMode.ENABLE`. Canvas size capped (longest side 4,000 px; scale about 2× for OCR).
  4. **Tesseract settings:** `workerBlobURL: false`, `cacheMethod: 'none'`, LSTM only, languages `ukr+rus+eng`; input only a canvas or `ImageData`.
  5. **Flow:** an accepted PDF keeps its `File` in memory until its `ocr_pages` are done. The form renders only those pages, recognizes them one at a time (at most one OCR job in the whole form), shows "Recognizing page N of M…", and can be cancelled by removing the file. Recognized text becomes blocks (`part` = `body`, `page` = N) merged into the file's extraction in page order; `ocr_pages` is then empty. At most 30 OCR pages per file; more → the file is rejected with `too_many_ocr_pages`.
  6. **Confidence:** per page; below 60 → material warning `ocr_low_confidence` (shown with icon and text); every OCR page gets warning `ocr_used` (not material).
  7. Assets load lazily (only when a file needs OCR). The OCR text goes through the same caps as server text (characters, blocks).
  8. Tests (Vitest): orchestration with mocked pdf.js and Tesseract modules (order, one job at a time, cancel, caps, confidence warnings, merge into extraction); the asset script (copies only allowed files, hash check fails on mismatch); `_headers` policy test updated; a Trusted Types policy test (allowed URLs pass, any other URL throws).
- Threats: T1, T5, T8, T9.

### S3-T6 Google Docs by public link

- Owners: `backend-dev` (S3-T6a, first), then `frontend-dev` (S3-T6b). Tests first: `test-engineer`. Branch: `feat/s3-gdocs` (worktree `/home/claude/wt/s3-gdocs`). Design: ADR 0012 (outbound HTTP), threat model T7. New runtime dependency: `httpx==0.28.1` (see "Stage 3 dependencies").
- Threats: T1, T2, T3, T6, T7, T11.

**S3-T6a — backend** (PR #35)

1. **Guard** (`app/net/`, ADR 0012 point 3, exact rules there): an `httpcore` network backend. `connect_tcp` accepts port 443 only and the ADR hostname rule only (IP literals in any notation and single-label names refused), resolves once through an injectable non-blocking resolver inside the connect timeout, refuses the whole result if any address is not public (IPv4: `is_global` and not multicast; IPv6: in `2000::/3` and `is_global`; IPv4-mapped and NAT64 checked by their IPv4 address), and tries the checked IPs one by one through the inner backend. `connect_unix_socket` raises `BlockedHostError`. Errors are typed (`BlockedHostError`, `BlockedAddressError`) and carry no address or hostname in their message.
2. **Client factory** (`app/net/`): new client per call, `trust_env=False`, `follow_redirects=False`, `retries=0`, HTTP/1.1 only, certificate verification on (`certifi`), connect 5 s and read 10 s timeouts; it accepts no `proxy`, `uds`, `mounts` or `local_address`; requests never set the `sni_hostname` extension. A test proves the production factory uses the guard: with a fake resolver that returns `127.0.0.1`, a real request fails with `BlockedAddressError` and the inner backend is never asked to connect. Tests also cover: Unix socket refused, no proxy taken from `HTTPS_PROXY`/`ALL_PROXY` in the environment, `sni_hostname` absent.
3. **Policy test:** no module under `app/` except `app/net/` creates an `httpx` client or uses `urllib`, `http.client`, `socket.create_connection`, `socket.socket` or `asyncio.open_connection` (sandbox code that already uses `socket` for its pipe, if any, is listed explicitly).
4. **Guard tests** (T2 control 4): hosts `127.0.0.1`, `127.1`, `0.0.0.0`, `[::1]`, `2130706433`, `0x7f000001`, `localhost`, `intranet` (single label), `Example.COM.` (normalized and accepted), `-bad-.com`; resolver results `127.0.0.1`, `10.0.0.1`, `172.16.0.1`, `192.168.0.1`, `169.254.169.254`, `100.64.0.1`, `0.0.0.0`, `224.0.0.1`, `::1`, `fd00::1`, `fe80::1`, `fec0::1`, `ff02::1`, `::7f00:1`, `::ffff:127.0.0.1`, `::ffff:224.0.0.1`, `64:ff9b::7f00:1`, `64:ff9b::a00:1`; a mixed result (one public and one private address) is refused; port 80 and 8443 refused; the inner backend receives the IP string, not the hostname; with two public addresses and the first failing, the second is tried.
5. **Fetcher** `fetch_google_doc(document_id) -> bytes` (`app/net/google_docs.py`):
   - export URL built from the validated ID only (`re.fullmatch`): `https://docs.google.com/document/d/<ID>/export?format=docx`;
   - request headers exactly: a fixed `User-Agent`, `Accept: application/vnd.openxmlformats-officedocument.wordprocessingml.document`, `Accept-Encoding: identity`; never a `Cookie`, `Authorization`, `Referer` or any header of the incoming request (`X-Provider-Key` included);
   - redirects handled by the fetcher: at most 3; the `Location` is resolved against the current URL and must be `https`, port 443 or none, no user info, host `docs.google.com` or matching `^doc-[a-z0-9-]{1,60}-docs\.googleusercontent\.com$`; the cookie jar is cleared before each hop; host `accounts.google.com` → `google_doc_not_public`; anything else, or a fourth redirect → `google_doc_unavailable`;
   - status: `200` with the DOCX media type → read; `200` with `text/html` → `google_doc_not_public`; other media types → `google_doc_unavailable`; `401`, `403` → `google_doc_not_public`; `404` → `google_doc_not_found`; `429`, `5xx` and anything else → `google_doc_unavailable`;
   - body read raw (no decoding); any `Content-Encoding` other than `identity` → `google_doc_unavailable`; `Content-Length` above the file limit, or more bytes than the limit while streaming → `google_doc_too_large` (stop reading at once);
   - the whole fetch has a total deadline of 20 s (`GOOGLE_FETCH_TIMEOUT_SECONDS`); the total deadline and every `httpx` timeout (connect, read, write, pool) → `google_doc_timeout`; DNS, TLS, connection and guard errors → `google_doc_unavailable` (a resolver `OSError` becomes an `httpcore.ConnectError` with a fixed text); every `httpx` and guard error is mapped with `raise ... from None`, and its `str()` is never logged or returned (it can contain the URL or an IP address);
   - `Content-Disposition` and other metadata are never read.
   Tests use a fake transport for the flow (redirect chain, every status, cookies set by a response are not sent on the next hop, header set, caps, deadline).
6. **Endpoint** `POST /api/extract/google-doc`:
   - `Content-Type` must be `application/json` (else `415 unsupported_media_type`); body limit is the JSON limit (`413 request_too_large`, existing middleware, exact path match);
   - body `{"document_id": "<ID>"}`, no other fields; malformed JSON or other fields → `422 invalid_request`; ID not a full match (`re.fullmatch`) of `[A-Za-z0-9_-]{25,100}` → `422 invalid_google_doc_id`; errors are `{"error": "<code>"}` and never echo the input (no FastAPI default validation body);
   - takes the extraction slot first (`503 busy` with `Retry-After`, before any body byte is read; only the `415` header check comes before it) and holds it through the body read, the fetch, the extraction and the response; the body read has the deadline `GOOGLE_BODY_TIMEOUT_SECONDS` (5 s, the body is a small JSON) → `408 upload_timeout`, then the `422` checks above;
   - fetch errors: `422 google_doc_not_public`, `422 google_doc_not_found`, `422 google_doc_too_large`, `502 google_doc_unavailable`, `504 google_doc_timeout`;
   - the fetched bytes must be detected as DOCX by magic bytes (else `502 google_doc_unavailable`), then the same `run_extraction` with the same limits; extraction errors and the `200` response are exactly as for `/api/extract`;
   - logging: method, path, status, duration only; never the ID, a URL, a hostname, an address or a response header. Loggers `httpx` and `httpcore` at `WARNING` in `log_config.json` and at application start (`httpx` logs each request URL at `INFO`). Extend the log canary test with an ID canary that goes through a real `httpx.AsyncClient` (guarded backend with a fake resolver and a fake inner backend), so the `httpx` request log is covered.
7. Settings: `GOOGLE_FETCH_TIMEOUT_SECONDS` (20), `GOOGLE_CONNECT_TIMEOUT_SECONDS` (5), `GOOGLE_BODY_TIMEOUT_SECONDS` (5); bounds validated like the existing settings.

**S3-T6b — frontend** (PR #36)

1. Each contract region gets a "Google Docs link" text field with an "Add" button (i18n `en`, `uk`, `ru`) and a hint: the document must be shared as "Anyone with the link can view"; for private documents, download as DOCX or PDF and upload.
2. Link check in the browser with `new URL()`: protocol `https:`, host exactly `docs.google.com`, no user name or password, no explicit non-default port (`:443` is the default and is normalized away by `new URL()`), path `/document/d/<ID>` optionally followed by `/edit`, `/view`, `/preview`, `/copy` or `/`, ID `^[A-Za-z0-9_-]{25,100}$`; query and fragment ignored. Anything else → inline error "This is not a Google Docs document link" (published `/d/e/…/pub` links included). The pasted link is never rendered as a clickable link.
3. The request: `POST /api/extract/google-doc`, JSON `{"document_id": ID}`, with the same fetch options as uploads (`credentials: "omit"`, `redirect: "error"`, `cache: "no-store"`) and the same strict response validation and size caps as `extract.ts`; error codes are paired with their status like the upload codes.
4. The document becomes a row in the contract like an uploaded DOCX: label "Google Docs document …<last 6 characters of the ID>", same scheduler (at most two requests in flight, `busy` retry with a capped delay), same preview, counts toward the file limits, removal aborts the request. A second add of the same ID to the same contract is refused as a duplicate.
5. The ID is kept in component memory (a `Map` by row id) only while its row exists: to send the request, retry on `busy` and refuse duplicates. It is dropped when the row or its contract is removed. It never enters reducer state, announcements or storage; it is not written to `localStorage`, IndexedDB, the URL or the console. The link field has `autocomplete="off"` and is cleared after "Add". Later cache keys (stage 4) use the content hash, never the ID.
6. Error messages for every new code (all three languages). CSP unchanged: no Google host in any directive.
7. Tests (Vitest): link parsing table (valid forms, wrong host, `http:`, user info, port, `/u/0/` form, `/d/e/` published form, short and long IDs, ID with `.`), request options and body, every error code shown, duplicate refusal, removal aborts, no storage writes.

## Stage 4 — Browser hash and cache

Design: ADR 0013 (browser cache and history), ADR 0001, ADR 0008 point 4. Threats: T3, T9, T11. Customer decision (2026-10-22): history is **off** by default.

Order: S4-T1 and S4-T2 in parallel (different modules; resolve conflicts in the locale files at merge). S4-T3 docs last. New development dependency for S4-T2 tests: `fake-indexeddb` **6.2.5** exactly (approved by `security-reviewer`, 2026-10-22; dev only, imported only in tests, not in `dist/`).

### S4-T1 Hashes and duplicate detection (PR #49)

- Owner: `frontend-dev`. Tests first: `test-engineer`. Branch: `feat/s4-hash` (worktree `/home/claude/wt/s4-hash`).
- Threats: T3 (control 7), T11.

1. `src/hash/sha256.ts`: `sha256Hex(data: ArrayBuffer | Uint8Array | string): Promise<string>` through `crypto.subtle.digest("SHA-256", …)`; strings are UTF-8 encoded; result is 64 lower-case hex characters. No fallback implementation: if `crypto.subtle` is missing, it throws `HashUnavailableError` (the page needs a secure context anyway).
2. `src/hash/normalize.ts`: `normalizeForHash(text: string): string` exactly as ADR 0013 point 8 (NFC; CRLF and CR → LF; tabs and runs of spaces → one space; spaces at line ends removed; three or more line breaks → two; trim). Tests: a table of inputs, idempotence (`f(f(x)) === f(x)`), NFD vs NFC input gives the same hash, Cyrillic and Latin look-alikes give different hashes.
3. `src/hash/key.ts`: `canonicalJson(value)` (sorted object keys at every level, no spaces, arrays keep order, only strings, finite numbers, booleans, `null`, arrays and plain objects; anything else throws) and `buildKey(parts: Record<string, KeyPart>): Promise<CacheKey>` = `sha256Hex(canonicalJson({ v: 1, ...parts }))`. `CacheKey` is a branded string type. Tests: key order does not change the key; array order does; `undefined`, `NaN`, functions, `Date` throw.
4. **File hash before upload.** When a file is added, the browser hashes its bytes. The same bytes already in the same contract (any status except `rejected`) → the new row is refused as `duplicate_file` with no request to the server. The same bytes in another contract → the row is accepted and shows a warning "The same file is in Contract X" (i18n, all three languages).
5. **Text hash after extraction.** When a row becomes `accepted` (upload, OCR finished, or Google Docs), the browser hashes `normalizeForHash` of its text blocks joined with `\n\n` in order. A row with the same text hash as another accepted row in the same contract → a warning "Same text as another file in this contract"; in another contract → "Same text as a file in Contract X". Warnings only; nothing is refused after extraction. A Google Docs row with the same text as an uploaded file is detected this way.
6. `contractTextHash(contract)`: hash of the canonical JSON of the ordered text hashes of the accepted rows; `null` while any row is `queued` or `checking`. Exported for stage 9; tested now.
7. Hashes live only in memory (reducer state or component state), next to the extracted text, and are dropped with the row. Never in `localStorage`, `sessionStorage`, IndexedDB, the URL, the console or announcements, and never sent over the network (not in any request to our server). Tests spy on the storage APIs and on `fetch`.
8. Hashing a 10 MiB file must not block the UI thread for long: hash with `crypto.subtle` (asynchronous); the row stays `queued` until the hash is done; removing the row while hashing drops the result.

### S4-T2 `CacheStore`, history setting and clear all (PR #50)

- Owner: `frontend-dev`. Tests first: `test-engineer`. Branch: `feat/s4-cache` (worktree `/home/claude/wt/s4-cache`).
- Threats: T3 (controls 6, 7), T9 (CSP unchanged), T11 (mapping stored only with history on).

1. **Port** `src/storage/cacheStore.ts` (ADR 0013 points 3–6):
   ```ts
   interface CacheStore {
     get<T>(key: CacheKey, validate: (data: unknown) => data is T): Promise<CacheHit<T> | null>;
     put(key: CacheKey, kind: CacheKind, data: unknown): Promise<PutResult>; // "stored" | "disabled" | "too_large" | "storage_full" | "failed"
     list(): Promise<CacheEntryMeta[]>; // key, kind, createdAt, lastUsedAt, size; newest first
     delete(key: CacheKey): Promise<void>;
     clear(): Promise<void>;
     purgeExpired(): Promise<number>;
   }
   ```
   `CacheKind` is `"analysis"` for now. `get` updates `lastUsedAt` on a hit. Time comes from an injectable clock. The stored record keeps the data as a JSON string (`json`), parsed on read; `size` is its UTF-8 length.
2. **Adapters:** `IndexedDbCacheStore` (own wrapper, no `idb`; database `aic-cache` version 1, store `entries`, key path `key`, index `lastUsedAt`; `onversionchange` closes the connection; every write is one transaction), `MemoryCacheStore`, `DisabledCacheStore`. One contract test suite runs against all three (the disabled store has its own expectations).
3. **Validation on read:** unknown `schema` or `kind`, `createdAt` or `lastUsedAt` not a finite number or in the future by more than one day, `size` mismatch, `json` not a string or not parseable, or the caller's validator returns false → the entry is deleted and `get` returns `null`.
4. **Retention:** 90 days from `createdAt`. `purgeExpired` runs at start-up and inside `get` and `list`. An entry exactly 90 days old is expired.
5. **Caps (fail closed):** at most 2 MiB per entry (UTF-8 length of `JSON.stringify(data)`) → `too_large`, nothing written; `JSON.stringify` failure → `failed`; if the put makes more than 100 entries, the least recently used are deleted in the same transaction until 100 remain. `QuotaExceededError` or any transaction error → the transaction is aborted, nothing partial stays, result `storage_full` or `failed`.
6. **History setting** `src/storage/historySetting.ts`: `isHistoryEnabled()` reads `localStorage["aic.history"] === "on"` (any read error → off); `setHistoryEnabled(true)` writes `"on"`; `setHistoryEnabled(false)` **first** removes the key, **then** deletes the database. `createCacheStore()` returns `DisabledCacheStore` when history is off or IndexedDB cannot be opened (open error, `null` `indexedDB`, security error), else `IndexedDbCacheStore`.
6a. **Other tabs and start-up (ADR 0013 point 2a):** `IndexedDbCacheStore` re-reads the setting before it opens the database and before every `put` (off → `disabled`, nothing written, no database created). A `storage` event for `aic.history` (or `key === null`) switches the app to `DisabledCacheStore` at once. After `onversionchange` the store instance never reopens the database. In `onupgradeneeded` the store re-reads the setting; off → abort the upgrade transaction and return `disabled`. At start-up with history off, the app calls `indexedDB.deleteDatabase("aic-cache")`. Test with two store instances on one `IDBFactory` (two tabs): tab A turns history off or clears all → tab B's next `put` returns `disabled` and the database does not exist afterwards; an `open` from tab B that reaches `onupgradeneeded` after the setting is off aborts the upgrade, and the database does not exist.
7. **Clear all** `clearAllData()`: **first** removes every `localStorage` and `sessionStorage` key that starts with `aic.` except `aic.lang`; **then** deletes the `aic-cache` database and, where `indexedDB.databases()` exists, every other database it lists. Result `"cleared" | "blocked" | "failed"`; `blocked` when a deletion is blocked by another open connection.
8. **Settings panel** (`src/settings/`), reachable from the page header ("Data and history"), i18n `en`, `uk`, `ru`:
   - toggle "Save results in this browser" (default off, `role="switch"` with `aria-checked`), one-sentence explanation: results with contract quotes (names replaced by placeholders) are kept in this browser for 90 days, not encrypted; do not turn on on a shared computer;
   - turning it off when entries exist asks for confirmation ("Saved results will be deleted"); cancel keeps it on;
   - status line: number of saved results (from `list()`), or "History is not available in this browser" with the toggle disabled when IndexedDB is not available;
   - button "Delete all data in this browser" with a confirmation; on `blocked` the message asks to close other tabs of the app; after success the toggle shows off and the count is 0.
9. **"Already analyzed" dialog** `src/settings/CachedResultDialog.tsx` (used by stage 10; shipped and tested now with a fixture): shows the date of the saved result (formatted for the UI language) and two buttons, "Show saved result" and "Run a new analysis". `role="dialog"`, `aria-modal="true"`, labelled by its heading; focus moves to the first button; focus stays inside the dialog; Escape closes it with a third outcome `"cancel"`; focus returns to the element that opened it. Props: `savedAt`, `onChoice(choice: "cached" | "new" | "cancel")`.
10. Nothing in this task writes contract text, file bytes, extracted text or a placeholder mapping to any storage (T3 control 7, ADR 0013 point 9a). CSP unchanged. `fake-indexeddb` is imported only in test files; a test (or a build check) proves the production bundle in `dist/` does not contain it.
11. Tests (Vitest, `fake-indexeddb` for the IndexedDB adapter; inject a fresh `IDBFactory` per test): contract suite on all adapters, retention boundary, LRU eviction at 101 entries (same transaction), 2 MiB boundary (exactly 2 MiB stored, one byte more refused), quota error leaves no entry, corrupt entry deleted, history off writes nothing (spy on `indexedDB.open`), two-tab test (6a), start-up delete with history off, clear all order and with a blocked deletion, `sessionStorage` keys cleared, settings panel behaviour, dialog keyboard behaviour.

### S4-T3 Docs for stage 4

- Owner: `docs-writer`. After S4-T1 and S4-T2 are merged.
- Threat model: check T3 control 6 and T11 control 5 against the merged code (updated in the stage 4 plan PR); add the no-encryption residual risk. ADR 0013 status → accepted. `CLAUDE.md` architecture row unchanged unless the design changed. README: "Data and history" in "How it works".
