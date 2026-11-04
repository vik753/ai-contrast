# S6-T4 tests: public names (the contract for the implementation)

Written from `docs/agent/TASKS.md` S6-T4 (items 1-4, 3a, 3b), ADR 0016 points 5-8 and threat model T1, T2, T6, T10.
Run: `cd backend && uv run --locked pytest tests/check -q`. All tests fail until the feature exists.

## Endpoint

`POST /api/provider/check`, JSON body, header `X-Provider-Key` (not for `free`).
Body fields: `provider` (a `PresetId` value), `model` (required except for `free`; for `free` the model is fixed and any given value is refused with `422 unexpected_model`), `base_url` (`custom` only), `turnstile_token` (`free` only). Unknown fields are refused. Body cap 4096 bytes.

| Case | Status | Body |
| --- | --- | --- |
| success | 200 | `{"ok": true}` exactly |
| body over 4096 bytes | 413 | `{"error": "request_too_large"}` (before the body is parsed) |
| not JSON, wrong types, unknown field | 422 | `{"error": "invalid_request"}` |
| unknown `provider` | 422 | `{"error": "invalid_provider"}` |
| bad or missing `model` (non-free) | 422 | `{"error": "invalid_model"}` |
| `base_url` for a non-custom provider | 422 | `{"error": "unexpected_base_url"}` |
| bad custom `base_url` | 422 | `{"error": "invalid_base_url"}` |
| `turnstile_token` for a non-free provider | 422 | `{"error": "unexpected_turnstile_token"}` |
| `X-Provider-Key` missing or not 1-512 printable ASCII (non-free) | 422 | `{"error": "invalid_provider_key"}` |
| `X-Provider-Key` present with `free` | 422 | `{"error": "unexpected_provider_key"}` |
| free mode not configured | 503 | `{"error": "free_mode_unavailable"}` |
| Turnstile missing/refused/replayed/table full | 403 | `{"error": "turnstile_failed"}` |
| free quota (per IP or global Neurons) | 429 | `{"error": "free_quota_exhausted"}` + `Retry-After` |
| check rate limit (10/min, 60/day per IP) | 429 | `{"error": "rate_limited"}` + `Retry-After` |
| 2 checks already in flight | 503 | `{"error": "busy"}` + `Retry-After` |
| `AIError` | see below | `{"error": "<AIErrorCode value>"}` |

`AIError` status map: `provider_auth_failed` 401, `provider_model_not_found` 404, `provider_rate_limited` 429,
`provider_bad_request` 400, `provider_blocked_host` 422, `provider_unavailable` 502, `provider_bad_response` 502.
Order: size, JSON/schema, cheap validation (provider, model, base_url, key rules), free-mode availability,
check rate limit `hit()`, in-flight slot, then (free only) Turnstile, per-IP free `hit()`, Neuron budget, then `check()`.
A failed Turnstile is NOT refunded (review round 1). A refused budget refunds both hits of the same request.
Requests that fail cheap validation count nothing.

## Settings (`app.settings.Settings`, env = upper-case name)

`cf_account_id` (32 lower-case hex, else `ValidationError`), `cf_ai_token`, `turnstile_secret_key` (all `SecretStr | None`, default `None`),
`turnstile_expected_hostname: str | None`, `turnstile_action: str` (default `check`),
`check_per_minute=10`, `check_per_day=60`, `free_calls_per_ip_per_day=5`, `free_neuron_budget=8000` (`1..9999`, else `ValidationError`),
`max_concurrent_checks=2`, `turnstile_replay_max_entries=10000` (`1..10000`), `turnstile_replay_seconds=600`, `allow_private_provider_urls` (exists; `ENVIRONMENT=production` with `true` -> `ValidationError`).
Free mode is available only when `cf_account_id`, `cf_ai_token` and `turnstile_secret_key` are all set.
`turnstile_expected_hostname` unset: the hostname is not compared. Set: it must be equal.

## Test hooks (keyword arguments of `create_app` and `install()`; unset = production behavior; `app.state` is never read)

- `create_app(..., provider_transport=...)` (forwarded to `install()`): an `httpx2` transport passed as `transport=` to `provider_for` (also for `free`).
- `create_app(..., turnstile_transport=...)`: an `httpx2` transport for the siteverify call.
- `create_app(..., clock=...)`: `Callable[[], float]`, UTC epoch seconds, used by all windows, the quota and the `challenge_ts` age.

## New modules

- `app.net.turnstile.verify(token: str, secret: SecretStr, *, transport=None) -> TurnstileVerdict`.
  POST to the constant URL `https://challenges.cloudflare.com/turnstile/v0/siteverify` through `app/net/`; the secret and token only in the body; no `remoteip`.
  `TurnstileVerdict`: frozen dataclass `success: bool`, `hostname: str | None`, `action: str | None`, `challenge_ts: float | None` (UTC epoch seconds).
  `TurnstileError(Exception)` on transport error, status other than 200, non-JSON, wrong shape or a body over 64 KiB.
- `app.limits.free.FreeQuota(calls_per_ip: int, neuron_budget: int, max_keys: int, clock)`: daily, aligned UTC.
  `.reserve(key: str, neurons: int) -> QuotaDecision` (`allowed: bool`, `retry_after: int`, `reason: "ip" | "budget" | "table" | None`).
  A budget refusal counts no per-IP call. `.settle(estimate: int, actual: int) -> None` corrects the spent budget (never below 0).
  `.remaining_neurons -> int`. `neurons` must be >= 1.
- Daily tables (`check_per_day`, free per-IP) key IPv6 clients by /48; per-minute tables keep the /64 key of `client_key`. IPv4 and `unknown` are unchanged. `FreeQuota` receives the key as given; the endpoint maps it.
- `app.limits.free.CHECK_NEURONS = 10`: the Neuron estimate that a free check reserves before the call. A budget below it refuses every free check.
- The replay table stores a token only after Turnstile accepted it (a refused token is not stored). Entries older than `turnstile_replay_seconds` are dropped; a full table of fresh entries refuses new tokens with `403 turnstile_failed`.
