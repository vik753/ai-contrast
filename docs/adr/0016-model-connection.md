# ADR 0016 — Model connection: AI provider port, adapters, keys and free mode

- Status: proposed (tech lead, 2026-10-29; needs `security-reviewer` design and dependency approval)
- Date: 2026-10-29
- Related: ADR 0002 (official SDKs), ADR 0007 (free default model), ADR 0008 and 0015 (type gate), ADR 0009 (prompt injection), ADR 0012 (outbound HTTP), threat model T1, T2, T6, T9, T10, T11

## Context

Stage 6 connects the backend to AI providers. Later stages (7 topics, 8 tagging, 9 analysis) call models only through what this stage builds. No contract analysis runs in stage 6: the only call a client can trigger is a fixed connection check.

Facts checked on 2026-10-29:

- The official SDKs no longer use `httpx`. `anthropic` (1.x and 2.x) and `openai` (3.x) depend on **`httpx2`** (`pydantic/httpx2`, a fork of `httpx`) and **`httpcore2`**. The SDKs reject an `httpx` client (`_reject_httpx_object`). `httpcore2.AsyncConnectionPool` still takes a `network_backend`, so the guard design of ADR 0012 still works, but on the new packages.
- `httpx2` depends on `truststore` (operating system trust store) and `idna`; `anthropic` also depends on `opentelemetry-api` (API only, no SDK or exporter), `docstring-parser`, `jiter` and `sniffio`.
- Releases are frequent (`anthropic` 2.0 on 2026-10-21, `openai` 3.41 on 2026-10-28). We pin versions that are at least 14 days old at the time of the security review.

## Decision

### 1. Dependencies

- Runtime: `anthropic`, `openai`, `httpx2`, `httpcore2`, pinned exactly in `pyproject.toml` and `uv.lock`, each the newest release at least 14 days old when `security-reviewer` approves (candidates on 2026-10-29: `anthropic==1.15.0`, `openai==3.31.0`, `httpx2`/`httpcore2` of the same date range). No extras (`aiohttp`, `bedrock`, `vertex`, `mcp`, `realtime` and others stay out).
- `app/net/` moves from `httpx`/`httpcore` to `httpx2`/`httpcore2`, including the Google Docs export. `httpx` stays only as a development dependency (FastAPI test client). The ADR 0012 policy test changes to: only `app/net/` may import `httpx2` or `httpcore2`; nothing under `app/` imports `httpx` or `httpcore`.
- TLS: the outbound client builds its own `ssl.SSLContext` from the `certifi` bundle (verification on, hostname check on) and passes it as `verify=`; `truststore` and environment trust settings are never used (`trust_env=False`). A test pins this.
- `opentelemetry-api` is allowed as a transitive dependency only. No OpenTelemetry SDK or exporter is installed (T1 control 9); a policy test fails if `opentelemetry-sdk` or any exporter is in `uv.lock`.
- Every version change of these packages needs a security review (CLAUDE.md rule 9).

### 2. `AIProvider` port (`app/ai/port.py`)

- The port has two operations:
  - `check() -> CheckResult`: sends a **fixed built-in probe** (a constant in `app/ai/`, no caller input) and reports only success or an error code. It never returns model text.
  - `complete_json(request: AIRequest) -> ModelJson`: for stages 7–9. `AIRequest` is a frozen dataclass whose content fields are gate types only (`PseudonymizedDocument`, `PseudonymizedText`, `ConfirmedTopic`) plus instruction templates from `app/ai/prompts/` (constants) and a JSON schema class. **No `str` parameter anywhere in the port** (ADR 0015 point 5; the AST policy test already covers every module under `app/ai/`).
- Prompt assembly (`app/ai/prompting.py`): instructions and data are separate messages; every data block is wrapped in delimiters with a random per-block nonce from `secrets.token_hex(16)`; a block whose text contains its own delimiter is impossible because the nonce is chosen after the text is known and checked against it. One `AIRequest` carries at most one document (ADR 0009); a policy test checks it.
- `ModelJson` is the raw parsed JSON object, size-capped; schema validation with Pydantic happens in the caller (stage 9). Model output is never logged, never put into an error, never re-sent to a model.
- The model gets no tools: adapters never send `tools`, `tool_choice`, `functions` or similar fields; a test inspects the wire body.

### 3. Adapters (`app/ai/adapters/`)

