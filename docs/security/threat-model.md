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
10. SDK environment variables have no effect (ADR 0016 point 3). `app/net/ai_client.py` lets only an allowlist of request headers leave the process, so `ANTHROPIC_CUSTOM_HEADERS`, `OPENAI_CUSTOM_HEADERS`, organization and project variables (`OPENAI_ORG_ID`, `OPENAI_PROJECT_ID`) and trace-context headers never reach the wire. The base URL always comes from our preset table or the checked custom URL. `ANTHROPIC_LOG` and `OPENAI_LOG` cannot lower the log level: the adapters set the SDK and `httpx2`/`httpcore2` loggers to `WARNING` before every call. Anthropic tracing is off (`open_telemetry={"traces": {"enabled": False}, "propagation": False}`), so `ANTHROPIC_OPEN_TELEMETRY_*` variables record no span. Tests set each variable to a canary and check the wire, the logs and the spans. Operators still never set the debug variables in production.
10a. Mapped provider errors keep no exception chain. An adapter maps every SDK or transport error to one `AIError` code and raises it outside the `except` block, so the new error has no `__cause__` and no `__context__` (the SDK error holds the request with the key header). The error text is never used.
11. Settings use `hide_input_in_errors=True`, so startup errors never print values (including our own secrets).

Browser controls:

1. Default storage: `sessionStorage` (cleared when the tab closes).
2. Opt-in "Remember on this device": `localStorage`, with a warning.
3. "Forget key" button. "Clear all" (ADR 0013) also removes every `aic.key.<provider>` entry from both storages and empties the key field that is open at that moment.
4. Strict CSP (see T9). No third-party scripts, analytics or CDNs.
5. React escaping only. Raw HTML sinks are banned by lint (`no-restricted-syntax` with T1 messages): `dangerouslySetInnerHTML`, `__html`, `innerHTML`/`outerHTML` writes, `insertAdjacentHTML`, `createContextualFragment`, `setHTMLUnsafe`, `parseHTMLUnsafe`, `document.write`, `DOMParser`, `srcDoc`. Inline `eslint-disable` has no effect (`noInlineConfig`). Runtime backstop: Trusted Types (`require-trusted-types-for 'script'; trusted-types default`). The only policy is our `default` policy (`src/ocr/trustedTypes.ts`, installed at startup in `main.tsx`): `createScriptURL` accepts an exact list of our own URLs under `/ocr/`; there is no `createHTML` and no `createScript`, so those sinks still throw. Untrusted text is never passed through i18n `<Trans>` and never used as a translation key. Untrusted text such as file names reaches i18next `t()` only as interpolation values. `escapeValue: false` relies on React escaping. `skipOnVariables: true` is set explicitly. File names render inside `<bdi>`.
6. UI tip: create a separate provider key for AI Contrast with a spending limit.

Out of our control: malicious browser extensions and compromised client devices. The privacy policy says so.

## T2. SSRF through a custom provider URL

Threat: the backend calls a URL supplied by the client. An attacker supplies `http://169.254.169.254/`, `http://localhost:8000/` or an internal hosting address, or uses our server as an open proxy.

Controls:

1. **Presets:** known providers have hard-coded base URLs (allowlist).
2. **Custom base URL** (advanced setting) passes the SSRF guard:
   - scheme `https` only, port 443 only;
   - hostname only: lower case, one trailing dot stripped, at least two labels, final label `[a-z]{2,63}` or `xn--…`; IP literals in any notation and single-label names rejected. The custom provider URL uses the same hostname rule (`check_hostname`) at the request boundary, and an IP literal (any notation) is refused early by syntax with `provider_blocked_host`, before any DNS or network call;
   - resolve DNS once (non-blocking, inside the connect timeout); reject the whole result if any address is not public. IPv4: `is_global` and not multicast. IPv6: inside `2000::/3` and `is_global`; IPv4-mapped (`::ffff:0:0/96`) and NAT64 (`64:ff9b::/96`) addresses are checked by their IPv4 address;
   - connect to the checked IPs one by one (DNS rebinding defense); TLS SNI and certificate check use the hostname; no `sni_hostname` override; Unix sockets refused;
   - no proxy (`trust_env=False`, no SOCKS, no `proxy`, `uds`, `mounts` or `local_address`), `retries=0`;
   - redirects are not followed; on AI calls every 3xx response is refused with `provider_bad_response`, whatever the SDK request options say (a redirect would carry the provider key to another host);
   - AI responses accept identity encoding only: a non-identity `Content-Encoding` is refused (`provider_bad_response`), and the size cap (2 MiB; 64 KiB for Turnstile) counts the bytes that are read;
   - there is one source of network backend and TLS context (`app/net/client.py`: the guarded backend and a context built from the `certifi` bundle, `keylog_filename` unset). `truststore` is installed with `httpx2` but never used;
   - the backend appends the endpoint path; the client sets only the base URL;
   - timeouts and a response size limit.
3. Local models (Ollama and others) only in local development: `ALLOW_PRIVATE_PROVIDER_URLS=true`. Off in production: the settings refuse the switch when `ENVIRONMENT=production`. The Docker image defaults to `ENVIRONMENT=production`, so this refusal fails closed. **Accepted development-only risk:** with the switch on, the connection check for `custom` uses `private_ai_transport()`, a transport **without the SSRF guard** (`http`, private hosts and any port allowed). The redirect refusal, size cap and header allowlist still apply. Only a developer who sets the variable on their own machine is exposed.
4. Tests cover at least: `127.0.0.1`, `127.1`, `0.0.0.0`, `[::1]`, `2130706433`, `0x7f000001`, `169.254.169.254`, `10.0.0.1`, `192.168.0.1`, `[fd00::1]`, `::7f00:1`, `fec0::1`, `ff02::1`, `::ffff:224.0.0.1`, `64:ff9b::a00:1`, and hostnames that resolve to loopback.
5. The loggers `httpx2` and `httpcore2` (and `anthropic`, `openai`) stay at `WARNING` (they log request URLs at `INFO`). Outbound errors are mapped to our codes; their text (URL, IP address) is never logged or returned. Implementation: `app/net/` (ADR 0012).

