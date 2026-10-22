# ADR 0013 — Browser cache and history

- Status: proposed (tech lead, 2026-10-22; `security-reviewer` approved the design after round 2; accepted when stage 4 is merged)
- Date: 2026-10-22
- Related: ADR 0001 (stateless, `CacheStore` port), ADR 0008 point 4 (cache key, mapping), threat model T3, T11

## Context

The server stores nothing (ADR 0001). Requirement 9 of `docs/plan.md`: a re-upload of the same contracts is detected, and the client chooses the cached result or a new analysis. The cache lives in the browser.

What a cached entry holds (stage 9 and later): the analysis result with contract quotes, with placeholders instead of identifiers. That is sensitive data in the browser profile. A shared computer is the main threat (T3).

Stage 4 builds the storage, the hashing and the user controls. Stage 9 and stage 10 write and read real results through the same port.

## Decision

1. **History is off by default** (customer decision, 2026-10-22). With history off, nothing is written to IndexedDB, and the cache always misses. The client turns history on in the settings panel. The setting is stored in `localStorage` under `aic.history` (`"on"`; any other value or no value means off).
2. **Turning history off deletes every saved entry** after a confirmation. "Off" means "nothing is stored", never "stored but hidden". Order: remove `aic.history` first, then delete the database, so no tab can re-create it.
2a. **Other tabs and start-up (fail closed).** Every tab re-reads `aic.history` before it opens the database and before every `put`. On the `storage` event for `aic.history` (or for a cleared storage) a tab switches to `DisabledCacheStore` at once. A connection closed by `onversionchange` is never reopened by that store instance. In `onupgradeneeded` the store re-reads the setting; if it is off, it aborts the upgrade transaction, so a late `open` in another tab cannot re-create the database. At start-up with history off, the app calls `indexedDB.deleteDatabase("aic-cache")`, so a deletion that was blocked or failed earlier is finished later.
3. **`CacheStore` port** (`frontend/src/storage/`). Application code depends only on the port. Adapters:
   - `IndexedDbCacheStore`: one database `aic-cache`, one object store `entries`, key path `key`, an index on `lastUsedAt`;
   - `MemoryCacheStore`: tests;
   - `DisabledCacheStore`: history off, or IndexedDB not available (private mode, blocked storage). `get` returns a miss, `put` returns `disabled`, nothing is kept.
4. **Entry:** `{ key, schema: 1, kind, createdAt, lastUsedAt, size, json }`. `json` is the data serialized with `JSON.stringify` (a string, so the size check is exact and no structured-clone types are stored); the store parses it on read. `get(key, validate)` takes a validator from the caller. An entry that fails parsing or validation, has an unknown `schema` or `kind`, or has impossible timestamps is deleted and reported as a miss. **A cached result is untrusted input:** the stage 9 validator is strict and capped like a model response, every quote is verified again against the current masked text on every hit, and the result is rendered as plain text only (`CLAUDE.md` rule 6).
5. **Retention: 90 days from `createdAt`.** Using an entry does not extend it. Expired entries are deleted at start-up and before every `get` and `list`; an expired entry is never returned.
6. **Caps fail closed.** At most 100 entries; at most 2 MiB per entry (UTF-8 length of `json`). A larger entry is not stored (`too_large`), never truncated. Over 100 entries, the least recently used entries are deleted in the same transaction as the put. A quota error aborts the transaction (`storage_full`); no partial entry stays.
7. **Clear all** first removes every `localStorage` and `sessionStorage` key with the `aic.` prefix except the UI language (`aic.lang`), so history returns to off in every tab; then it deletes the `aic-cache` database and, where `indexedDB.databases()` is supported, every other IndexedDB database of the origin. If another tab blocks the deletion, the UI asks the client to close the other tabs; the start-up delete (point 2a) finishes it later. Today the app stores nothing else: no service worker, no Cache Storage, OCR runs with `cacheMethod: "none"`.
8. **Hashing:** SHA-256 through Web Crypto (`crypto.subtle.digest`), lower-case hex. Text is normalized before hashing: Unicode NFC; CRLF and CR to LF; tabs and runs of spaces to one space; spaces at line ends removed; three or more line breaks to two; leading and trailing white space removed. Keys are built from a canonical JSON (sorted keys, no spaces) of their parts with a version field. The analysis key (stage 9) is built from the final masked text of each document (client edits included), the document order, the client's side, the topics, the UI language, the prompt version, the detector version, the provider host and the model (ADR 0008 point 4). Stage 4 ships the building blocks and tests them; it does not fix the final key layout. Hashes never leave the browser: they are not sent to the server or to any provider.
9. **No contract text in storage** (T3 control 7). Extracted text and file bytes are never written to IndexedDB, `localStorage` or `sessionStorage`. File hashes and text hashes live only in memory, like the extracted text.
9a. **The placeholder mapping is never stored** (change to ADR 0008 point 4). The key is built from masked text, so two contracts that differ only in identifiers have the same key. A stored mapping would then show the names of one contract on another. On a hit, the browser restores names with the mapping of the current session, which matches the current masked text. Stored entries hold placeholders only.
10. **No new runtime dependency.** The IndexedDB wrapper is our own small code (no `idb`). Tests use `fake-indexeddb` **6.2.5** exactly, as a development dependency only (approved by `security-reviewer`, 2026-10-22: Apache-2.0, no dependencies, no install scripts; not 6.2.6, too new and ships stray test files). It is imported only in test files; a test checks that the production bundle does not contain it.

## Consequences

- Positive: the client controls what is kept; the default is safe on a shared computer; storage can change behind the port.
- Negative: with history off (the default), the "already analyzed" dialog never appears; the client must turn history on first. The settings panel says so.
- Residual risk: IndexedDB is not encrypted. Anyone with access to the browser profile can read saved results (with placeholders, not real names) while history is on. Encryption with a key stored in the same profile would not change that, so v1 does not encrypt. The settings panel explains this in one sentence.
