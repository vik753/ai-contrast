# Threat model — AI Contrast v1

Owner: `security-reviewer`. Updated at every stage. Fully reviewed at stage 12 (security audit).

## Principles

1. **The server stores nothing.** No database, no files on disk, no server-side cache.
2. **The server holds no client secrets.** The client API key lives on the server only for the duration of one request. The server holds only its own operational secrets for the free default model and Turnstile (ADR 0007), in hosting environment variables.
3. **Everything external is untrusted:** files, links, provider URLs, contract text, model output.
4. **Minimal dependencies,** each pinned with a hash.
5. **Least privilege** for every component, workflow and agent.
6. **Security in every stage,** not only at the end.

## Assets

| Asset | Where it lives | Impact of a leak |
| --- | --- | --- |
| Client API key | Browser. Server: memory, one request only. | Spending on the client's account; account access at the provider. |
| Contract text | Browser. Server: memory. The client's AI provider. | Personal and commercial data exposure. |
| Analysis results | Browser IndexedDB | Contain contract quotes. |
| Google Docs document ID (public link) | Browser; server: memory, one request only | Read access to that document for anyone who has it. |
| Our free-tier credentials (`CF_ACCOUNT_ID`, `CF_AI_TOKEN`, Turnstile secret) | Render secret env vars only | Free quota theft; abuse of our Cloudflare account in our name. |
| Our backend | Render | Resource abuse; attacks on others through us. |
| Repository and CI | GitHub | Code or dependency tampering. |

## T1. API key leak

Threats: XSS in our frontend; malicious dependency; key in logs, errors or URLs; network interception; browser extensions; shared computers.

Server controls:

1. The key travels only in the `X-Provider-Key` header. Never in a URL or query string.
2. Backend type: `pydantic.SecretStr`.
3. Request logging records only method, path, status and duration. No headers, no bodies.
4. The error handler returns only an error code and a short safe message. SDK exception text never leaves the server and is never logged verbatim.
5. The key lives only inside one request. No global variables, caches or shared SDK clients with a key.
6. **Log canary test:** a request with the key `sk-CANARY-<random>` must not leave the canary in logs, responses or errors. Runs in CI on every change.
7. A redaction filter on the root log handler removes exception messages, tracebacks and stack info from every logger, including `uvicorn.error`. Tested through `log_config.json`. The filter is installed only through `uvicorn --log-config log_config.json`: every way of starting the backend (Dockerfile, Compose, Render) keeps that flag; do not override the Docker command on Render. Limits: message text is not scrubbed, so application code never logs exception objects or messages; no logger may use `propagate=False` with its own handler; `logging.raiseExceptions = False`, so formatting errors never print arguments.
8. A custom `422` handler: validation errors never return `input`, `ctx` or `msg`, and never echo client-chosen keys (unknown fields, dict keys). The field list is capped.
9. FastAPI native telemetry is disabled explicitly. No OpenTelemetry SDK or exporter without security review.
10. SDK debug-logging variables (`ANTHROPIC_LOG`, `OPENAI_LOG`) are never set in production.
11. Settings use `hide_input_in_errors=True`, so startup errors never print values (including our own secrets).

Browser controls:

1. Default storage: `sessionStorage` (cleared when the tab closes).
2. Opt-in "Remember on this device": `localStorage`, with a warning.
3. "Forget key" button.
4. Strict CSP (see T9). No third-party scripts, analytics or CDNs.
5. React escaping only. Raw HTML sinks are banned by lint (`no-restricted-syntax` with T1 messages): `dangerouslySetInnerHTML`, `__html`, `innerHTML`/`outerHTML` writes, `insertAdjacentHTML`, `createContextualFragment`, `setHTMLUnsafe`, `parseHTMLUnsafe`, `document.write`, `DOMParser`, `srcDoc`. Inline `eslint-disable` has no effect (`noInlineConfig`). Runtime backstop: Trusted Types (`require-trusted-types-for 'script'; trusted-types 'none'`). Untrusted text is never passed through i18n `<Trans>` and never used as a translation key. Untrusted text such as file names reaches i18next `t()` only as interpolation values. `escapeValue: false` relies on React escaping. `skipOnVariables: true` is set explicitly. File names render inside `<bdi>`.
6. UI tip: create a separate provider key for AI Contrast with a spending limit.

Out of our control: malicious browser extensions and compromised client devices. The privacy policy says so.

## T2. SSRF through a custom provider URL

Threat: the backend calls a URL supplied by the client. An attacker supplies `http://169.254.169.254/`, `http://localhost:8000/` or an internal hosting address, or uses our server as an open proxy.

