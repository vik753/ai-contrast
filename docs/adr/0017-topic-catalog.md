# ADR 0017 — Topic catalog: templates, typed attributes, custom and suggested topics

- Status: proposed (tech lead, 2026-11-04; `security-reviewer` approved the design after round 2)
- Date: 2026-11-04
- Related: ADR 0008 and 0015 (gate types, safety pass), ADR 0009 Layers 2 and 3 (schema-first topics, `ConfirmedTopic`, one document per call), ADR 0013 (browser storage), ADR 0016 (AI port, free mode), threat model T5, T6, T10, T11

## Context

Stage 7 builds the topics that stages 8 (tagging) and 9 (analysis) use. Requirement 3 of `docs/plan.md`: three kinds of topics, combinable and editable before the analysis — ready templates, topics suggested by AI from the uploaded contracts, and the client's own topics. Requirement 4: the client chooses their side. ADR 0009 Layer 3 makes every topic **schema-first**: typed attributes with a direction per client side, so stage 9 compares values by code and no model ever reads two contracts.

This is the first stage with real prompts. Topic text crosses documents (it is the only string allowed in calls for different documents), so it must be short, client-confirmed, masked and free of AI-addressed text.

## Decision

### 1. Catalog format (`shared/topics/`)

- One JSON file per domain: `kasko`, `osago`, `lease`, `property_insurance`, written by `domain-analyst`, validated by a Pydantic model in `app/topics/catalog.py` and by a JSON schema test in the frontend. A `catalog_version` (hash of the files) goes into every reply and, at stage 9, into the cache key.
- **Domain:** `id`, names in `en`/`uk`/`ru`, `sides` (closed list per domain with names in three languages: `kasko` and `property_insurance`: `insured`, `insurer`; `osago`: `insured`, `insurer`, `injured_party`; `lease`: `tenant`, `landlord`), and `topics`.
- **Topic:** `id` (`[a-z][a-z0-9_]{1,47}`), names and a one-line description in three languages, `synonyms` per language (stems and phrases for stage 8 keyword tags, at most 40 per language, each at most 60 characters), and `attributes` (1–12).
- **Attribute:** `id`, labels in three languages, `type` one of:
  - `amount` (number with a unit from a closed list: `UAH`, `USD`, `EUR`, `percent_of_sum` for a share of the sum insured, `percent_of_loss` for a share of each loss),
  - `percentage`,
  - `duration` (number with a unit from `hours`, `days`, `working_days`, `months`, `years`),
  - `enum` (closed values; the shared coverage enum is `covered`, `not_covered`, `conditional`, `not_stated`),
  - `categories` (a list from a closed set given in the attribute, labels in three languages),
  - `text` (anything else; never compared by code);
  - and `direction` per side: `lower_better`, `higher_better`, `none`; for `enum`, an explicit order of values per side or `none`; for `categories`, `more_better`, `fewer_better` or `none`. `text` is always `none`.
- **Field names** (JSON): domain `{id, names, sides, topics}`; side `{id, names}`; topic `{id, names, descriptions, synonyms, attributes}` (language maps `en`/`uk`/`ru`); attribute `{id, labels, type, directions, units?, values?}` with `directions` mapping side id to direction; `enum`/`categories` values as `{id, labels}`; an enum direction is an ordered list of value ids, best first.
- Every catalog text must pass `confirm_topic()` (a loader test). Caps (fail closed in the loader and in a test): at most 30 topics per domain, 12 attributes per topic, 30 enum or category values per attribute, 200 characters per name, label or description.

### 2. Catalog API

`GET /api/topics/catalog` returns all domains with `catalog_version` (static, cacheable, no AI call, no request body). The frontend also bundles the same files at build time so the UI works before the backend wakes; a test checks both copies are identical.

### 3. Topic text safety pass (`app/topics/safety.py`)

Every topic text that did not come from the catalog (client-typed names and descriptions, AI-suggested names, AI-proposed attribute labels and category values, synonyms from expansion) passes the same function before it is used anywhere:

