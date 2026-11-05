# S8-T2 tests: public names (the contract for the implementation)

Written from `docs/agent/TASKS.md` S8-T2, ADR 0018 (all points), ADR 0016 points 5-8, ADR 0017 point 6, threat model T1, T5, T6, T10, T11.
Run: `cd backend && uv run --locked pytest tests/tag_api -q`. All tests fail until the feature exists.
Tests build on `tests/check/helpers.py` (`Rig`), `tests/topic_ai/helpers.py` and the fixture catalog `tests/topics/fixtures/catalog_ok` (domain `kasko`: topics `deductible`, `theft_cover`, `exclusions`). No network: the provider is a fake transport.
Names marked (choice) are the test engineer's; the tech lead may change one, then `helpers.py` changes in one place.

## Request: `POST /api/tag` (JSON, body cap 4 MiB, 413 `request_too_large`)

```
{ "provider", "model", "check_model"?, "base_url"?, "turnstile_token"?,
  "domain", "side",
  "document": { "label", "detector_version", "clauses": [{"id","text"}], "acknowledged_unmasked": [] },   # as /api/safety-check
  "topics": { "catalog": [CatalogRef], "suggested": [TopicDefinition], "custom": [TopicDefinition] } }   # TopicSelection
```

- Provider rules as `/api/provider/check`: header `X-Provider-Key` (not for `free`), same 422 codes. `model` is the cheap (tagging) model, `check_model` the strong (check) model; if absent `check_model` = `model`. `free`: both fields are refused (`422 unexpected_model`); the free model `@cf/openai/gpt-oss-120b` serves both calls.
- `app.ai.presets.MODEL_PAIRS: Mapping[PresetId, ModelPair]`, `ModelPair(cheap: str, strong: str)` (frozen dataclass), one entry per preset except `custom`; `free` has cheap == strong == the free model; for the other presets both are members of `PRESETS[id].models` and differ.
- Topics: resolved with `resolve_topics`, in the order catalog, suggested, custom. Topic index `Tk` is the k-th topic (1-based) of that order.
- Errors, in this order of checks: 413/422 request errors; safety-pass errors as `/api/safety-check` (422 `unmasked_identifier` with `spans`, 409 `detector_version_mismatch`); selection errors 422 `too_many_topics`, `unknown_topic`, `no_topics` (no topic at all), 409 `catalog_version_mismatch`; topic text errors as the topic endpoints (`topic_flagged` + `field`, ...); 422 `keyword_budget_exceeded` (a refusal, no AI call); 422 `document_too_large_for_tagging` (sum of clause characters over `Settings.tag_max_document_chars` (300000), or more than 60 batches; no AI call); free mode: 422 `too_many_documents`, 422 `free_too_large`, 403 `analysis_pass_*`, 429 `free_quota_exhausted` (+ `Retry-After`), 503 `free_mode_unavailable`; 429 `rate_limited` (+ `Retry-After`); 503 `busy` (+ `Retry-After`). Hard provider errors fail the request with the status map of `tests/check/README.md` (`provider_auth_failed` 401, `provider_model_not_found` 404, `provider_bad_request` 400, `provider_blocked_host` 422). Soft provider errors never fail the request: `provider_unavailable` (5xx, timeout) -> reason `timeout`, `provider_rate_limited` -> `quota`, `provider_bad_response` and bad output -> `bad_output` (batch falls back to keyword tags).
- Settings (choice, env = upper-case name): `tag_per_minute=10`, `tag_per_day=60` (per IP, validation failures count nothing), `tag_deadline_seconds=300.0`, `tag_call_deadline_seconds=60.0`, `tag_max_document_chars=300000`, `keyword_step_budget=1000000` (passed to the keyword step; a tiny value makes it fail), `analysis_pass_max_calls=40`, `analysis_pass_max_neurons=3000` (per pass; worst case reserved before the first AI call). In flight: 1 per client, pool `max_concurrent_checks` shared with check and topics. Existing: `free_calls_per_ip_per_day`, `free_neuron_budget`, `free_pass_max_entries`.

## Reply (200)