Controls:

1. **Presets:** known providers have hard-coded base URLs (allowlist).
2. **Custom base URL** (advanced setting) passes the SSRF guard:
   - scheme `https` only, port 443 only;
   - hostname only: lower case, one trailing dot stripped, at least two labels, final label `[a-z]{2,63}` or `xn--…`; IP literals in any notation and single-label names rejected;
   - resolve DNS once (non-blocking, inside the connect timeout); reject the whole result if any address is not public. IPv4: `is_global` and not multicast. IPv6: inside `2000::/3` and `is_global`; IPv4-mapped (`::ffff:0:0/96`) and NAT64 (`64:ff9b::/96`) addresses are checked by their IPv4 address;
   - connect to the checked IPs one by one (DNS rebinding defense); TLS SNI and certificate check use the hostname; no `sni_hostname` override; Unix sockets refused;
   - no proxy (`trust_env=False`, no SOCKS, no `proxy`, `uds`, `mounts` or `local_address`), `retries=0`;
   - redirects are not followed;
   - the backend appends the endpoint path; the client sets only the base URL;
   - timeouts and a response size limit.
3. Local models (Ollama and others) only in local development: `ALLOW_PRIVATE_PROVIDER_URLS=true`. Off in production. The Docker image defaults to `ENVIRONMENT=production`, so this refusal fails closed.
4. Tests cover at least: `127.0.0.1`, `127.1`, `0.0.0.0`, `[::1]`, `2130706433`, `0x7f000001`, `169.254.169.254`, `10.0.0.1`, `192.168.0.1`, `[fd00::1]`, `::7f00:1`, `fec0::1`, `ff02::1`, `::ffff:224.0.0.1`, `64:ff9b::a00:1`, and hostnames that resolve to loopback.
5. The loggers `httpx` and `httpcore` stay at `WARNING` (they log request URLs at `INFO`). Outbound errors are mapped to our codes; their text (URL, IP address) is never logged or returned. Implementation: `app/net/` (ADR 0012).

## T3. Contract data leak

Threats: files on server disk, logs, error trackers, server cache, the AI provider, shared computers.

Controls:

1. Files are processed in memory. Any temporary file a library needs is deleted in `finally`. Uploads are raw bytes (`application/octet-stream`) with no file name in the URL, headers or body (ADR 0010). The browser sends them with `credentials: "omit"`, `redirect: "error"` and `cache: "no-store"`; tests pin these options.
2. Logs contain no content: only sizes, counts, durations and error codes.
3. No external error tracker in v1. If added later, it must scrub content.
4. API responses carry `Cache-Control: no-store`.
5. The UI warns that contract text goes to the provider chosen by the client.
6. Browser: "Save history" toggle, "Clear all" button, 90-day retention.
7. Extracted text is kept in in-memory React state only; never in storage, URLs, logs or announcements; dropped when the file is removed.
8. CI rejects telemetry SDKs, exporters and distros (`opentelemetry-sdk|distro|exporter-*`, `logfire`, `sentry-sdk`) in `uv.lock` until a security review approves one.

## T4. Malicious files

Threats: zip bombs (DOCX is a ZIP), XXE, PDF bombs (huge page count, nested streams), type spoofing, parser vulnerabilities.

Controls:

1. Limits (initial): 10 MiB per file; 5 files per contract; 5 contracts per analysis (free mode: 2); 50 MiB per analysis; 100 pages per document and 300 per analysis (from stage 3); ZIP: 2,000 entries, 100 MiB declared uncompressed size, compression ratio 200.
2. File type by magic bytes, not by extension.
3. DOCX: before parsing, check total uncompressed size, entry count and compression ratio.
   - **ZIP is read the same way as the stage 3 reader:** the central directory ends exactly at the EOCD; no EOCD or ZIP64 signature in the archive comment; the parsed entry count equals the EOCD count; entry names are printable ASCII with no `.`, `..` or empty segments and no segment ending in `.`; case-folded duplicates are rejected. Stage 3 (S3-T2, `app/extraction/docx_zip.py`) adds, before any part is read: local headers lie back to back from offset 0 to the central directory in central-directory order (no overlap, no gap, strictly increasing offsets) and match the central directory (signature, name, flags, method, CRC, sizes; a data descriptor must hold the central values); OPC part names (no percent-encoded unreserved character or `/`; duplicates compared after percent-decoding and `casefold()`); declared sizes at most `MAX_DOCX_PART_BYTES` per part and `MAX_ZIP_UNCOMPRESSED_BYTES` in total. Parts are decompressed as streams: more or fewer bytes than declared, data after the end of the deflate stream, or a wrong CRC fail while reading. Every failure is `archive_rejected`. A test checks that `zipfile` and the detector see the same entries.
   - Text detection only classifies the file; stage 3 decodes the whole file strictly and repeats the control-character rule, failing closed. Extraction uses only the kind the server detected on the same bytes in the same request.