## T3. Contract data leak

Threats: files on server disk, logs, error trackers, server cache, the AI provider, shared computers.

Controls:

1. Files are processed in memory. Any temporary file a library needs is deleted in `finally`. Uploads are raw bytes (`application/octet-stream`) with no file name in the URL, headers or body (ADR 0010). The browser sends them with `credentials: "omit"`, `redirect: "error"` and `cache: "no-store"`; tests pin these options.
2. Logs contain no content: only sizes, counts, durations and error codes.
3. No external error tracker in v1. If added later, it must scrub content.
4. API responses carry `Cache-Control: no-store`.
5. The UI warns that contract text goes to the provider chosen by the client.
6. Browser (ADR 0013): "Save results in this browser" is off by default; turning it off deletes saved results; "Clear all" removes app keys and databases; 90-day retention; caps fail closed; other tabs stop writing at once (`storage` event, setting re-read before every write); at start-up with history off the database is deleted again. Saved results hold placeholders, never the mapping.
   - **Turning history off is always possible,** also when the store is unavailable: the setting key is removed first, then the database is deleted.
   - **Rule for stage 10:** the app must subscribe its store to `subscribeHistoryChanges` and switch to `DisabledCacheStore` when the setting changes in another tab.
   - **Residual risk:** IndexedDB is not encrypted. Anyone with access to the browser profile can read saved results. The UI warns about shared computers. Where `indexedDB.databases()` is missing, "Clear all" deletes only `aic-cache`.
7. Extracted text is kept in in-memory React state only; never in storage, URLs, logs or announcements; dropped when the file is removed. File hashes and text hashes live only in memory, are dropped with the row and are never sent to the server. Duplicate detection is advisory and fails open (a hash failure shows no warning); it is not a security control.
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
2. **Clean input:** Layer 1 runs in one module, `backend/app/textclean/`, for `/api/extract` and `/api/segment`. Symbol-font checkboxes are mapped first; default-ignorable, Cf, Co, Cs, Cn removed by a checked-in table, generated and pinned to Unicode 15.1.0 (`backend/scripts/gen_ignorable_table.py --check` fails if the table differs); line breaks normalized; NFC; cleaning is idempotent. The backend Python version is pinned to 3.13 (`backend/.python-version`, same as the Docker image). A Python upgrade that changes the Unicode version fails the generator check, and the table must be regenerated. Other scripts kept and flagged; NFC for text, NFKC + confusable skeleton only for matching; PDF and DOCX text dropped only when provably invisible, borderline and overlapping text kept and flagged; removed text shown in the preview and reported as 🔴 "contains hidden text".
3. **Detect and flag:** versioned pattern file, also run on suggested and custom topics; heuristic hits 🟡 and block green for that clause; high-confidence classes (special or role tokens including gpt-oss harmony tokens, our tags, hidden instruction text, instruction plus rating words) 🔴 and remove all greens of the document; model reports accepted only from single-document calls.
4. **Map-reduce prompts:** one document per call for tagging and rating; schema-first topics with typed attributes, proposed for custom topics without any document text and confirmed by the client (`ConfirmedTopic`); comparison by code from attribute values; `text` attributes shown side by side for the client; no model call receives text of two documents, directly or through summaries (policy and wire tests); random per-block nonce in both tags; all special tokens and tag look-alikes neutralized; sandwich rules; fixed transform order with an offset map.
5. **Code-checked output:** strict schema; global-override markers cap every green of the document; model tags that push a topic over its cap are dropped, and a topic not analyzed in one document shows 🟡; repair never sends previous model output back; every finding needs a verbatim quote; quotes expanded to full sentence or clause; green needs a minimum-length quote outside suspicious spans, a deterministic exception rule the model cannot lift, a bounded cross-reference check (depth 1, at most 5 clauses), and matching numbers with units; missing topics computed by code; keyword tags cannot be removed by the model; "Other" clauses scanned and rated.
6. **Limits:** no tools, network, memory, keys or mapping for the model; hard token cap including repairs and reasoning; linear-time patterns inside the limited parsing subprocess; caps on clauses, tags and entities. **Every cap fails closed:** the document is rejected or the topic is "not analyzed" with a reason; nothing is truncated silently.
   **Clause segmentation (ADR 0014):** segmentation runs in the sandbox (worker kind `segment`); the parent never parses the body. Patterns and the algorithm are linear-time (running lines found by hashing, patterns applied per line). Caps: 2,000 clauses and 20,000 characters per clause; long clauses are split, never truncated. Abuse rules: a line longer than 120 characters, a clause-start line or a heading repeated on every page is not collapsed into a running line; an early or mid-document "Signatures" heading followed by numbered clauses does not make them `requisites`. Running clauses are rated like body clauses. The browser rejects a reply whose spans leave non-whitespace text uncovered (fails closed). Stage 11 eval case: a harmful sentence repeated on every page.
