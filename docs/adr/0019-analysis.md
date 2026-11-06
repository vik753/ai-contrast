# ADR 0019 — Analysis: rating per document, verification by code, comparison by code

- Status: proposed (tech lead, 2026-11-06; round 2 after `security-reviewer` round 1)
- Date: 2026-11-06
- Related: ADR 0007 (free mode), ADR 0008/0015 (pseudonymization, gate types), ADR 0009 (Layers 3–4: one document per call, quotes, green rules, every cap fails closed), ADR 0013 (browser cache), ADR 0016 (AI port, limits, free mode), ADR 0017 (topics, attributes, directions), ADR 0018 (tagging, signature, analysis pass), threat model T1, T5, T6, T10, T11

## Context

Stage 8 gives, per document, the clauses of each confirmed topic and the "Other" clauses. Stage 9 rates them. ADR 0009 fixes the rules: one document per model call, every finding needs a verbatim quote, green needs the deterministic checks, the comparison between documents is done by code, missing-topic findings come from tagging, every cap fails closed. Stage 10 builds the full result table; stage 9 delivers the verified per-document findings and the code comparison with a minimal view.

## Decision

### 1. Endpoint `POST /api/analyze` — one document, streamed

- Input: the masked document exactly as `/api/tag` takes it, the topic selection (same rules, `app/topics/selection.py`, `catalog_version_mismatch`), domain and side, the UI language (`en` / `uk` / `ru`), the stage 8 tagging result (model and check tags with their `signature` and `tagging_version`, client tags), the browser's document flags (point 6) and the provider selection of ADR 0016 (or the analysis pass in free mode, ADR 0018 point 7).
- One request per document. The browser runs the documents one after another (at most 5; 2 in free mode). This keeps memory per request small (512 MB server), lets the browser show progress and retry one document, and keeps the rule "one document per call" visible in the API.
- **In the sandbox child, before any AI call:** the full safety pass (as `/api/safety-check`), keyword tags, "Other", risk terms and Layer 2 are **recomputed** (the stage 8 code). The server checks the tag signature (`tagging_version` must equal the current one, digest must match); a missing or wrong signature → `409 tagging_signature_invalid` (the browser re-tags). **Signature v2** (a stage 9 change to `/api/tag`) covers the document digest, `tagging_version`, the model and check pairs, the `incomplete_reasons`, the per-topic status (`model_tags_dropped`, `not_analyzed` with reason), the resolved topic set (ids and definition hashes), the domain and the side. `/api/analyze` derives missing-topic findings and topic status only from these signed fields; a different topic set, domain or side → `409`. Client tags are checked (ids, caps of ADR 0018 point 8) and only add. Code then builds the per-topic clause sets and the "Other" set exactly like `/api/tag` (`finish_tags`), plus the cross-reference closure (point 4). The extraction slot is released before any AI call.
- **Reply:** `text/event-stream` (SSE over `fetch`, because the request is a `POST` with the key header; `EventSource` cannot send headers). Events: `start` (plan: topic count, Other batches, reserved calls), `topic` (one per topic, when done), `other` (one per Other batch), `progress` (counts only), `done` (document summary and `result_signature`), `error` (code only). Every event is one JSON object, at most 64 KiB; a heartbeat comment every 15 s. The stream holds ids, enums, numbers, offsets and **model-written explanations** (point 3); it never holds clause text or topic text (the browser has both).
- Client disconnect cancels the outstanding AI calls (task cancellation). A cancelled or unfinished call is charged at its **worst case** (ADR 0018 point 7 rule); only finished calls settle with reported usage.
- Every refusal (4xx, `busy`, quota) is sent as a normal JSON reply **before** the first stream byte. Stream headers: `Cache-Control: no-store`, `X-Accel-Buffering: no`, no compression; each write has a send timeout under the deadline; a stalled client is dropped and its calls cancelled.
- Nothing is stored.

### 2. Model calls (strong model, one document, one topic)

- **`RATE_TOPIC`** (one call per topic per document): the instruction holds the topic (title, short description, attributes with ids, types, units and allowed values — no directions, no synonyms), the client's side and the output language; the data block holds the topic's clauses (tagged clauses plus the cross-reference closure), each with its clause id, in one nonce block. Output (strict JSON, Pydantic, `extra="forbid"`):
  - per attribute: `value` by type (`amount` {number, currency}, `percentage`, `duration` {number, unit}, `enum` value id, `categories` value ids, `text` short string, or `not_stated`), and `evidence`: at most 3 items `{clause, quote}`;
  - `findings`: at most 8 items `{rating: green|yellow|red, attribute|null, explanation (≤ 400 chars, output language), evidence: 1–3 {clause, quote}}`;
  - `injection_suspected`: at most 3 `{clause, quote}`.