4. XML: every DOCX part (`[Content_Types].xml`, every `.rels`, the main part, styles, notes, headers, footers) is parsed with `defusedxml` 0.7.1 with `forbid_dtd=True` (and its defaults `forbid_entities=True`, `forbid_external=True`). **Any DTD → `suspicious_package`**, before an entity can be expanded (XXE and "billion laughs" included); malformed XML is `suspicious_package` too. Parsing is streaming (`iterparse` over the checked part stream, elements cleared after use) with an element-depth cap per part (`MAX_DOCX_XML_DEPTH`, 256) and an element cap over all parts of one document (`MAX_DOCX_ELEMENTS`, 2,000,000), both failing closed with `suspicious_package`. No python-docx. Worst case at the caps (about 29 MB of XML, 1.9 million elements): child CPU about 7 s of 20 s, peak RSS 46 MiB of the 192 MiB address-space limit.
   - **PDF** (S3-T3, `app/extraction/pdf.py`, `pdf_document.py`, `pdf_device.py`): `pdfminer.six` 20260107 only (no pdfplumber). **pdfminer logging:** the `pdfminer` logger is set to ERROR by `app.extraction.pdf` itself, does not propagate and has only a counting handler that never formats a record (pdfminer messages quote PDF bytes); a counted record makes the material warning `damaged_pdf`. `CMAP_PATH` is removed from the environment before extraction, so CMaps load only from pdfminer's packaged JSON files. **Encrypted PDF:** opened only when the empty **user** password works. pdfminer's owner-password fallback is switched off for every handler (R2 to R4: the empty owner password would decrypt the user password; R5 and R6: the owner hash is tried first), so a file with a non-empty user password and an empty owner password is `encrypted_unsupported`. Any other password, an unknown security handler or algorithm → `encrypted_unsupported`; permission flags are ignored (the person can open the file). Page count checked before any page is interpreted (`MAX_PDF_PAGES`, 100 → `too_many_pages`). The cross-reference chain is walked by our own loop, not pdfminer's recursion: more than `MAX_PDF_PREV_CHAIN` (32) `/Prev` links or a loop → `pdf_damaged`; an object that a cross-reference section lists but that cannot be parsed (pdfminer would silently read an older revision) → `pdf_damaged`; **free-entry rule:** an object number that is free in a newer revision but in use in an older one, or that has another generation in an older section, is *suspect* (pdfminer would resurrect the old object that viewers no longer show); `pdf_damaged` only when extraction actually resolves a suspect number (a `getobj` check), so a legitimate update that deletes an object nobody references is read normally (warning `pdf_edited` only); the table and the `/XRefStm` of one hybrid revision count as one; a `/XRefStm` section that leads back to a section already seen → `pdf_damaged`; any other parse failure or `RecursionError` → `pdf_damaged` (the exception is dropped: it may quote the file). Cross-reference reconstruction → material warning `damaged_pdf`; a lost trailer is repaired only when exactly one catalog and no encryption dictionary exist. Caps: rendered glyphs ≤ 2 × `EXTRACT_MAX_TEXT_CHARS`, filled paths recorded per page ≤ 20,000, flow ordering for ≤ 200 text boxes per page (else top-to-bottom order), annotations read per page ≤ 1,000. Worst case at the caps (100 dense pages, 534,000 characters): child CPU about 9.3 s of 20 s, peak RSS 53 MiB of the 192 MiB address-space limit. Residual: a flate stream that decompresses beyond the memory limit ends the child (`extraction_failed`, fail closed).
5. Parsing runs in a subprocess with time and memory limits (ADR 0011): one child per file, `RLIMIT_AS`, `RLIMIT_CPU`, `RLIMIT_FSIZE` = 0, `RLIMIT_NOFILE`, `RLIMIT_CORE` = 0 and `RLIMIT_NPROC` = 0 (a compromised child cannot leave processes behind); wall deadline and result cap in the parent; stderr never logged.
6. Docker: non-root user, read-only root filesystem, in-memory temp directory. Compose uses `read_only`, `tmpfs` for `/tmp`, `cap_drop: [ALL]` and `no-new-privileges`. Render cannot enforce a read-only root filesystem (residual risk). Compose ports bind to 127.0.0.1; Docker Engine 28.0 or later is required for LAN isolation. The local backend has `mem_limit: 512m`, the same as Render.