7. **Adversarial eval gate:** attack success measured against clean twins over N ≥ 3 runs; held-out set; adaptive red-team at stage 12; for AI-layer changes the tech lead records the eval result on the PR head in the PR; eval secrets per T8.
8. **Placeholder look-alikes (stage 5b, ADR 0015):** the detector in `/api/segment` neutralizes text that looks like one of our placeholders: the brackets (`[`, `]`, and full-width forms) become `⟦` and `⟧` in the returned blocks. The match runs on the confusable skeleton, so Cyrillic or Greek look-alike letters are caught too. The neutralized spans are returned in `neutralized`, and the clause gets a warning. A real placeholder in a document can then come only from the browser's masking.
9. **Layer 2 and topic text (stage 7, ADR 0017):**
   - **Layer 2 is implemented** in `backend/app/injection/` (versioned `PATTERNS_VERSION`, hits with spans). It matches on the NFKC + confusable skeleton view with linear-time patterns. It covers stems and synonyms of instruction, ignore and rating words, declined forms (datives), AI and model names, role and special tokens, tag and placeholder look-alikes, and colour ratings ("rate it green"; not "Green Card"). The eval found two real bypasses in this layer; both were fixed and are in the eval attack list.
   - **Topic text rules** (`app/topics/safety.py`): Layer 1 idempotence and NFC, grammar and length caps, no placeholder look-alike (also on the skeleton), identifier detector, Layer 2, and the meta-word **combination** rule 6 (`app/injection/meta.py`; never a single word). A refused topic gives `topic_flagged` (with the `field`), `topic_contains_identifier` (with spans, never the value) or `invalid_topic_text`. Attribute ids, value ids, side and domain are scanned by Layer 2 as words, because a model can read them.
   - **Best effort.** Layer 2 and rule 6 are phrase lists and can be bypassed. The guarantees are structural: ratings are computed by code, directions come only from the catalog or the client, and one document goes into one AI call. A bypass can steer a topic name, but it cannot rate anything.
   - **Model replies that the browser stores** (suggested topics, proposed attributes, synonyms) pass the server topic safety pass first. When the browser loads them from `localStorage` or from an imported file, it checks them again with the import rules: size cap 256 KiB, strict schema without extra keys, no `__proto__`/`constructor`/`prototype` keys, and the ADR 0017 caps. Invalid content is dropped. The server re-runs `confirm_topic()` on every request, so the browser is never trusted.
   - Eval: `backend/eval/topics/` measures the false-positive rate on honest topic names and the leaks of an adversarial Contract B (recorded mode in CI). Open: live numbers with a real model (stage 11).
10. **Tagging cannot hide a clause (stage 8, ADR 0018; `app/tagging/`):**
   - **Keyword first.** Code tags clauses by topic synonyms on the NFKC + confusable skeleton view (headings included) before any model call. The model only adds tags. A model answer that omits a keyword tag changes nothing. A cap never removes a keyword tag.
   - **"Other" is rated.** A clause with no tag goes to "Other". Code scans every "Other" clause with the checked-in risk-term list (EN/UK/RU) and returns the hits. Stage 9 rates all "Other" clauses; if it cannot, the document is incomplete and gets no greens.
   - **Caps fail closed.** At most 5 model tags per clause (reason `clause_cap`). More than 60 model-tagged clauses added to one topic: all model tags of that topic are dropped (`model_tags_dropped`), and those clauses go to "Other". More than 120 keyword clauses for one topic: the topic is `not_analyzed` (`too_many_clauses`), and its clauses are also in "Other". The keyword step has a budget of 1,000,000 steps; above it the request is refused with `keyword_budget_exceeded` (never continued with empty keyword tags).
   - **Missing-topic findings** ("the contract does not mention X") are produced only when tagging was complete for the document (no `model_tagging_incomplete`) and the topic is neither `model_tags_dropped` nor `not_analyzed`. Such a finding is never green.
   - **Layer 2 on clauses.** Hits are returned per clause. A hit never makes the clause disappear.
   - **Signature.** `/api/tag` signs the model and check tags (HMAC over the document digest, `tagging_version` and the tag hash). Stage 9 recomputes keyword tags, "Other" and Layer 2 itself and accepts only signed model/check tags and client-added tags.
   - Eval: `backend/eval/tagging/` (recorded mode in CI): keyword recall 0.81, precision 0.89, hidden clauses 0, plus two adversarial contracts (a clause that tells the tagger to skip it; a topic flood). Open: live numbers (stage 11).

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