1. Layer 1 cleaning (`app/textclean/`) must be idempotent and the text must already be NFC; otherwise `invalid_topic_text` (client text is refused, never fixed silently). Leftover combining marks outside a letter are refused.
2. Grammar: 1–80 characters for names, 1–200 for client descriptions and labels, 1–60 for category and enum values and for synonyms (synonyms at least 3 letters, and not in a checked-in stop-word list per language), no line breaks, allowed characters only (letters and marks of the Latin and Cyrillic scripts, digits, space and `-'’.,()/%№`); no `[`, `]`, `⟦`, `⟧`, `<`, `>`, `{`, `}`, `|`, backtick.
3. **Placeholder-free:** no `[X.TYPE_n]` look-alike, also on the confusable skeleton.
4. **Identifier detector** (ADR 0015) runs on the text; any hit → `topic_contains_identifier` with spans (the client must remove it; topics are never masked, because a masked placeholder in a shared topic would leak which document it came from).
5. **Layer 2** (point 4) runs on the text; any hit → `topic_flagged` (a suggested topic is dropped and its source document is flagged).
6. **Meta-word rule (topics only).** Phrase lists can always be bypassed by plurals, synonyms and word order, and a topic name never needs to address an AI. So topic text is also refused (`topic_flagged`) on a *combination* of checked-in meta words in EN/UK/RU (on the skeleton, stem match), never on a single word: (a) an AI word (`assistant*`, `асистент*`, `ассистент*`, `AI`, `ИИ`, `ШІ`, `нейромереж*`, `нейросет*`, `neural network*`, `chatbot*`, `LLM`, `GPT`, `language model`, `мовн* модел*`, `языков* модел*`) together with an instruction word (`instruction*`, `directive*`, `guidance`, `інструкц*`, `вказівк*`, `инструкц*`, `указани*`, and the whole words `prompt`, `command`, `промпт`, `команда` when "for", "to", "для" or an AI word follows), a rating verb or a colour word, or an AI word right after "for", "to" or "для"; (b) an instruction word together with a hidden, system or secret qualifier; (c) a rating verb (`rate`, `rated`, the verb forms of `оцінити`/`оценить`, not the noun) followed by a colour or favourable word, or a colour word with a quantifier, an object or a give/assign verb. Honest names are tested and pass: "Prompt payment", "Prompt notice of loss", "Instructions of the insurer", "Указания страховщика", "Командировочные расходы", "Commander liability", "Оценка выгодности", "AI system liability", "Assistant services", "vehicle model", "Зелена карта" / "Green Card" (OSAGO). The client rewords a refused name; a false positive costs one edit. Layer 2 and this rule are best effort; the guarantees are ratings by code, directions only from the catalog or the client, and one document per call.

Only after all six does `confirm_topic()` create a `ConfirmedTopic`.

**What may cross documents (ADR 0009: a short name, never a summary).** A `ConfirmedTopic` built from a suggestion or a client topic is capped at **4 KiB** of text in total (UTF-8, all fields), failing closed (`topic_too_large`). The **description of an AI suggestion is shown only in the UI** and never enters the `ConfirmedTopic` or any prompt; a client-written description may enter it. **Synonyms are never sent to a model** (they are only for stage 8 keyword tags by code). **Directions decide ratings by code, so only the catalog or the client sets them:** every attribute has `direction_source` (`catalog` or `client`); an attribute proposed by a model starts with direction `none` and the UI asks the client to choose; the server refuses a non-catalog attribute whose direction is not `none` unless `direction_source` is `client` (the server cannot tell who clicked, so this is an honest-UI rule plus a default that fails to neutral). **Catalog topics are taken by id:** the request names `topic_id` and `catalog_version`; the server builds the `ConfirmedTopic` from its own catalog and refuses changed text or a version mismatch (`catalog_version_mismatch`). Caps per analysis request: at most 30 catalog topics, 10 suggested and 10 custom topics (`too_many_topics`). The gate type grows to hold the whole confirmed definition: `domain`, `topic_id` (catalog id or `custom_<n>`), `title`, `description`, `attributes` (a tuple of frozen `ConfirmedAttribute`), `synonyms` (tuples per language), `side`. **`ConfirmedTopic` is not bound to any document** (it is the one cross-document string, ADR 0009); the stage 6 follow-up that proposed binding it is withdrawn. Catalog topics also go through `confirm_topic()` (their text is trusted, but the type is the same).

### 4. Layer 2 patterns (`app/injection/`)

Stage 7 builds the ADR 0009 Layer 2 detector because topics need it first; stage 9 reuses it on clauses. A versioned, checked-in pattern file (EN/UK/RU and the role and special tokens listed in ADR 0009), matched on the NFKC + confusable skeleton view with linear-time patterns, returns classes `heuristic` or `high` with spans. For topics, any class blocks the text. "Source document flagged" for a dropped suggestion is advisory in v1: the server is stateless, so the flag is returned in the suggest reply and shown by the browser; stage 9 recomputes Layer 2 on the clauses itself. Tests cover each listed token, the three languages, homoglyph and zero-width variants (after Layer 1), and honest negatives ("AI system", "model year", "штучний інтелект" in an IT contract topic).

### 5. AI calls (new `PromptTemplate` members)

- **`SUGGEST_TOPICS`** — per document (one `PseudonymizedDocument`, the domain, the side): returns at most 8 topic names with a one-line description, strict schema. Each suggestion goes through point 3; failures are dropped and counted. The source document label is never part of the suggestion.
- **`PROPOSE_ATTRIBUTES`** — **no document**: input is one `ConfirmedTopic` whose attributes are still empty (name, description, domain, side). Returns 1–12 attributes in the point 1 schema. Every label and value goes through point 3. The client confirms or edits; the result becomes a new `ConfirmedTopic`.
- **`EXPAND_SYNONYMS`** — **no document**: input one `ConfirmedTopic`; returns synonyms per language (caps of point 1), each through point 3.
- `AIRequest` changes: `document` becomes optional, and **each `PromptTemplate` member declares its full field set**, enforced in `AIRequest.__post_init__`: `SUGGEST_TOPICS` — document required, topic and text forbidden; `PROPOSE_ATTRIBUTES` and `EXPAND_SYNONYMS` — topic required, document and text forbidden (ADR 0009: "attribute proposal, synonym expansion and the connection test take none"); later templates declare theirs. The AST policy test keeps the "no `str`" rule.
- `SUGGEST_TOPICS` input cap: at most 60,000 characters of masked clause text per call (about 15–20k tokens), checked before the call; above → `document_too_large_for_suggest` (fails closed; the client can still pick template and own topics).
- Output caps: `max_tokens` per template (suggest 1,200; propose 1,500; expand 800), one repair attempt per ADR 0009 (same inputs plus an error-code enum, never the previous output), then `ai_bad_output`.