## T5. Prompt injection (ADR 0009)

**Threats.**
- The other party writes the whole contract and addresses the AI openly or hidden (white, tiny or clipped PDF text, hidden DOCX runs, zero-width, tag or variation-selector characters, fake delimiters and role tokens, other languages, encodings, legal wording aimed at automated review).
- **Cross-document influence:** one contract steers how another is rated, or frames it as "containing AI instructions".
- **Visible but not extracted:** harsh terms in footnotes, text boxes, content controls, tracked insertions, form fields, light-grey fine print or a section titled like "Signatures" — the person signs them, the model never sees them.
- **Tagging and topic attacks:** a clause routed to "Other" is never rated; over-tagging; steering AI-suggested topics.
- **Evidence gaming:** a planted favorable sentence with a buried exception, quote truncation, number-unit mismatch, self-praise.
- **Cost and denial:** clause explosion, reasoning-heavy text, repair loops, catastrophic regex backtracking.

**Controls (summary; details in ADR 0009):**

1. **Read what the person reads:** DOCX parts resolved through package relationships, package anomalies rejected as 🔴 "suspicious package", zero text is an error; own DOCX walker (insertions, content controls, text boxes, fields, footnotes, endnotes, headers, footers); a "Not read" warning only for material unread content, and then no green for that document; damaged PDFs (cross-reference reconstruction) are material "Not read"; references to documents that were not provided are shown and cap the referring clauses at 🟡.
2. **Clean input:** symbol-font checkboxes mapped first; default-ignorable, Cf, Co, Cs, Cn removed by a checked-in table; other scripts kept and flagged; cleaning is idempotent; NFC for text, NFKC + confusable skeleton only for matching; PDF and DOCX text dropped only when provably invisible, borderline and overlapping text kept and flagged; removed text shown in the preview and reported as 🔴 "contains hidden text".
3. **Detect and flag:** versioned pattern file, also run on suggested and custom topics; heuristic hits 🟡 and block green for that clause; high-confidence classes (special or role tokens including gpt-oss harmony tokens, our tags, hidden instruction text, instruction plus rating words) 🔴 and remove all greens of the document; model reports accepted only from single-document calls.
4. **Map-reduce prompts:** one document per call for tagging and rating; schema-first topics with typed attributes, proposed for custom topics without any document text and confirmed by the client (`ConfirmedTopic`); comparison by code from attribute values; `text` attributes shown side by side for the client; no model call receives text of two documents, directly or through summaries (policy and wire tests); random per-block nonce in both tags; all special tokens and tag look-alikes neutralized; sandwich rules; fixed transform order with an offset map.
5. **Code-checked output:** strict schema; global-override markers cap every green of the document; model tags that push a topic over its cap are dropped, and a topic not analyzed in one document shows 🟡; repair never sends previous model output back; every finding needs a verbatim quote; quotes expanded to full sentence or clause; green needs a minimum-length quote outside suspicious spans, a deterministic exception rule the model cannot lift, a bounded cross-reference check (depth 1, at most 5 clauses), and matching numbers with units; missing topics computed by code; keyword tags cannot be removed by the model; "Other" clauses scanned and rated.
6. **Limits:** no tools, network, memory, keys or mapping for the model; hard token cap including repairs and reasoning; linear-time patterns inside the limited parsing subprocess; caps on clauses, tags and entities. **Every cap fails closed:** the document is rejected or the topic is "not analyzed" with a reason; nothing is truncated silently.
7. **Adversarial eval gate:** attack success measured against clean twins over N ≥ 3 runs; held-out set; adaptive red-team at stage 12; for AI-layer changes the tech lead records the eval result on the PR head in the PR; eval secrets per T8.

**Residual risk:** a wrong yellow or red finding on any document — including a false red on a competing contract — or a missed difference remains possible. A green always needs a verbatim, expanded, exception-checked quote, but a verified quote can still mislead because the attacker writes the text. ToUnicode mismatches, text drawn as images, text covered by a shape or image painted later, and text in the same colour as a coloured box under it are only partly handled in v1.

DOCX residual risks (S3-T2, review round 1). The rule is: text is removed only when its invisibility is resolved exactly; anything we cannot resolve is kept and flagged `borderline_text`.