1. Per-IP rate limit in memory with our own fixed-window limiter (`app/limits/`, no slowapi): a bounded table (at most 50,000 keys) that fails closed when it is full of fresh keys. Rolling windows use a monotonic clock; aligned daily windows use wall time and reset at 00:00 UTC.
2. Concurrent analysis limit (initial: 2) because of 512 MB RAM.
3. Request body size limit at the server: `BodySizeLimitMiddleware` on every route (64 KiB for JSON routes, 10 MiB for `/api/extract`); a `Content-Length` with more than 18 digits counts as too large. `/api/extract` also has the `ExtractionLimiter` (2 slots per process, `503 busy` with `Retry-After`, exposed by CORS), a body deadline of 60 s and a minimum average rate of 32 KiB/s after 5 s (`408 upload_timeout`), `Connection: close` on every response sent before the body is read, and `Transfer-Encoding` rejected (`411`). The limiter counts per process, so the backend runs as a single worker: `--workers 1` is explicit in the Dockerfile `CMD`, so `WEB_CONCURRENCY` cannot raise it (policy test). `POST /api/segment` holds an extraction slot from the same pool of 2, has a 4 MiB body limit for its exact path, and uses the same body deadline and minimum rate as uploads. `POST /api/safety-check` does the same: it holds a slot from the same pool (`503 busy` when full), has its own body limit (`SAFETY_MAX_BODY_BYTES`, that path only), and uses the same deadline and minimum rate. The parent never parses its body; the sandbox child does.
4. At most 1 extraction slot per client key (client key derived as in control 6; `MAX_EXTRACTIONS_PER_CLIENT`, default 1), on top of the shared pool of 2. It covers `/api/extract`, `/api/extract/google-doc`, `/api/segment` and `/api/safety-check` (`503 busy` with `Retry-After`). **The stage 13 release blocker for this control is closed (S6-T3).** `POST /api/extract/google-doc` takes a slot before it reads its JSON body (so a busy server answers `503` first); a client can hold a slot for up to `GOOGLE_BODY_TIMEOUT_SECONDS` (5 s) by sending that body slowly, and for up to the fetch deadline (20 s) while the server waits for Google. The per-key limit means one client key cannot hold both slots. Residual risk: many client keys (a distributed attacker) can still fill the shared pool.
5. CORS allows only our frontend origin. CORS protects against other websites in a browser, not against scripts. `ALLOWED_ORIGINS` holds exact `https://host[:port]` origins; `null`, paths and wildcards are rejected; production requires it to be set explicitly.
6. Per-IP limits behind Render's proxy: never trust the leftmost `X-Forwarded-For`; derive the client IP from the hop added by Render's proxy, and document it. Implemented in S6-T3 and S6-T4 (`app/limits/`): in production the client key is the Nth entry from the right of `X-Forwarded-For` (`TRUSTED_PROXY_HOPS`, default 1); in development it is the socket peer. A missing or invalid value gives the shared key `unknown`. Tiers: IPv4 as is; IPv6 by its /64 prefix for the per-minute check limit and the extraction slots; IPv6 by its /48 prefix (`daily_key`) for daily tables, the free quota and the check slot, so /64 rotation inside one allocation cannot fill a daily table or give extra calls. 6to4 (`2002::/16`) and Teredo (`2001::/32`) addresses are keyed by the embedded IPv4 address; IPv4-mapped IPv6 by its IPv4 address. `/api/provider/check`: 10 per minute and 60 per day per key, at most 1 check in flight per /48 or IPv4 key and 2 per server; the free quota is 5 calls per key and day. Aligned UTC daily windows fail closed on a backward wall-clock step (keys stay counted longer). No IP address is logged. **Stage 13 checks** `ENVIRONMENT=production` and that Render's `X-Forwarded-For` has the client address as its rightmost entry (until then this is an assumption).
7. No raw prompt endpoint. The server runs only our analysis pipeline, so it is useless as a generic AI proxy.
8. If needed later: Cloudflare Turnstile.
9. The extraction slot covers sending the response: a send deadline (30 s) cuts off a client that does not read; uvicorn `--limit-concurrency 32` caps open connections. **Release blockers for stage 13:** (a) uvicorn has no header-read timeout, so 33+ sockets that send a partial header make every route answer 503 (slowloris); (b) a cut-off connection is closed, not aborted, and keeps about 4 MiB of kernel send buffer until the client closes it. Check whether Render's proxy buffers headers and responses; if not, add a header-read timeout and abort cut-off connections, and add kernel socket buffers to the ADR 0011 memory budget.
10. **Topic AI endpoints (stage 7):** `POST /api/topics/suggest`, `/propose-attributes` and `/expand-synonyms` share the AI slots of `/api/provider/check` (1 call in flight per client key, 2 per server; `503 busy` with `Retry-After`). Limits per client key: `TOPICS_PER_MINUTE` (10) and `TOPICS_PER_DAY` (60), the three endpoints together. Body caps: 16 KiB for propose and expand; suggest uses the safety-check cap and a cap of 60,000 characters of masked clause text (`document_too_large_for_suggest`). A total deadline of 60 s per AI call (`TOPIC_AI_DEADLINE_SECONDS`) releases the slot on timeout. `suggest` runs its safety pass under the extraction slots and releases them before the AI call, so a slow provider never holds an extraction slot. No raw prompt endpoint exists: each endpoint builds its own fixed prompt.
11. **Tag endpoint (stage 8, ADR 0018): `POST /api/tag`** takes one masked document per request.
   - It holds an extraction slot for the sandbox work (safety pass, keyword tags, risk terms, Layer 2) and releases it before any AI call. It shares the AI slots and the per-key limits of the other AI endpoints (`503 busy` with `Retry-After`).
   - Size limits fail closed before any AI call: `document_too_large_for_tagging` (characters above `tag_max_document_chars`, or more than 60 batches), `no_topics`, `duplicate_topic`, `keyword_budget_exceeded`.
   - Batches: at most 12,000 characters and 40 clauses each, at most 60 per request. The whole worst case (all batches, all check calls, one repair each) is reserved before the first call. Each AI call has its own deadline (`TAG_CALL_DEADLINE_SECONDS`, 60 s), and the overall deadline is 5 minutes (`TAG_DEADLINE_SECONDS`). A deadline hit keeps the finished calls and adds the reason `timeout`.
   - The reply holds ids, enums, counts and offsets only. Logs hold counts and error codes only.

Browser controls:

1. At most 2 requests (checks and clause splits together) are in flight in the whole form: one shared budget. A `busy` answer is retried at most 3 times, and `Retry-After` is limited to 1–10 s. The browser reads a `200` body up to 4 MiB + 64 KiB (the extraction result) and any other body up to 4 KiB.
2. The preview caps blocks and characters per file; client validation repeats every server list cap.

## T7. Google Docs import

Threat: the import makes our server fetch a URL (SSRF, open proxy), leaks the document link, or brings a different or oversized file into the pipeline.

Controls (S3-T6, ADR 0012):

