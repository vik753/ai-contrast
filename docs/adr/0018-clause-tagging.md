# ADR 0018 — Clause tagging: keyword tags, model tags, "Other" and the analysis pass

- Status: proposed (tech lead, 2026-11-05; round 1 security changes included)
- Date: 2026-11-05
- Related: ADR 0009 (Layers 2–4; "tagging cannot hide a clause"; one document per call; every cap fails closed), ADR 0014 (clauses), ADR 0015 (safety pass, gate), ADR 0016 (AI port, limits, free mode), ADR 0017 (`ConfirmedTopic`, synonyms, Layer 2), threat model T5, T6, T10, T11

## Context

Stage 9 rates a topic using only the clauses tagged with it. If tagging misses a clause, that clause is never rated for the topic. ADR 0009 therefore fixes the rules: code tags first by keywords, a model can only add tags, untagged clauses go to "Other" and are still rated, and caps never hide a clause. Stage 8 builds this step for **one document per request**.

## Decision

### 1. Endpoint `POST /api/tag`

- Input: one masked document exactly as `/api/safety-check` takes it (label, `detector_version`, clauses, `acknowledged_unmasked`), the topic selection (catalog topics by id with `catalog_version`, custom and suggested topic definitions; resolved with `app/topics/selection.py` and `confirm_topic()`), the domain and side, and the provider selection of ADR 0016 point 6 (plus the analysis pass in free mode, point 7).
- The server runs, **in the sandbox child**, the full safety pass, the keyword tags (point 2), the risk-term scan (point 4) and Layer 2 (point 6); only then is the extraction slot released, before any AI call (pure-Python text work never runs on the event loop). It resolves the topics, runs the AI steps and returns: per clause the list of `{topic_id, source: "keyword" | "model" | "check"}`, the "Other" list with risk-term hits, per-topic counts and flags (`model_tags_dropped`, `not_analyzed` with a reason), Layer 2 flags per clause (`heuristic` / `high` with spans), a per-document `model_tagging_incomplete` flag with reasons (`bad_output`, `timeout`, `quota`, `check_failed`), and `tagging_version` (hash of the keyword rules, the risk-term list, the prompts and `PATTERNS_VERSION`). The reply holds only ids, enums, counts and offsets — never clause text, topic text or model text.
- Nothing is stored. The browser keeps the result in memory next to the document (and in the cache only through stage 9's result, ADR 0013).

### 2. Keyword tags (deterministic, first)

- For every confirmed topic, its synonyms (catalog synonyms; for custom and suggested topics the confirmed synonyms) are matched on the NFKC + confusable skeleton view of each clause, case-insensitively, at word starts (stems match word prefixes, phrases match word sequences with flexible whitespace). Linear time: an Aho–Corasick-style automaton or a token-prefix index; no regex built from synonyms (synonyms are client text).
- The clause heading counts as clause text (ADR 0014).
- Keyword tags can never be removed by a model or by a cap (point 5). Keyword flooding is possible (the attacker writes the text): above 120 keyword clauses a topic is `not_analyzed` (🟡), and its clauses are still rated in "Other".

### 3. Model tags (cheap model, then a check)

- **Tagging call** (`TAG_CLAUSES`, cheap model): one document only; clauses in batches (each batch at most 12,000 characters of clause text and 40 clauses, data blocks with nonces); the instruction lists the topics by **opaque index** (`T1…Tn`) with title and short description only (no synonyms, no attribute ids); the output is, per clause id, a list of topic indexes (at most 5) with a confidence `high` / `low`, strict schema; unknown clause ids or indexes → `ai_bad_output` for that batch (one repair, then the batch counts as not tagged by model: its clauses keep keyword tags and go to "Other" if they have none, and the document is `model_tagging_incomplete` (`bad_output`)).
- **Check call** (`CHECK_TAGS`, strong model): for clause–topic pairs marked `low`, one call per batch asks "does this clause regulate this topic, yes/no" (strict schema). Only `yes` keeps the tag (`source: "check"`). If a check call fails, its `low` tags are dropped and the document is `model_tagging_incomplete` (`check_failed`).
- Models: each provider preset names a **cheap** and a **strong** model (the client may change both; `free` uses `@cf/openai/gpt-oss-120b` for both). The UI shows the pair.
- The model **adds** tags only. A model answer that omits a keyword-tagged pair changes nothing.

### 4. "Other" and risk terms

- A clause with no tag after points 2–3 goes to "Other". Code scans every "Other" clause with a checked-in **risk-term list** (EN/UK/RU stems: penalty, fine, forfeit, exclusion, not covered, waive, unilateral, terminate, indemnify, liquidated damages; штраф, пеня, неустойк, не відшкодову, не возмеща, виключенн, исключени, в односторонньому, в одностороннем, відмов, отказ…) and returns the hits. Stage 9 rates **all** "Other" clauses per document (risk-term clauses first); if it cannot rate all of them (caps, budget), the document is marked incomplete and gets **no greens**.

### 5. Caps (fail closed, never hide a clause)

- At most 5 model tags per clause (keyword tags are not capped and are counted separately).
- At most 60 model-tagged clauses per topic per document. If model tags push a topic over the cap, **all model tags of that topic are dropped**, keyword tags stay, the dropped clauses go to "Other" (if they have no other tag), and the topic is flagged `model_tags_dropped` (outlier: a fooled tagger cannot turn a red into "not analyzed").
- If **keyword** tags alone exceed 120 clauses for one topic, the topic is `not_analyzed` with reason `too_many_clauses` (shown 🟡 at stage 10); its clauses go to "Other" as well, so they are still rated.
- Token budget per document for tagging (input estimate before any call); above it → `422 document_too_large_for_tagging` (fails closed, before any AI call; the client can deselect topics or split the document).
- **Missing-topic findings** ("the contract does not mention X") are emitted only when tagging was complete for that document (no `model_tagging_incomplete`) and the topic is neither `model_tags_dropped` nor `not_analyzed`; such a finding is never green. Otherwise the topic shows 🟡 "could not confirm".
- **Overall limits per request:** at most 60 tagging batches and a 5-minute overall deadline; the whole worst case (all batches, all possible check calls, one repair each) is reserved before the first call; if the reservation fails, the request fails before any call (no partial result).

### 6. Layer 2 on clauses

`app/injection.scan()` runs on every clause (text and heading). Hits are returned per clause; stage 9 applies the ADR 0009 labels (heuristic 🟡 for the clause; high → no greens for the document). The tagging prompt does not change because of a hit: the clause is still tagged and rated (a hidden instruction must not make a clause disappear).

### 7. Free mode: the analysis pass

- Free analyses use an **analysis pass** like the topic free pass (ADR 0017 point 6) with `aud=analysis`: issued after one Turnstile at the start of an analysis (the tag call of the first document), per-process HMAC key, valid 30 minutes, same /48, one live pass per client, bounded table. One pass covers **one analysis**: at most `N` documents (2 in free mode, ADR 0007) and their tag, check and stage 9 calls. Starting it charges the per-IP free analysis quota (5 per day, ADR 0016); every call reserves its worst-case Neurons and settles with reported usage; the analysis share of the budget is the 70 % not reserved for topics.
- Free-mode size limits of ADR 0007 (2 contracts, 30 pages in total) are checked at the tag call. Pages are counted **from characters only** (3,000 per page), because the masked document carries no trusted page numbers. The pass table records the digests of at most 2 documents and their total size; a third digest or more than 30 pages is refused. Each pass also has a worst-case Neuron cap and a call cap, so re-tagging cannot spend the analysis share.
- Audiences are strict: `aud=analysis` is refused by the topic endpoints and `/api/provider/check`; `/api/tag` refuses `aud=topics`; one live pass per client per audience.

### 8. Browser

- `App` gets the confirmed masked documents from the upload flow (the pseudonymization preview) through a small **in-memory** store (never IndexedDB, `localStorage` or `sessionStorage`; emptied by "Clear all"), which also enables "Suggest" in the topic panel (stage 7 follow-up).
- A "Tag clauses" step per document after topics are confirmed: progress per document, the result as a list of clauses with their topic chips (keyword / model / check, shown with an icon and text, not colour only), "Other" with risk-term marks, and the per-topic flags. The client cannot remove keyword tags; the client may add a tag to a clause. **Client tags** count towards the 120 keyword cap per topic and the 5-per-clause cap, their topic and clause ids are checked, and they may only add. Stage 9 never trusts a tagging result from the browser: it recomputes keyword tags, "Other" and Layer 2 itself (bound to the document digest and `tagging_version`) and accepts from the browser only client-added tags and the model/check tags it can re-verify by digest.
- Cost estimate before the step: number of calls and an estimate of tokens per document; shown with the model pair (full estimate in stage 11).

### 9. Eval

`ai-eval-engineer` adds `backend/eval/tagging/`: per clause the expected topics from the S7-T0 fixtures (`expected.json` clause references, extended by `domain-analyst` where needed); metrics: per-topic recall and precision of keyword tags alone and of keyword + model tags, share of clauses in "Other", risk-term recall on "Other"; adversarial cases: a clause that tells the tagger to skip it, a document that floods one topic to hit the cap; recorded mode in CI (stub recordings as in stage 7) and live mode locally.

## Consequences

- Positive: no clause can disappear from the analysis; keyword tags make tagging work even without a model; the analysis pass gives free mode a clear per-analysis budget.
- Negative: two model calls per batch at worst; client text (synonyms) drives an automaton, which needs size caps (synonym caps of ADR 0017 apply).
- Residual risk: a missed tag sends the clause to "Other", where it is rated without a topic, so its finding may be less specific; the eval measures this.