- **Layout-dependent headers and footers:** we read the headers and footers that sections reference (first-page ones with `w:titlePg`, even-page ones with `w:evenAndOddHeaders`), but we do not lay out pages. A section that never starts a page, or a one-page section with an even-page header, can make us read a header the person never sees; the opposite cannot happen.
- **Text boxes:** text-box text is read in full; text that overflows a fixed-size box, boxes anchored off the page, and boxes behind other shapes or images are not detected.
- **Field updates on open:** Word can recalculate fields when the file opens or prints (`w:dirty`, `w:updateFields`); we read the stored result and add `field_may_update` (not material). Field codes are never read.
- **Data binding:** a content control bound to custom XML (`w:dataBinding`) can show a value from the custom XML part instead of the stored text; we read the stored text and add the material warning `not_read_data_binding`.
- **Markup compatibility:** `mc:Choice` is read only for the namespaces Word supports (others are `suspicious_package`); elements in an unknown ignorable namespace are skipped and must hold no text. Other consumers (for example older Word versions or other editors) may show `mc:Fallback` content that we do not read.
- **List numbering labels (S3-T2b):** numbering labels follow the visibility of the level and the paragraph mark; whether a paragraph counts follows its mark (a hidden, deleted or moved-away mark does not count). Counters are kept per story; a definition we cannot resolve becomes decimal with `numbering_approximate`.
- **Formatting we do not resolve:** table conditional formatting (kept + `borderline_text`), theme tints and shades that need rounding (kept + `borderline_text`), shading patterns, character borders, emboss and engrave effects, text effects (`w14:textFill`), and fonts whose glyphs are blank.

## T6. Server abuse

Threats: DoS, oversized uploads, request floods, use as a free AI proxy.

Controls:

1. Per-IP rate limit in memory (slowapi).
2. Concurrent analysis limit (initial: 2) because of 512 MB RAM.
3. Request body size limit at the server: `BodySizeLimitMiddleware` on every route (64 KiB for JSON routes, 10 MiB for `/api/extract`); a `Content-Length` with more than 18 digits counts as too large. `/api/extract` also has the `ExtractionLimiter` (2 slots per process, `503 busy` with `Retry-After`, exposed by CORS), a body deadline of 60 s and a minimum average rate of 32 KiB/s after 5 s (`408 upload_timeout`), `Connection: close` on every response sent before the body is read, and `Transfer-Encoding` rejected (`411`). The limiter counts per process, so the backend runs as a single worker: `--workers 1` is explicit in the Dockerfile `CMD`, so `WEB_CONCURRENCY` cannot raise it (policy test).
4. **Before stage 13:** at most 1 extraction slot per client IP (client IP derived as in control 6), with the stage 6 rate limiter. **Release blocker for stage 13.** Residual risk until then: one client can hold both slots with about 32 KiB/s per slot (about 2 MiB per minute), as a burst or a drip, and reconnect at each 60 s deadline.
5. CORS allows only our frontend origin. CORS protects against other websites in a browser, not against scripts. `ALLOWED_ORIGINS` holds exact `https://host[:port]` origins; `null`, paths and wildcards are rejected; production requires it to be set explicitly.
6. Per-IP limits behind Render's proxy: never trust the leftmost `X-Forwarded-For`; derive the client IP from the hop added by Render's proxy, and document it.
7. No raw prompt endpoint. The server runs only our analysis pipeline, so it is useless as a generic AI proxy.
8. If needed later: Cloudflare Turnstile.
9. The extraction slot covers sending the response: a send deadline (30 s) cuts off a client that does not read; uvicorn `--limit-concurrency 32` caps open connections. **Release blockers for stage 13:** (a) uvicorn has no header-read timeout, so 33+ sockets that send a partial header make every route answer 503 (slowloris); (b) a cut-off connection is closed, not aborted, and keeps about 4 MiB of kernel send buffer until the client closes it. Check whether Render's proxy buffers headers and responses; if not, add a header-read timeout and abort cut-off connections, and add kernel socket buffers to the ADR 0011 memory budget.

Browser controls:

1. At most 2 checks are in flight in the whole form. A `busy` answer is retried at most 3 times, and `Retry-After` is limited to 1–10 s. The browser reads a `200` body up to 4 MiB + 64 KiB (the extraction result) and any other body up to 4 KiB.
2. The preview caps blocks and characters per file; client validation repeats every server list cap.

## T7. Google Docs import

Threat: the import makes our server fetch a URL (SSRF, open proxy), leaks the document link, or brings a different or oversized file into the pipeline.

Controls (S3-T6, ADR 0012):

