# ADR 0012 — Outbound HTTP: httpx with a guarded network backend

- Status: accepted (tech lead; `security-reviewer` approved the dependency and the design, 2026-10-22)
- Date: 2026-10-22
- Related: ADR 0002 (official SDKs), threat model T2, T6, T7

## Context

Stage 3 (S3-T6) adds the first outbound request of the backend: the export of a public Google Docs document. Stage 6 adds more: AI providers, including a custom base URL that the client supplies (T2). Every outbound request must follow the SSRF rules of `CLAUDE.md` rule 4: HTTPS and port 443 only, hostnames only, DNS resolved once, private and special addresses blocked, connection to the checked IP, no redirects, timeouts and size limits.

The official `anthropic` and `openai` SDKs (ADR 0002) are built on `httpx`, and both accept our own `httpx` client. One guard that works for `httpx` therefore covers the Google export now and the AI providers later.

`httpx` 0.28.1 is already in `uv.lock` as a development dependency (the FastAPI test client), together with `httpcore` 1.0.9, `h11`, `anyio`, `certifi` and `idna`. The runtime image already contains `h11` and `anyio` (through `uvicorn` and `starlette`).

## Decision

1. `httpx==0.28.1` becomes a runtime dependency, pinned exactly. No other new package: no `h2` (HTTP/2 stays off) and no `socksio` (no SOCKS proxies). `h11` stays at 0.16.0 or later (CVE-2025-43859). Every version change of `httpx`, `httpcore` or `h11` needs a security review.
2. All outbound HTTP of the application goes through one package, `app/net/`. A policy test fails if any other module under `app/` creates an `httpx` client or uses `urllib`, `http.client`, `socket.create_connection` or `asyncio.open_connection`.
3. **The guard is an `httpcore` network backend.** Its `connect_tcp(host, port, ...)`:
   - accepts port 443 only;
   - accepts only a DNS hostname: lower case, one trailing dot stripped, at least two labels, labels of letters, digits and hyphens (1–63 characters, no leading or trailing hyphen), final label `[a-z]{2,63}` or `xn--[a-z0-9-]{1,59}`. This refuses IP literals in any notation (`127.1`, `2130706433`, `0x7f000001`, `[::1]`) and single-label names (the resolver would append search domains);
   - resolves the hostname once, with the non-blocking resolver of the event loop, inside the connect timeout;
   - refuses the whole result if any address is not public. IPv4: `is_global` and not multicast. IPv6: inside `2000::/3` and `is_global`; addresses in `::ffff:0:0/96` (IPv4-mapped) and `64:ff9b::/96` (NAT64) are checked by their embedded IPv4 address. (In Python 3.13 `is_global` alone is true for `::7f00:1` and `fec0::1`, so it is not enough.);
   - tries the checked addresses one by one, in the resolver's order, and connects to the IP address, not to the hostname. TLS is started afterwards by `httpcore` with the original hostname as SNI, and the certificate is verified for that hostname;
   - `connect_unix_socket` always raises `BlockedHostError`.
4. **Client settings** for every outbound client: a new client per request (no shared client and no key in a global), `trust_env=False` (no proxy or certificate settings from the environment), `follow_redirects=False` (the caller checks each redirect itself), `retries=0`, certificate verification on with the `certifi` bundle, explicit connect, read and total timeouts, `Accept-Encoding: identity` where the caller reads a body with a cap, and a streamed size cap that fails closed. The factory accepts no `proxy`, `uds`, `mounts` or `local_address`. Requests never set the `sni_hostname` extension (it would override both SNI and the certificate hostname).
5. **Logging and errors:** the loggers `httpx` and `httpcore` are set to `WARNING` in `log_config.json` and at application start (`httpx` logs every request URL at `INFO`). Every `httpx` and guard error is mapped to our own error code with `raise ... from None`; `str()` of such an error is never logged or returned, because it can contain the URL or the IP address.
6. Tests use a fake resolver and a fake inner backend. No test reaches the network.

## Consequences

- One guard for the Google export (S3-T6) and for AI providers and custom base URLs (stage 6). Stage 6 passes our guarded `httpx` client to the SDKs.
- The guard is below the transport, so a test with `httpx.MockTransport` does not exercise it. The guard has its own tests, and a test shows that the production client factory uses the guarded backend.
- Wiring a custom network backend into `httpx` 0.28 needs either our own transport on top of `httpcore.AsyncConnectionPool` or a subclass of `httpx.AsyncHTTPTransport`. The choice is an implementation detail; the version pin and the tests protect it on upgrades.
- A Dependabot update of `httpx` or `httpcore` needs a security review (CLAUDE.md rule 9).