- `AnthropicAdapter` on the `anthropic` SDK (Messages API) and `OpenAICompatibleAdapter` on the `openai` SDK (Chat Completions, which every preset supports). Application code imports only the port and a factory; a policy test enforces that only `app/ai/adapters/` imports `anthropic` or `openai`.
- **One SDK client per request**, built with our guarded `httpx2.AsyncClient` from `app/net/` (ADR 0012 rules: `trust_env=False`, no redirects, `retries=0` on the transport, and `max_retries=0` on the SDK client, explicit timeouts). The client and the key are closed and dropped when the request ends. No global client, cache or class attribute holds a key.
- SDK defaults that could leak or change behaviour are fixed: `max_retries=0`; no `default_headers` from the environment; the SDK base URL always comes from our preset table or the checked custom URL, never from `ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL` (the factory passes `base_url` explicitly; a test sets those variables and checks they are ignored); `OPENAI_ORG_ID`, `OPENAI_PROJECT_ID` and similar variables are ignored the same way.
- Caps: request timeout (connect 5 s, total 120 s for `complete_json`, 20 s for `check`), response body cap (streamed, fails closed, 2 MiB), `max_tokens` set on every call (the probe uses at most 16 output tokens, or the provider's minimum for reasoning models).
- **Error mapping** (T1 control 4): every SDK and transport error becomes one of our codes with `raise … from None`: `provider_auth_failed` (401/403), `provider_model_not_found` (404 or model error), `provider_rate_limited` (429), `provider_bad_request` (400/422), `provider_unavailable` (5xx, timeout, connection), `provider_blocked_host` (guard refusal), `provider_bad_response` (invalid JSON, cap exceeded). SDK exception text, response bodies and request IDs are never logged or returned.

### 4. Providers and models

- **Preset table** (`app/ai/presets.py`, an allowlist): `free` (AI Contrast Free, Cloudflare Workers AI), `anthropic` (`https://api.anthropic.com`), `openai` (`https://api.openai.com/v1`), `gemini` (`https://generativelanguage.googleapis.com/v1beta/openai/`), `mistral` (`https://api.mistral.ai/v1`), `openrouter` (`https://openrouter.ai/api/v1`), `custom` (OpenAI-compatible only). Each preset names its adapter and a few suggested model IDs for the UI.
- **Model ID** is chosen by the client for every preset except `free` (fixed: `@cf/openai/gpt-oss-120b`). Grammar: 1–128 characters of `[A-Za-z0-9._:/@-]`, starting with a letter or digit; anything else is `422 invalid_model`.
- **Custom base URL** (`custom` only): `https` scheme, no user info, no query or fragment, port absent or 443, hostname rules of ADR 0012 point 3, path at most 256 characters of `[A-Za-z0-9._~/-]`; the backend appends the endpoint path. Checked twice: syntax at the request boundary, addresses in the guard at connect time. `ALLOW_PRIVATE_PROVIDER_URLS=true` (development only, refused in production at startup) allows `http` and private hosts for local models.

### 5. API key handling

- The client's key travels only in `X-Provider-Key` (T1). Request models never contain it; a dependency reads the header into `SecretStr` (1–512 printable ASCII characters, else `422 invalid_provider_key`). The key is passed to the SDK constructor and nowhere else. The log canary test (T1 control 6) is extended to the new endpoints, to every error path and to the wire capture: the key may appear on the wire **only** in the provider's auth header (`x-api-key` or `Authorization: Bearer`) and never in the URL or body.
- `free` takes no client key; a request with `X-Provider-Key` and `provider: "free"` is refused (`422 unexpected_provider_key`), so a client key is never sent to Cloudflare by mistake.
- Our own secrets `CF_ACCOUNT_ID`, `CF_AI_TOKEN`, `TURNSTILE_SECRET_KEY` are `SecretStr` settings, read only from the environment, absent in development unless set. Without them `free` answers `503 free_mode_unavailable`. They are never logged, returned or sent to the browser (T10 control 1).

### 6. Connection check endpoint

`POST /api/provider/check`, body `{ "provider": "...", "model": "...", "base_url": "..." (custom only), "turnstile_token": "..." (free only) }`, header `X-Provider-Key` (not for `free`). It runs `check()` and answers `200 { "ok": true }` or `4xx/5xx { "error": "<code>" }`. It never returns model text, headers or provider error bodies, so it is useless as a proxy. Limits: JSON body 4 KiB; per-IP rate limit (point 8); at most 2 checks in flight per server.

### 7. Free mode (ADR 0007)

- `free` uses the `OpenAICompatibleAdapter` with base URL `https://api.cloudflare.com/client/v4/accounts/<CF_ACCOUNT_ID>/ai/v1` and our token. The account ID is validated as 32 lower-case hex characters at startup.
- **Turnstile:** every free-mode call that the client triggers needs a Turnstile token, verified server-side at `https://challenges.cloudflare.com/turnstile/v0/siteverify` through `app/net/` (guarded client, 10 s timeout, 64 KiB cap), with our secret and without the client IP. Accepted only if `success` is true and `hostname` equals our frontend host (production) — one token, one use (Cloudflare enforces single use; we also refuse a token seen in the last 10 minutes, kept as a hash in memory). Errors: `403 turnstile_failed`.
- **Quotas** (in memory, reset at 00:00 UTC, the same time Cloudflare resets Neurons): per-IP daily free calls; a global daily Neuron budget below 10,000 (initial 8,000), charged before the call by an estimate from the input size and `max_tokens`, corrected after the call from the reported usage. Exhausted → `429 free_quota_exhausted`. State is lost on restart; that is accepted (Cloudflare's own free limit is the hard cap, T10 control 2).
- **Turnstile in the browser** is the one exception to "no third-party scripts" (CLAUDE.md rule 8), approved by the customer with ADR 0007. The script `https://challenges.cloudflare.com/turnstile/v0/api.js` is loaded **only** when the client uses free mode (never on page load), with `render=explicit`. CSP adds `https://challenges.cloudflare.com` to `script-src` and `frame-src` only; the Trusted Types `default` policy accepts that one exact URL. No other Cloudflare script, no analytics. The UI says that free mode loads a Cloudflare check.

### 8. Rate limiting and client IP

- Our own small in-memory limiter (`app/limits/`), not slowapi: a fixed-window counter per key, bounded table (at most 50,000 keys, oldest evicted; when full of fresh keys, new keys are refused — fail closed). No new dependency. CLAUDE.md architecture row changes from "slowapi" to "own in-memory limiter".
- **Client IP** (T6 control 6): in production the IP is taken from the **rightmost** `X-Forwarded-For` entry added by Render's proxy (`TRUSTED_PROXY_HOPS=1`); in development, the socket peer. A missing or invalid value counts as one shared key `unknown` with the strictest limit.
- Limits (initial, settings): `/api/provider/check` 10 per minute and 60 per day per IP; free-mode calls 5 per day per IP; and the stage 13 release blocker: **at most 1 extraction slot per IP** across `/api/extract`, `/api/extract/google-doc`, `/api/segment` and `/api/safety-check` (`503 busy` with `Retry-After`).

### 9. Browser

- Provider settings panel: preset list (free selected by default), model field with the preset's suggestions, custom base URL under "Advanced" (custom only), API key field (type `password`, `autocomplete="off"`), "Test connection" button, "Forget key" button, and the Gemini free-key hint with Google's data-use warning (ADR 0007).
- **Key storage** (T1 browser controls): `sessionStorage` by default; opt-in "Remember on this device" uses `localStorage` with a warning. Keys `aic.key.<provider>`. "Forget key" and "Clear all" (ADR 0013 point 7) remove them. The key is sent only to our backend, only in `X-Provider-Key`, with `credentials: "omit"`, `redirect: "error"`, `cache: "no-store"`. It is never put in a URL, a log, an error message, IndexedDB or React dev state that is persisted.
- Free mode shows which provider processes the text and its data policy (T10 control 8).

### 10. Wire canaries (T11 control 10)

The canary harness of ADR 0015 point 6 gets an `AIProvider` wire capture: both adapters run against `httpx2.MockTransport` (through our client factory with the guard swapped for the mock), for `check()` and for a `complete_json()` call built from a safety-passed canary document. The test asserts: no identifier canary and no key canary in the URL, headers (except the auth header) or body; no `tools` field; exactly one document per request.

## Consequences

- Positive: one guarded network path for every outbound call; the port cannot take raw text; stages 7–9 only add prompts and schemas.
- Negative: four new runtime packages plus their transitive ones (`truststore`, `opentelemetry-api`, `docstring-parser`, `jiter`, `sniffio`, `distro` if pulled); `app/net/` is migrated, so the ADR 0012 guard tests must pass again on `httpcore2`. Turnstile is a third-party script in free mode.
- Residual risk: the in-memory limiter resets on restart and is per process (single worker, ADR 0011); a distributed attacker with many IPs can still use the free quota, which is capped by Cloudflare's free plan. Provider-side retention of masked text is outside our control; the UI states each provider's policy only for free mode.