1. **Public link only.** The browser accepts only `https://docs.google.com/document/d/<ID>/...` and sends only the ID, in a JSON body, to `POST /api/extract/google-doc`. The server validates the ID with `^[A-Za-z0-9_-]{25,100}$` and builds the export URL `https://docs.google.com/document/d/<ID>/export?format=docx` itself. No URL from the client is ever fetched.
2. **SSRF guard** (T2 controls, ADR 0012) on every hop: DNS resolved once, public addresses only, connection to the checked IP, TLS verified for the hostname, no proxy from the environment.
3. **Redirects:** at most 3, each checked: `https`, port 443, no user info, host `docs.google.com` or matching `^doc-[a-z0-9-]{1,60}-docs\.googleusercontent\.com$` (not other user-content hosts). The cookie jar is cleared before each hop. A redirect to `accounts.google.com` means the document is not public. Any other target is refused.
4. **Request:** fixed headers only (`User-Agent`, `Accept`, `Accept-Encoding: identity`). No cookies, no header from the incoming request. A response with any `Content-Encoding` is refused (no decompression bomb).
5. **Limits:** body streamed with the file limit (10 MiB), connect timeout 5 s, total 20 s. The extraction slot is held for the whole request. The body must be a DOCX by magic bytes; then the same sandbox extraction as an upload.
6. **The ID works like a password** for that document: never logged (the `httpx` request log is off, T2 point 5), never in a URL of our API, never in an error message, never stored in the browser. The ID is validated with a full match (Python `$` also accepts a trailing newline).
7. **Metadata:** the Google title (`Content-Disposition`, `docProps`) is never read (ADR 0008 point 8).
8. **Private documents (Google Picker) are not in v1:** the Picker needs third-party scripts (CLAUDE.md rule 8). The person exports the document as DOCX or PDF and uploads it.
9. **Stage 13 deployment blocker:** a per-IP rate limit for this endpoint, because it makes outbound requests.

## T8. Supply chain

Example: on 2026-03-24, malicious LiteLLM 1.82.7 and 1.82.8 were published to PyPI. They stole LLM API keys, cloud keys, SSH keys and `.env` secrets. The attackers got publishing access through the project's CI/CD.

Controls:

1. Minimal dependencies. No LiteLLM. Official `anthropic` and `openai` SDKs only.
2. Lock files with hashes: `uv.lock`, `package-lock.json`. Install only with `uv sync --locked` and `npm ci`. Docker base images are pinned by digest and updated by Dependabot. CI runs pip-audit with the OSV source. Docker base images, including `frontend/Dockerfile.dev`, are pinned by digest. There is no `# syntax=` directive, or it is pinned by digest. `COPY --from=` and `RUN --mount=...from=` use only stage aliases or digest-pinned images. Dependabot takes digest and patch updates only; Python, Node and uv minor and major upgrades are planned changes.
3. A new dependency needs approval of the tech lead and `security-reviewer`.
4. Updates through Dependabot pull requests with a cooldown of 7 days. Ignore rules use only `update-types` (never `versions:`), so they never suppress security updates. npm majors and Python/Node/uv minor and major versions are planned upgrades, reviewed every stage (`npm outdated`, `uv tree --outdated`). Dependabot alerts and security updates are enabled in repository settings.
5. CI: pip-audit, npm audit, CodeQL (Python and TypeScript). CodeQL languages: `python`, `javascript-typescript`, `actions`; query suite `security-extended`.
6. GitHub Actions pinned by full commit SHA; minimal `permissions:`. Workflow triggers are limited to `push`, `pull_request`, `schedule`, `workflow_dispatch`. No `pull_request_target`, no `workflow_run`. Every `actions/checkout` has `persist-credentials: false`. No `${{ }}` inside `run:`, comment lines included; pass values through `env:`. Job-level permissions are only `read`/`none`, except `security-events: write` for CodeQL. These rules are enforced by `backend/tests/test_repo_policy.py`.
7. GitHub secret scanning and push protection enabled.
8. Tesseract language data and fonts are committed or built into the bundle, not loaded from a CDN.
9. `frontend/.npmrc` sets `ignore-scripts=true` (do not remove it without security review); npm is pinned with `packageManager`. The Vite dev server is never exposed beyond localhost. The Compose frontend dev container runs as `node` (uid 1000) with a read-only root filesystem, no capabilities, `no-new-privileges` and `npm ci --ignore-scripts`. Residual risk: the `./frontend` bind mount is read-write, so on a Linux host where the developer is uid 1000, dev-server code can change the source tree. Planned mitigation: Compose Watch `sync`.
10. **Eval secrets (ADR 0009 Layer 6):** the eval never runs on `pull_request`. The GitHub `eval` environment has required reviewers and a deployment branch policy limited to `main` (`workflow_dispatch` runs the workflow file of the dispatched branch). PR-head evals run locally with a separate eval key with a low spending limit, never the production free-model token.