- **`RATE_OTHER`** (one call per batch of "Other" clauses, risk-term clauses first; batch ≤ 12,000 characters and 40 clauses): per clause at most 2 findings in the same finding shape, or `no_issue`. Every clause of the batch must be answered (missing or unknown clause ids → bad output). **Other findings are at most 🟡**: a model green on an Other clause is shown as 🟡 `other_not_green` (Other clauses have no topic, so the exception rule cannot check them).
- Strong model of the preset (`MODEL_PAIRS`; the client may change it; `free`: the one model). Explicit `max_tokens` and reasoning effort per preset. One repair attempt per call with the same inputs plus an error-code enum (ADR 0009), never the previous output.
- Prompt structure as stage 6–8: system message holds the instruction; user message holds the data block with a fresh nonce; key rules repeated after the block (sandwich); role and special tokens neutralized before sending. Explanations are cleaned on the server before they enter the stream: control, format, bidi and default-ignorable characters stripped (the `app/textclean` table), NFC, cap 400 code points, then Layer 2; on any Layer 2 hit the explanation is dropped and replaced by the code `explanation_withheld`. The UI renders them as text only (rule 6), always after the code-made label and reason codes. Placeholders in explanations are restored in stage 10 only for the document's own known placeholders (never inside `⟦…⟧`).

### 3. Verification by code (Layer 4), in a pure module `app/analysis/verify/`

1. **Quote check.** Each quote must occur verbatim in the cited clause's masked text after whitespace folding only (runs of whitespace match one space; no case or punctuation folding). Failing quotes are dropped. A finding with no verified quote is shown as `unverified` and is never green. An attribute value without a verified quote becomes `not_confirmed`. A quote that occurs more than once in the clause is checked at **every** occurrence; a green needs all of them to pass. An `injection_suspected` item with a valid clause id blocks green for that clause even if its quote fails.
2. **Quote expansion.** Each verified quote is expanded to its full sentence (sentence end `.`, `;`, `!`, `?` followed by space or end, list markers and clause boundaries; abbreviations list EN/UK/RU), never beyond the clause. Checks and display use the expanded span. The reply carries offsets `[clause, start, end]`, not text.
3. **Green rules** (a green that fails any rule becomes 🟡 with a reason code; the model cannot lift a cap):
   - `quote_too_short`: expanded quote under 25 characters;
   - `suspicious_span`: the quote overlaps a Layer 2 span or an `injection_suspected` quote, or the clause has a heuristic Layer 2 hit;
   - `check_exceptions`: the rest of the quoted clause (text after and before the quote, and its heading) contains an exception marker; or another clause refers to the quoted clause by number, or shares the finding's topic and contains an exception marker (EN/UK/RU list of ADR 0009, a checked-in lexicon with tests); that clause's offsets are attached;
   - `global_override`: any clause of the document has a global-override marker → every green of the document is capped, with that clause attached;
   - `too_many_references`: the quoted clause's cross-reference closure needs more than 5 clauses;
   - `number_mismatch`: the attribute value (number with unit) is not found in the expanded quote with a matching unit word (unit lexicon EN/UK/RU for each catalog unit; digits, decimal comma or point, thousands spaces, and numbers in words 0–100 plus the "десять (10)" pattern), or the quote holds more than one number of the same unit; a mismatch caps at 🟡 and the value becomes `not_confirmed`;
   - `document_flags`: no green in the document when a flag of point 6 says so; no green for a clause with an unprovided reference.
4. **Verified values.** The number and unit check runs on **every** numeric attribute value, not only for greens. A value is `verified` only when its quote passes, the number check passes and no clause cap (`check_exceptions`, `suspicious_span`, `too_many_references`) or document cap (`global_override`, flags, `incomplete`) applies to its evidence; otherwise it is `not_confirmed` and is never compared (point 5). Enum and category values follow the same rule without the number check.
5. **Missing-topic findings** come from tagging only (zero clauses after recompute, tagging complete, topic neither `model_tags_dropped` nor `not_analyzed`): a 🟡 or 🔴 finding chosen by code (red only when the catalog marks the topic `essential` for the side; else yellow), never green, never from model claims.
6. **Other completeness.** If any "Other" clause stays unrated (bad output after repair, cap, deadline, budget), the document is `incomplete`: the count of unrated clauses is shown and **no green** stays in the document.
7. **Topic not analyzed.** A topic whose call fails (bad output after repair, deadline, budget) or whose clause set is above the call cap (40 clauses or 20,000 characters) is `not_analyzed` with a reason and shown 🟡; its clauses are rated in "Other" in the same request, so none is unrated.

### 4. Cross-references

Code finds references to clause numbers in the topic's clauses ("clause 12", "п. 4.2", "пункт 4.2", "розділ 3"; lexicon EN/UK/RU) and adds the referenced clauses to the call (depth 1, at most 5 per clause, cycles ignored). Above the limit the finding is capped (`too_many_references`) and the extra clauses are not added.