1. **Public link only.** The browser accepts only `https://docs.google.com/document/d/<ID>/...` and sends only the ID, in a JSON body, to `POST /api/extract/google-doc`. The server validates the ID with `^[A-Za-z0-9_-]{25,100}$` and builds the export URL `https://docs.google.com/document/d/<ID>/export?format=docx` itself. No URL from the client is ever fetched.
2. **SSRF guard** (T2 controls, ADR 0012) on every hop: DNS resolved once, public addresses only, connection to the checked IP, TLS verified for the hostname, no proxy from the environment.
3. **Redirects:** at most 3, each checked: `https`, port 443, no user info, host `docs.google.com` or matching `^doc-[a-z0-9-]{1,60}-docs\.googleusercontent\.com$` (not other user-content hosts). The cookie jar is cleared before each hop. A redirect to `accounts.google.com` means the document is not public. Any other target is refused.
4. **Request:** fixed headers only (`User-Agent`, `Accept`, `Accept-Encoding: identity`). No cookies, no header from the incoming request. A response with any `Content-Encoding` is refused (no decompression bomb).
5. **Limits:** body streamed with the file limit (10 MiB), connect timeout 5 s, total 20 s. The extraction slot is taken before the JSON body is read (body deadline `GOOGLE_BODY_TIMEOUT_SECONDS`, 5 s, `408 upload_timeout`) and held for the whole request. The body must be a DOCX by magic bytes; then the same sandbox extraction as an upload.
6. **The ID works like a password** for that document: never logged (the `httpx` request log is off, T2 point 5), never in a URL of our API, never in an error message, never stored in the browser. In the browser the ID is kept in component memory (a `Map` by row id) only while its row exists: to send the request, retry on `busy` and refuse duplicates. It is dropped when the row or its contract is removed. It never enters reducer state, announcements or storage. The ID is validated with a full match (Python `$` also accepts a trailing newline).
7. **Metadata:** the Google title (`Content-Disposition`, `docProps`) is never read (ADR 0008 point 8).
8. **Private documents (Google Picker) are not in v1:** the Picker needs third-party scripts (CLAUDE.md rule 8). The person exports the document as DOCX or PDF and uploads it.
9. **Stage 13 deployment blocker:** a per-IP rate limit for this endpoint, because it makes outbound requests.

## T8. Supply chain

Example: on 2026-03-24, malicious LiteLLM 1.82.7 and 1.82.8 were published to PyPI. They stole LLM API keys, cloud keys, SSH keys and `.env` secrets. The attackers got publishing access through the project's CI/CD.

Controls:

1. Minimal dependencies. No LiteLLM. Official `anthropic` and `openai` SDKs only.
2. Lock files with hashes: `uv.lock`, `package-lock.json`. Install only with `uv sync --locked` and `npm ci`. Docker base images are pinned by digest and updated by Dependabot. CI runs pip-audit with the OSV source. Docker base images, including `frontend/Dockerfile.dev`, are pinned by digest. There is no `# syntax=` directive, or it is pinned by digest. `COPY --from=` and `RUN --mount=...from=` use only stage aliases or digest-pinned images. Dependabot takes digest and patch updates only; Python, Node and uv minor and major upgrades are planned changes.
3. A new dependency needs approval of the tech lead and `security-reviewer`.
4. Updates through Dependabot pull requests: version updates monthly, one grouped PR per ecosystem, cooldown 14 days; the tech lead reviews the batch at the end of a stage. Security updates are ungrouped and not delayed (the repository setting "Grouped security updates" stays off). Residual risk: a fix without a GitHub advisory can wait up to about 44 days. Ignore rules use only `update-types` (never `versions:`), so they never suppress security updates. npm majors and Python/Node/uv minor and major versions are planned upgrades, reviewed every stage (`npm outdated`, `uv tree --outdated`). Dependabot alerts, malware alerts and security updates are enabled in repository settings (malware alerts since 2026-10-29).
5. CI: pip-audit, npm audit, CodeQL (Python and TypeScript). CodeQL languages: `python`, `javascript-typescript`, `actions`; query suite `security-extended`.
6. GitHub Actions pinned by full commit SHA; minimal `permissions:`. Workflow triggers are limited to `push`, `pull_request`, `schedule`, `workflow_dispatch`. No `pull_request_target`, no `workflow_run`. Every `actions/checkout` has `persist-credentials: false`. No `${{ }}` inside `run:`, comment lines included; pass values through `env:`. Job-level permissions are only `read`/`none`, except `security-events: write` for CodeQL. These rules are enforced by `backend/tests/test_repo_policy.py`.
7. GitHub secret scanning and push protection enabled.
8. Tesseract language data and fonts are built into the bundle, not loaded from a CDN. `scripts/copy-ocr-assets.mjs` checks every language file (`4.0.0_best_int`) against a SHA-256 manifest before it copies anything; a mismatch fails the build. `pdfjs-dist` has the optional dependency `@napi-rs/canvas`: it installs native binaries in dev and CI only and is never shipped to the browser.
9. `frontend/.npmrc` sets `ignore-scripts=true` (do not remove it without security review); npm is pinned with `packageManager`. The Vite dev server is never exposed beyond localhost. The Compose frontend dev container runs as `node` (uid 1000) with a read-only root filesystem, no capabilities, `no-new-privileges` and `npm ci --ignore-scripts`. Residual risk: the `./frontend` bind mount is read-write, so on a Linux host where the developer is uid 1000, dev-server code can change the source tree. Planned mitigation: Compose Watch `sync`.
10. **Eval secrets (ADR 0009 Layer 6):** the eval never runs on `pull_request`. The GitHub `eval` environment has required reviewers and a deployment branch policy limited to `main` (`workflow_dispatch` runs the workflow file of the dispatched branch). PR-head evals run locally with a separate eval key with a low spending limit, never the production free-model token.
11. **Test-only code stays out of the bundle:** a CI step after `npm run build` fails if `frontend/dist/` contains `fake-indexeddb` or `FDBFactory` (`fake-indexeddb` 6.2.5 is a dev dependency, imported only in tests).
12. **Docker build context (stage 7):** the backend image is built from the repository root (`context: .`, `dockerfile: backend/Dockerfile`), because it also holds `shared/topics/`. `backend/Dockerfile.dockerignore` is an allowlist: it excludes everything (`*`), then admits only `backend/pyproject.toml`, `backend/uv.lock`, `backend/log_config.json`, `backend/app/` and `shared/topics/`. So a larger context cannot send `.git`, tests, docs, `.env` files or other source into the build. Stage 13: Render must use the repository root as build context and `backend/Dockerfile` as Dockerfile path.

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