### 6. Endpoints

`POST /api/topics/suggest`, `POST /api/topics/propose-attributes`, `POST /api/topics/expand-synonyms`. Each takes the provider selection of ADR 0016 point 6 (`provider`, `model`, `base_url`, `X-Provider-Key`), runs the safety pass server-side on its own input (suggest: the masked document as in `/api/safety-check`, with `detector_version`; the others: the topic definition), and returns only validated, safety-passed JSON. Limits: body caps (suggest uses the safety-check cap; the others 16 KiB), per-IP limits with the ADR 0016 limiter (aligned daily windows, /48 tier), 1 AI call in flight per client and 2 per server (shared with `/api/provider/check`), a total deadline per AI call of 60 s (connect 5 s; the provider slot is released on timeout), model output never logged. The suggest endpoint runs its safety pass in the sandbox slot and **releases the extraction slot before the AI call**, so a slow provider never holds an extraction slot.

**Free mode:** one Turnstile token per call would mean a challenge per topic. Instead, a verified Turnstile token at the first free topic call returns a **free pass**: an HMAC-SHA256-signed token `v1.<aud>.<expiry>.<client-key-hash>.<nonce>.<mac>` with `aud=topics` (refused by `/api/provider/check` and by every stage 9 endpoint), valid 15 minutes for the same client /48, at most 20 free topic calls. The HMAC key is **per process** (`secrets.token_bytes(32)` at startup, single worker; ADR 0011): a restart invalidates every pass, so the claim "fails closed on restart" is true, and there is no new secret. Calls are counted per nonce in a **bounded table** (at most 10,000 passes; full of live passes → new passes refused, fail closed). The pass travels only in the `X-Free-Pass` header, at most 256 characters, compared with `hmac.compare_digest`; never logged. A call is **reserved** against the pass, the per-IP **free topic quota** (initial 40 calls per day per /48, separate from the ADR 0016 free analysis quota of 5) and the global Neuron budget **before** the AI call, and settled after it. Topic calls may use at most **30 %** of the daily Neuron budget, so analyses always keep the rest (`free_quota_exhausted` above it).

### 7. Browser

- Topic panel: choose the domain (or "no template"), the side (closed list of the domain), template topics (all selected by default, each can be turned off), suggested topics (button "Suggest from my contracts", one call per document; the client accepts each suggestion), own topics (name and optional description → "Propose attributes" → editable attribute list → "Confirm"). Every topic shows its attributes and directions in the UI language. All strings in `en`/`uk`/`ru`.
- **Own topics storage:** in memory by default. "Save my topics on this device" (opt-in) stores them in `localStorage` key `aic.topics.v1` (only names, descriptions, attributes, synonyms — never contract text); removed by "Clear all". Export and import as a JSON file: import is untrusted input (size cap 256 KiB, strict schema with no extra keys and no `__proto__`/`constructor`/`prototype` keys, the same caps as point 1, every text re-checked by the server safety pass before use; nothing from the file is rendered as HTML).
- Honest-UI rule: when the client accepts a suggestion, its own description field stays empty (the suggestion's description is never copied into it).
- The topic set the client confirmed is sent with every later AI request; the server re-runs `confirm_topic()` on every request (the browser is never trusted).

### 8. Eval (first AI eval)

`ai-eval-engineer` adds `backend/eval/topics/`. Recorded responses are keyed by a hash of the prompt template text, the schema and the model; a mismatch fails the run (the recordings must be refreshed in live mode). An adversarial case: Contract B tries to smuggle text through a suggestion (long description, instructions, identifiers) and the test proves none of it reaches a `ConfirmedTopic` or another document's call. for each domain, synthetic contracts (from `domain-analyst`) with expected topics; metrics: suggestion precision/recall against expected topics, attribute-proposal schema validity and type agreement on a fixed list of custom topic names, synonym coverage of hand-written stems, Layer 2 false-positive rate on honest topic names. Runs on a recorded-response mode in CI (no network, no key) and on a live mode locally with a key; the live numbers are recorded in the PR. Baseline file like the detector eval.

## Consequences

- Positive: stage 8 and 9 get typed, confirmed topics; no model ever reads two contracts; topic text is the only cross-document string and is tightly checked.
- Negative: three new endpoints and three prompts; the free pass is lost on every restart (the client solves a new challenge); the catalog needs careful domain work in three languages.
- Residual risk: a client can type a topic that leaks information they chose to share (it is checked for identifiers, not for meaning); AI suggestions can be irrelevant (the client accepts each one); the free pass allows 20 calls per challenge.