```
{ "digest": <hex64, equals /api/safety-check digest>,
  "tagging_version": str, "signature": str,
  "tags": { "<clause id>": [ {"topic_id": str, "source": "keyword"|"model"|"check"} ] },   # every clause id is a key
  "other": ["<clause id>", ...],
  "risk": { "<clause id>": [[start, end], ...] },            # only "Other" clauses with hits
  "topics": { "<topic id>": { "keyword_clauses": int, "model_clauses": int, "model_asserted": int,
                              "model_tags_dropped": bool, "not_analyzed": null|"too_many_clauses" } },
  "missing_topics": ["<topic id>"],
  "layer2": { "<clause id>": { "text": [[start, end, cls]], "heading": [[start, end, cls]] } },   # only clauses with a hit
  "model_tagging_incomplete": bool, "incomplete_reasons": ["bad_output"|"timeout"|"quota"|"check_failed"|"clause_cap"] (sorted),
  "analysis_pass": "<token>" }                                # only on the call that verified Turnstile (free)
```

`model_asserted` (per topic) = number of clauses the model proposed for the topic (high, or low confirmed) even if the tag is not kept because a keyword tag exists or the topic was dropped. Strings in the reply are only clause ids, topic ids, enums, digest, version, signature (never clause, topic or model text).
`tags` holds the same pair once; a pair in several sources keeps the first of `keyword, model, check`.

## Prompts

`PromptTemplate.TAG_CLAUSES` and `PromptTemplate.CHECK_TAGS` (`app/ai/prompts`). The call for one batch has the template text as the system message and data blocks (with nonces) as user messages. Clause ids `c<n>` appear in the user messages. Topics appear as lines `T<k>: <title> - <description>` (title and description only; no synonyms, no id, no attributes). Check pairs appear in the user messages each on its own line as `c<n> T<k>` (one space).

- TAG output: `{"tags": [{"clause": "c1", "topics": [{"index": "T1", "confidence": "high"|"low"}]}]}`; at most 5 topics per clause; clauses may be omitted; unknown clause, unknown index, extra field or wrong type: bad output.
- CHECK output: `{"answers": [{"clause": "c1", "topic": "T1", "regulates": true}]}`; must answer asked pairs only; an unasked pair, extra field: bad output.
- Bad output: one repair call (same inputs plus an error-code enum, never the previous output), then the batch fails. Hard cap on one batch: 12,000 characters of clause text and 40 clauses.

## Signature

`app.tagging.signature.verify_tag_signature(app: FastAPI, signature: str, *, digest: str, tagging_version: str, tags: Mapping[str, Mapping[str, str]]) -> bool`: `tags` is `{clause_id: {topic_id: source}}`; only `model` and `check` pairs are hashed. A new `create_app` instance gives False for a signature of an old one.

## Analysis pass (free mode)

- Headers: `X-Analysis-Pass` on later calls (no `turnstile_token`; both together: 422 `invalid_request`). `X-Free-Pass` is the topic pass and never works here. Format `v1.analysis.<expiry>.<client-key-hash>.<nonce>.<mac>`, 1800 s, same /48, one live per client per audience (a topic pass and an analysis pass coexist), table size `free_pass_max_entries`.
- Errors (403): `analysis_pass_invalid`, `analysis_pass_expired`, `analysis_pass_exhausted` (call or Neuron cap, also when the worst case of the new request does not fit; no AI call); issuing with a full table 503 `analysis_pass_unavailable`; header with a non-free provider 422 `unexpected_analysis_pass`; no pass and no token 403 `turnstile_failed`.
- Topic endpoints refuse `X-Analysis-Pass` and an analysis pass in `X-Free-Pass` (`free_pass_invalid`); `/api/provider/check` refuses `X-Analysis-Pass` (422 `unexpected_analysis_pass`) and an analysis pass as Turnstile token (403 `turnstile_failed`).
- The pass records at most 2 document digests (a third: 422 `too_many_documents`; the same digest again is fine) and the total size by characters (3,000 per page, at most 30 pages = 90,000 characters; over: 422 `free_too_large`).
- Starting the analysis (Turnstile call) charges `free_calls_per_ip_per_day` once; pass calls charge nothing. Whole worst case reserved first (Neurons; refusal 429 `free_quota_exhausted`), settled from reported usage.