Deployed policy (stage 1) adds: `frame-src 'none'`, `font-src 'self'`, `manifest-src 'self'`, `require-trusted-types-for 'script'; trusted-types default` (stage 3), `worker-src 'self'` (no `blob:`), `Cross-Origin-Resource-Policy: same-origin`, `X-Frame-Options: DENY`. The exact policy lives in `frontend/public/_headers` and is pinned by `headers.test.ts`.

Stage 3 (OCR), as deployed:

- `new Worker(url)` and `importScripts()` are Trusted Types sinks. The CSP has `trusted-types default` and `worker-src 'self'`. The `default` policy (`createScriptURL` only) allows an exact URL list under `/ocr/` (pdf.js worker, Tesseract wrapper and worker, LSTM core files), not `/assets/`. Our classic Tesseract wrapper (`/ocr/tesseract-worker.js`) installs the same policy in the worker scope; a test keeps both lists equal.
- Everything is self-hosted: Tesseract `workerPath`, `corePath`, `langPath`, `workerBlobURL: false`, and pdf.js `workerPort`, `cMapUrl`, `standardFontDataUrl`, `wasmUrl`, `iccUrl`. pdf.js is the `legacy` build (the modern build needs newer browser APIs). No `quickjs-eval.*` and no `pdf.sandbox`. pdf.js 6 has no `isEvalSupported` option; a test checks that the copied pdf.js files contain no `eval(` and no `Function(` except the core-js `globalThis` fallback, which CSP (no `'unsafe-eval'`) and the Trusted Types policy (no `createScript`) also block. pdf.js `verbosity` is `ERRORS` (warnings can contain document data). Each page has a 60 s limit; document load and engine start have a 60 s limit.
- Turnstile (ADR 0007, ADR 0016 point 7) is isolated on its **own origin** (a second Cloudflare Pages project). The Cloudflare script never runs in the app origin, so the app CSP does not list `challenges.cloudflare.com`. The app CSP adds only the frame origin to `frame-src` (`__TURNSTILE_FRAME_ORIGIN__` in `frontend/public/_headers`, replaced at deploy); `script-src` is unchanged.
- The frame page has its own CSP (`frontend/turnstile/public/_headers`): `default-src 'none'; script-src 'self' https://challenges.cloudflare.com; frame-src https://challenges.cloudflare.com; connect-src https://challenges.cloudflare.com; style-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors __APP_ORIGIN__; upgrade-insecure-requests`, plus `Referrer-Policy: no-referrer`, HSTS, `nosniff` and `Permissions-Policy`. `__APP_ORIGIN__` is replaced at deploy with the exact app origin. The frame page has **no Trusted Types rule**: accepted, because the frame holds no secrets and no app storage and the Cloudflare script is not Trusted Types compatible.
- The app embeds the frame as `<iframe sandbox="allow-scripts allow-same-origin" referrerpolicy="no-referrer">` only in free mode. `postMessage` checks: the frame sends to the exact app origin only (`VITE_TURNSTILE_APP_ORIGIN`) and accepts only an exact `reset` from the app origin and its parent window. The app accepts a message only if `event.origin` equals the frame origin, `event.source` is the `contentWindow` of the iframe it created, and the shape is exact (`{ type: "turnstile-token", token: string ≤ 2048 }`, plus the `expired` and `error` types). Tests cover other origins, other sources and other shapes.
- An automated Playwright CSP smoke test (no `securitypolicyviolation`) runs in CI at the e2e stage.