## T9. Security headers

Frontend (Cloudflare Pages `_headers`), draft — refined when libraries are added:

```
Content-Security-Policy: default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self' blob:; connect-src 'self' https://<api-domain>; img-src 'self' data: blob:; style-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'; upgrade-insecure-requests
Strict-Transport-Security: max-age=63072000; includeSubDomains
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
Permissions-Policy: camera=(), microphone=(), geolocation=()
Cross-Origin-Opener-Policy: same-origin
```

Deployed policy (stage 1) adds: `frame-src 'none'`, `font-src 'self'`, `manifest-src 'self'`, `require-trusted-types-for 'script'; trusted-types 'none'`, `Cross-Origin-Resource-Policy: same-origin`, `X-Frame-Options: DENY`. The exact policy lives in `frontend/public/_headers` and is pinned by `headers.test.ts`.

Stage 3 plan (OCR and Google Picker):

- `new Worker(url)` and `importScripts()` are Trusted Types sinks. Tesseract.js and PDF.js create workers, so add a reviewed `default` policy (`trusted-types default`) whose `createScriptURL` accepts only same-origin `/assets/` URLs; no `createHTML`/`createScript`. Workers need their own default policy from a small worker entry of ours, or a path-specific header rule.
- Self-host Tesseract `workerPath`, `corePath`, `langPath` and PDF.js `workerSrc`, `cMapUrl`, `standardFontDataUrl`, `wasmUrl`. PDF.js `isEvalSupported: false`. Prefer `workerBlobURL: false`, then remove `blob:` from `worker-src`.
- Google Picker needs Google hosts in `script-src`, `frame-src` and `connect-src`, and COOP `same-origin-allow-popups` for the Google Identity Services popup — a documented exception to the header tests.
- Turnstile (ADR 0007) needs `https://challenges.cloudflare.com` in `script-src` and `frame-src` — also a documented exception.
- An automated Playwright CSP smoke test (no `securitypolicyviolation`) runs in CI at the e2e stage.

