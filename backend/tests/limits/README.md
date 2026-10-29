# S6-T3 tests: public names (the contract for the implementation)

These tests are written from the S6-T3 acceptance criteria, ADR 0016 point 8
and threat model T6. They fail until `app/limits/` exists.

| Name | Meaning |
| --- | --- |
| `app.limits.window.FixedWindowLimiter(limit, window_seconds, max_keys, clock)` | Fixed-window counter per key. `clock` is a `Callable[[], float]` (seconds). Non-positive `limit`, `window_seconds` or `max_keys` raise `ValueError`. |
| `.hit(key: str) -> bool` | Count one hit. `True` = allowed. `False` = over the limit, or a new key refused because the table is full of fresh keys (fail closed). A refused hit does not extend the window. A window starts at the first hit of a key and ends at `start + window_seconds` (the key is fresh again at exactly that time). |
| `app.limits.client_ip.client_key(scope, settings) -> str` | `scope` is the ASGI scope (dict). Returns IPv4 text, an IPv6 /64 key, or `unknown`. IPv4-mapped IPv6 gives the IPv4 key. |
| `Settings.trusted_proxy_hops` (env `TRUSTED_PROXY_HOPS`) | Default `1`. Production: the Nth entry from the right of `X-Forwarded-For` (several headers are joined in order). Fewer entries than hops, missing or invalid -> `unknown`. |
| `Settings.max_extractions_per_client` (env `MAX_EXTRACTIONS_PER_CLIENT`) | Default `1`. Extraction slots one client key may hold at once. |

Development uses the socket peer (`scope["client"][0]`) and ignores
`X-Forwarded-For`. Production never uses the peer.

The per-client slot limit covers `/api/extract`, `/api/extract/google-doc`,
`/api/segment`, `/api/safety-check` and is on top of the shared pool
(`max_concurrent_extractions`, default 2). When a client is over its limit:
`503 {"error":"busy"}` with `Retry-After`, answered before the body is read.
Slots are released on success, error, timeout and client disconnect.
No client address (IPv4, IPv6, or its /64 prefix) appears in logs.