Backend: `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, CORS allowlist.

## T10. Free default model (ADR 0007)

Threats: theft of our Cloudflare token; bots burning the shared free quota; using free mode as a free AI proxy; billing surprises.

Controls:

1. `CF_AI_TOKEN` is scoped to Workers AI only. It lives only in Render secret env vars. It is never sent to the browser, never logged, never part of an error. It is typed `SecretStr` and covered by the log canary test.
2. The Cloudflare account stays on the Workers Free plan: above 10,000 Neurons per day requests fail instead of being billed.
3. Free mode requires a valid Cloudflare Turnstile token, verified server-side, one use per analysis. The server accepts a token only if `success` is true, `hostname` equals `TURNSTILE_EXPECTED_HOSTNAME`, `action` equals `TURNSTILE_ACTION` (default `check`) and `challenge_ts` is at most 300 s old (at most 5 s in the future). A used token is kept as a SHA-256 hash in a bounded replay table (at most 10,000 entries, lifetime `TURNSTILE_REPLAY_SECONDS`, at least 305 s, default 600 s); when the table is full, new free calls are refused (fail closed). The siteverify call goes through `app/net/` with the secret only in the body and no client IP. A failed Turnstile check (`403 turnstile_failed`) is **counted** against the check limits and not refunded, so a flood of bad tokens is bounded.
3a. Production settings (`ENVIRONMENT=production`): the four free settings (`CF_ACCOUNT_ID`, `CF_AI_TOKEN`, `TURNSTILE_SECRET_KEY`, `TURNSTILE_EXPECTED_HOSTNAME`) are **all set or all unset**, else startup fails; Cloudflare's Turnstile test secrets (`1x…`, `2x…`, `3x…`) are refused. Without them free mode answers `503 free_mode_unavailable`.
4. Per-IP daily limit and an in-memory global daily Neuron budget below the free allocation (`FREE_NEURON_BUDGET`, 1 to 9999, default 8000). Both reset at 00:00 UTC. A request counts against the per-key limit only after cheap validation and Turnstile; a refusal by shared state (budget, full table) counts nothing.
5. Stricter size limits in free mode (initial: 2 contracts and 30 pages per analysis).
6. Free mode runs only our analysis pipeline with a fixed model; no raw prompts, no client-chosen model.
7. Quota exhausted → `429` with code `free_quota_exhausted`; the UI offers the client's own key.
8. The UI states which provider processes the text in free mode and its data policy.
9. **Free pass for topic calls (stage 7, ADR 0017 point 6; `app/limits/free_pass.py`):**
   - One Turnstile token per call would mean a challenge per topic. A verified token at the first free topic call returns a **free pass** `v1.<aud>.<expiry>.<client-key-hash>.<nonce>.<mac>` in the reply field `free_pass`.
   - The MAC is HMAC-SHA256 with a **per-process key** (`secrets.token_bytes(32)` at startup, never stored or logged). A restart invalidates every pass (fails closed). There is no new secret.
   - `aud=topics`: `/api/provider/check` and every stage 9 endpoint refuse it (`unexpected_free_pass`). The pass is valid for 15 minutes, only for the same client key (IPv4 or IPv6 /48), and for at most 20 calls (`FREE_PASS_MAX_CALLS`).
   - **One live pass per client:** a new Turnstile solve replaces the old pass. Calls are counted per nonce in a **bounded table** (`FREE_PASS_MAX_ENTRIES`, at most 10,000). When it is full of live passes, new passes are refused (`free_pass_unavailable`, fail closed).
   - The pass travels only in the `X-Free-Pass` header (at most 256 characters, exactly one header, compared with `hmac.compare_digest`). It is never logged. A request with a pass must not also hold a Turnstile token.
   - **Quotas:** a separate per-/48 topic quota (`FREE_TOPIC_CALLS_PER_IP_PER_DAY`, 40 per day) next to the analysis quota of 5. Topic calls may use at most **30 %** of the daily Neuron budget (`free_quota_exhausted` above it), so analyses keep the rest.
   - **Worst-case reservation:** before the AI call the server reserves the worst-case Neurons of the job (input, output cap and one repair call) against the topic quota, the global budget and the 30 % share. After the call it settles with the usage the provider reported. When the provider reports none, the reservation stands. A call where the model did no work (an error code of the `AI_NO_COST` set, or a connection config error) is refunded: the quota call and the pass call.
   - Residual risk: the pass allows 20 calls per challenge; the per-process key means a restart costs each client one new challenge.
10. **Analysis pass (stage 8, ADR 0018 point 7; `aud=analysis`):**
   - The first `/api/tag` call of an analysis verifies one Turnstile token and returns an analysis pass (same format and per-process HMAC key as the topic pass). It is valid for 30 minutes, for the same client key (/48), and covers one analysis: at most 2 documents in free mode and their tag, check and stage 9 calls. It travels only in the `X-Analysis-Pass` header.
   - Audiences are strict: the topic endpoints and `/api/provider/check` refuse `aud=analysis`; `/api/tag` refuses `aud=topics`. There is one live pass per client per audience, in a bounded table that fails closed.
   - Starting the pass charges the per-IP analysis quota (5 per day) once. Every call reserves its worst-case Neurons and settles with reported usage. The analysis share is the 70 % not reserved for topics. Each pass has a Neuron cap and a call cap, so re-tagging cannot spend the whole share.
   - Free size limits (2 documents, 30 pages) are counted from characters (3,000 per page). The pass records the digests of at most 2 documents; a third digest is refused.
   - **Browser:** "Clear all", or removing a document, aborts the `/api/tag` request in flight and settles any pending Turnstile wait with no later call. A document removed during a run is never sent. Results and status are emptied. Client tag caps (5 non-keyword tags per clause, 120 clauses per topic, selected topics only) are enforced in `setClientTags`, not only in the UI.

## T11. Identity leakage to AI providers (ADR 0008)

**Threat.** Identifiers from contracts (names of companies and people, codes, accounts, addresses, contacts, document numbers, vehicle and health data) reach an AI provider — including our free default provider — and are logged, retained or used for training. Side channels: file names, document metadata, PDF running headers and footers, custom topics and side text, wire-level SDK fields, cache, exports, logs, SSE and errors.

**Controls:**

1. All identifier classes in ADR 0008 are replaced by document-scoped typed placeholders (`[A.ORG_1]`) before any AI call; placeholder look-alikes in the source are neutralized; defined terms equal to masked names are masked.
2. Detection runs on de-hyphenated text and a confusable skeleton, inside the limited parsing subprocess, with linear-time patterns and caps; PDF running headers and footers are detected and masked or dropped.
3. The requisites section is processed line by line: only lines made entirely of identifiers, labels, role words and signature lines are dropped; any line with a condition is kept, masked, analyzed and flagged 🟡. Dropped lines are visible in the preview and counted as "not analyzed".
4. Mandatory preview; high-precision classes cannot be unmasked by the client. Checksummed codes are high-precision only with a context keyword (or inside the requisites section) and never match a number followed by a currency, `%` or a unit; a masked token next to an amount flags its clause 🟡. Detection caps fail closed (`too_many_identifiers`).
4a. **Clause headings are copied text.** A heading can hold an identifier, so stage 5b must mask headings like any other text.
5. The mapping stays in the browser memory; it is never sent to AI endpoints or providers, never logged and never stored (ADR 0013 point 9a: a cached result holds placeholders only); exports use placeholders by default.
6. **Fail-closed safety pass:** a detector version mismatch is rejected (`detector_version_mismatch`); idempotent input cleaning is only a check (`input_not_clean` if it would change anything, offsets never mapped); high-precision hits return `unmasked_identifier` with offsets, the browser pre-masks them and asks for a new confirmation; the server never changes confirmed text silently.
7. **Type gate:** a frozen dataclass with a runtime sentinel, created only by `safety_pass()`; never a request model; the `AIProvider` port takes no `str`; topics and side text become `PseudonymizedText` or `ConfirmedTopic`; repair never re-sends model output; an AST policy test enforces this, including `__new__` and `object.__setattr__` on gate types.
8. File names, PDF Info and XMP, DOCX `docProps`, embedded files and Google titles are never parsed into text, never logged, never sent. Uploads are raw bytes (`application/octet-stream`) with no file name in the URL, headers or body (ADR 0010). The browser sends them with `credentials: "omit"`, `redirect: "error"` and `cache: "no-store"`; tests pin these options.
9. Cache key = SHA-256 of the final masked text plus prompt and model versions. File and text hashes (stage 4) live only in browser memory, are dropped with the row and are never sent. Duplicate detection is advisory and fails open; it is not a security control.
10. **AI payload canaries on the wire** under the real `anthropic` and `openai` adapters (`httpx2` mock transport through our client wrapper): URL, headers and the whole body, for `check()` and `complete_json()`; plus negative checks for logs, SSE, errors, `422` and the browser's outgoing analysis request. As implemented (`backend/tests/ai/test_ai_wire_canary.py`): presets `anthropic`, `openai` and `custom` (the other presets share the OpenAI-compatible adapter); documents from the real safety pass; canary values in every SDK environment variable of T1 control 10; the key only in the auth header; one document per request; no `tools` field; the model ID only in the body (`test_ai_wire.py`). The Turnstile `siteverify` call and the free path (`CF_AI_TOKEN` only towards `api.cloudflare.com`) are checked in `backend/tests/check/`. The browser's outgoing analysis request does not exist yet (stage 9).
10a. `PseudonymizedText.source` is the `document_digest` of the checked document. Whoever builds a `PseudonymizedText` (the server safety pass, from stage 7) must compute it with `document_digest`, never take it from a request. `AIRequest` refuses a text whose `source` differs from the digest of its document (`ValueError`). No builder exists yet in stage 6.
11. The eval measures recall and precision per class and per language.
11a. **Tagging (stage 8):** `/api/tag` accepts only a document that passes the full safety pass (the same pass as `/api/safety-check`, run again in the sandbox). The tagging and check prompts hold masked clause text of one document and topics as opaque indexes (title and short description only; no synonyms, no attribute ids). Synonyms are used only by code. Tests in `backend/tests/tag_api/` cover the two prompts and the wire (security canaries). The browser keeps the confirmed masked documents in a small in-memory store only (never IndexedDB, `localStorage` or `sessionStorage`); "Clear all" empties it.
12. **`ConfirmedTopic` is the only cross-document string (stage 7, ADR 0017 point 3, `app/pseudo/gate.py`).**
   - It holds the whole confirmed definition (domain, topic id, title, description, side, frozen `ConfirmedAttribute` tuple, synonyms). It is created only by `confirm_topic()`, never by a request model, and is not bound to a document. The AST policy test covers it.
   - A topic that is not from the catalog is capped at **4 KiB** (UTF-8, all fields); above it gives `topic_too_large` (fails closed). Topics are never masked: an identifier in topic text is refused with `topic_contains_identifier` and offsets, and the client removes it.
   - **Suggestion descriptions are UI-only.** They never enter a `ConfirmedTopic` or a prompt. When the client accepts a suggestion, its own description stays empty.
   - **Synonyms are never sent to a model.** They are for keyword tags by code (stage 8). The prompt of a topic holds the title, the description, the domain, the side and the attribute labels and values; ids of attributes and values stay out of the prompt text.
   - **Directions decide ratings by code**, so only the catalog or the client sets them. A model-proposed attribute starts with direction `none`; the server refuses a non-`none` direction with `direction_source: "catalog"` outside the catalog (`invalid_direction`). This is an honest-UI rule plus a default that fails to neutral.
   - Value ids, side and domain are scanned by Layer 2 as words. Catalog topics are compared with the server's own catalog (`catalog_topic_changed`).
   - Caps per analysis request: 30 catalog, 10 suggested and 10 custom topics (`too_many_topics`; `app/topics/selection.py`, used from stage 9).
   - Suggest sends one document per call. Its input is checked by the same safety pass as `/api/safety-check`, with a cap of 60,000 characters.

**As implemented in stage 5b (ADR 0015):**

- **Detector:** runs in `/api/segment` (sandbox) and returns `detector_version`, `entities`, `requisites` and `neutralized`. The browser shows a mandatory preview; the client checks every replacement before analysis.
- **`POST /api/safety-check`:** the sandbox child checks in this order: (1) detector version (`409 detector_version_mismatch`); (2) acknowledged clause ids and size caps; (3) Layer 1 idempotence (`input_not_clean`); (4) placeholder grammar on the text and on the confusable skeleton (`invalid_placeholder`); (5) full detector re-run, plus partial-mask and keyword-digit scans; (6) acknowledged spans. A hit passes only if it is not high-precision and it equals an acknowledged span or lies fully inside one; the browser sends outermost spans only. Any other hit gives `422 unmasked_identifier` with offsets only. If all checks pass, the answer is `200` with `ok`, `detector_version` and a SHA-256 `digest` of the document. Errors other than the version mismatch are `422`; a timeout is `504 safety_timeout`.
- **Gate types:** `PseudonymizedDocument` and related types are in `app/pseudo/gate.py`; the AST policy test enforces point 7. The canary harness is in `backend/tests/canary/`.
- **Eval (held-out split, aggregate numbers only):** recall en 64/66, ru 64/64, uk 57/57; precision 1.000 in every language; 0 `must_not_mask` violations. One gate is an expected failure (xfail): en PERSON "normal" 0.929 (a Cyrillic name in brackets after a Latin form).

**Residual risks of stage 5b:**

- A one-word ORG without quotes or a definition is not masked. The preview is the final control.
- Low: a fail-closed false positive. The text `[A.ACCOUNT_1]; 4.2.` is refused by the safety check.
- `ЄДРПОУ 34123457 кв. 5` is not detected, but the safety check refuses it (fails closed).
- Unmasked by design: a checksum-valid РНОКПП without a keyword before `шт.`, and `Код 34123457 грн` (point 4: checksummed codes never match a number followed by a unit or currency).

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