Backend: `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, CORS allowlist.

## T10. Free default model (ADR 0007)

Threats: theft of our Cloudflare token; bots burning the shared free quota; using free mode as a free AI proxy; billing surprises.

Controls:

1. `CF_AI_TOKEN` is scoped to Workers AI only. It lives only in Render secret env vars. It is never sent to the browser, never logged, never part of an error. It is typed `SecretStr` and covered by the log canary test.
2. The Cloudflare account stays on the Workers Free plan: above 10,000 Neurons per day requests fail instead of being billed.
3. Free mode requires a valid Cloudflare Turnstile token, verified server-side, one use per analysis.
4. Per-IP daily limit and an in-memory global daily Neuron budget below the free allocation.
5. Stricter size limits in free mode (initial: 2 contracts and 30 pages per analysis).
6. Free mode runs only our analysis pipeline with a fixed model; no raw prompts, no client-chosen model.
7. Quota exhausted → `429` with code `free_quota_exhausted`; the UI offers the client's own key.
8. The UI states which provider processes the text in free mode and its data policy.

## T11. Identity leakage to AI providers (ADR 0008)

**Threat.** Identifiers from contracts (names of companies and people, codes, accounts, addresses, contacts, document numbers, vehicle and health data) reach an AI provider — including our free default provider — and are logged, retained or used for training. Side channels: file names, document metadata, PDF running headers and footers, custom topics and side text, wire-level SDK fields, cache, exports, logs, SSE and errors.

**Controls:**

1. All identifier classes in ADR 0008 are replaced by document-scoped typed placeholders (`[A.ORG_1]`) before any AI call; placeholder look-alikes in the source are neutralized; defined terms equal to masked names are masked.
2. Detection runs on de-hyphenated text and a confusable skeleton, inside the limited parsing subprocess, with linear-time patterns and caps; PDF running headers and footers are detected and masked or dropped.
3. The requisites section is processed line by line: only lines made entirely of identifiers, labels, role words and signature lines are dropped; any line with a condition is kept, masked, analyzed and flagged 🟡. Dropped lines are visible in the preview and counted as "not analyzed".
4. Mandatory preview; high-precision classes cannot be unmasked by the client. Checksummed codes are high-precision only with a context keyword (or inside the requisites section) and never match a number followed by a currency, `%` or a unit; a masked token next to an amount flags its clause 🟡. Detection caps fail closed (`too_many_identifiers`).
5. The mapping stays in the browser; it is never sent to AI endpoints or providers and never logged; "Clear all" and retention cover it; exports use placeholders by default.
6. **Fail-closed safety pass:** a detector version mismatch is rejected (`detector_version_mismatch`); idempotent input cleaning is only a check (`input_not_clean` if it would change anything, offsets never mapped); high-precision hits return `unmasked_identifier` with offsets, the browser pre-masks them and asks for a new confirmation; the server never changes confirmed text silently.
7. **Type gate:** a frozen dataclass with a runtime sentinel, created only by `safety_pass()`; never a request model; the `AIProvider` port takes no `str`; topics and side text become `PseudonymizedText` or `ConfirmedTopic`; repair never re-sends model output; an AST policy test enforces this, including `__new__` and `object.__setattr__` on gate types.
8. File names, PDF Info and XMP, DOCX `docProps`, embedded files and Google titles are never parsed into text, never logged, never sent. Uploads are raw bytes (`application/octet-stream`) with no file name in the URL, headers or body (ADR 0010). The browser sends them with `credentials: "omit"`, `redirect: "error"` and `cache: "no-store"`; tests pin these options.
9. Cache key = SHA-256 of the final masked text plus prompt and model versions.
10. **AI payload canaries on the wire** under the real `anthropic` and `openai` adapters (httpx `MockTransport`): URL, headers and the whole body, for every AI call type; plus negative checks for logs, SSE, errors, `422` and the browser's outgoing analysis request.
11. The eval measures recall and precision per class and per language.

**Residual risk:** the result is pseudonymized, not anonymous. Public standard terms, product wording, tariffs or procurement data can re-identify a counterparty. Automatic detection is never complete; the preview is the final control. Our backend sees the original text in memory during extraction and detection (nothing is stored).

## Checklist for every change

- [ ] Log canary test is green: no key or contract text in logs, responses or errors.
- [ ] All new external input is validated by a schema.
- [ ] Every new outbound request goes through the SSRF guard or uses an allowlisted preset.
- [ ] Every new dependency is approved and pinned in a lock file.
- [ ] Model output and contract text are rendered as plain text only.
- [ ] Every string that reaches a prompt is a gate type (`PseudonymizedDocument` / `PseudonymizedText` / `ConfirmedTopic`), an enum or a constant (T11).
- [ ] Every new AI call contains one document only, and its output is validated by code (T5).
- [ ] Every cap fails closed: no truncation, no partial masking, no partly rated topic (T5, T11).
- [ ] CI green: tests, linters, pip-audit, npm audit, CodeQL.

## Pre-launch audit (stage 12)

1. Review this threat model.
2. OWASP ZAP baseline scan.
3. Manual penetration test against OWASP Top 10 and OWASP Top 10 for LLM Applications.
4. Header check: Mozilla Observatory, securityheaders.com.
5. Fix findings and re-test.

PDF residual risks (S3-T3, review round 1). The rule is the same: text is removed only when its invisibility is exact; colours we cannot resolve, a zero-area clip, a form `BBox` that excludes the text, an optional content group that is OFF, a low alpha (below 0.2), a render mode outside 0 to 7, and light text on a known fill with a luminance difference under 0.2 are kept and flagged `borderline_text`. Content pdfminer does not run is a material warning (`not_read_annotation` for any visible annotation with an appearance stream, `not_read_pattern`, `not_read_type3`).

- **Type3 CharProcs:** a Type3 glyph is a small content stream. We read the text through `ToUnicode` (or the encoding) and measure the glyph size through `FontMatrix`, but we do not run the glyph procedures: a procedure that paints in a colour or shape different from the text colour, or draws other marks than the character, is not seen. Type3 fonts without `ToUnicode` are the material warning `not_read_type3`.
- **Transfer functions:** the graphics-state transfer function (`TR`, `TR2`), halftones and black generation can change the colour a device really prints; we compare the colour as written and do not apply them.
- **Overprint and blend:** overprint (`OP`, `op`), blend modes and soft masks change what shows through; a blend mode or soft mask only turns white-text removal into `borderline_text`. Spot colours (Separation, DeviceN) are resolved only through exponential tint transforms; Separation/DeviceN tint 0 counts as no ink only when the alternate colour at 0 is white. PostScript and sampled tint transforms are unresolved (kept and flagged).
- **Clips and layers:** a clip is tracked as a bounding box (a superset of the real clip), so text hidden by a non-rectangular clip inside that box is not detected; optional content `VE` expressions are treated as OFF.