### 5. Comparison by code (browser)

- `frontend/src/analysis/compare.ts` (pure, tested) compares the verified per-document values per attribute: numbers only with the same unit (no currency or unit conversion; different units → `not_comparable`), enums and categories by id, `text` never (shown side by side with "compare yourself"). With the catalog or client direction it marks `better` / `worse` / `same` per document; without a direction only `same` / `different`. `not_confirmed`, `not_stated` and `not_analyzed` values are never compared as equal.
- Only `verified` values (point 3.4) are compared; `better` is never shown for a value under any cap.
- The comparison runs in the browser because the server is stateless and holds one document per request; the input values are the server's verified values (the browser trusts its own server replies; the contract author cannot change them). The model never sees two documents and never compares.

### 6. Document flags from the browser

The browser sends flags it got from `/api/extract` (and OCR) for this document: `not_read_material`, `hidden_text_removed`. The server accepts them as **restrictions only**: each flag can only remove greens, never add one. Red-class Layer 2 and references to documents not provided are **recomputed by the server** from the text (ADR 0009 lexicon); the browser sends only the annex links the client made (a client statement that lifts the cap on the referring clauses, shown as such). A browser that omits an extract flag harms only its own user; the threat model records this residual risk (T5).

### 7. Limits and budget (fail closed)

- Request body ≤ 2 MiB; same document caps as `/api/tag`; at most 20 topics.
- Worst-case reservation before the first call: topics × 2 + Other batches × 2 calls (one repair each), plus the Other batches needed if **every** topic fails at runtime and its clauses move to Other (each with a repair), each with its `max_tokens`. If that worst case exceeds the cap, the request is refused before any call. Above the per-request cap (`analysis_max_calls`, default 80) → `422 document_too_large_for_analysis` before any AI call.
- Overall deadline 8 minutes per document; per-call deadline 90 s. Deadline → the open topics are `not_analyzed` (reason `timeout`), the open Other batches unrated → document `incomplete`, no greens.
- Free mode: `/api/analyze` refuses a document whose digest is not among the analysis pass's recorded digests (`analysis_pass_document_mismatch`). The analysis pass of ADR 0018 point 7 covers the tag, check and analyze calls of its 2 documents; each call reserves its worst-case Neurons and settles with the reported usage; the pass call cap and Neuron cap apply.
- Per-key concurrency and the AI slots of ADR 0016; `503 busy` with `Retry-After`.

### 8. Result signature and cache

- `done` carries `result_signature = HMAC-SHA256(per-process key, v1 | document digest | analysis_version | domain | side | model | output language | hash of the flags | hash of the verified result)`; `analysis_version` hashes the prompts, schemas, lexicons and verification rules. It lets stage 10 and stage 11 tell a current result from a stale one; the browser cache (ADR 0013) keys results by the document hashes, the topic selection signature, `analysis_version`, domain, side, model, output language and the flags hash.
- Stage 9 fixes the cache key type (one `CacheKey`) and the `contractTextHash` null case (stage 4 follow-ups).

### 9. Browser (minimal view)

- "Analyze" runs after tagging: per document an SSE stream (`fetch` + `ReadableStream`, strict event parser with a per-event and a total stream size cap), progress per document and topic, stop button, "Clear all" aborts every stream and drops results (as stage 8).
- A minimal result view per topic: per document the attribute values (with `not_confirmed` / `not_stated`), the comparison marks, the findings with colour + icon + text label, the reason codes of capped greens as text, and "Other" findings; quotes are shown from the browser's own clause text by offsets. Plain text only. The full table, name restoration and export are stage 10.

### 10. Eval and policy tests

- Policy: every AI-layer function and `AIRequest` subclass takes at most one `PseudonymizedDocument` (AST test over `app/ai/`, `app/analysis/`, `app/tagging/`); the wire canary fails if one captured request holds placeholders of two labels.
- `backend/eval/analysis/` (recorded mode in CI, live locally): expected findings for the S7-T0 contracts (`domain-analyst`), metrics: verified-quote rate, rating agreement per topic, attribute value accuracy, share of capped greens on honest contracts, and **evidence-gaming cases with clean twins**: buried exception, global override, number in words vs digits mismatch, quote truncation, cross-reference chain, injected rating command, self-praise. Gates: no green on any attack case; no attack changes a rating beyond the clean-twin variance.

## Consequences

- Positive: no model sees two contracts; every colour shown has a verified quote or is marked unverified; greens are hard to fake; the comparison is reproducible.
- Negative: one call per topic per document plus Other batches; honest greens are sometimes capped (`check_exceptions`, `number_mismatch`); the eval tracks this rate.
- Residual risk: an honest-looking but misleading verified quote (the attacker writes the text) can still be green; document flags rely on the user's own browser.
