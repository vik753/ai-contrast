# S9-T3 tests: `POST /api/analyze` (the contract for the implementation)

Written from `docs/agent/TASKS.md` S9-T3, ADR 0019 points 1, 3, 6, 7, 8, ADR 0018 points 7-8, threat model T1, T5, T6, T10, T11.
Run: `cd backend && uv run --locked pytest tests/analyze_api -q`. All tests fail until the feature exists.
Builds on `tests/tag_api/helpers.py` (`TagRig`, `TagUpstream`), `tests/topics/fixtures/catalog_ok` (domain `kasko`). No network.
Names marked (choice) are the test engineer's; the tech lead may change one, then `helpers.py` changes in one place.

## Request (JSON, cap 2 MiB, 413 `request_too_large`; unknown fields: 422 `invalid_request`)

Everything of the `/api/tag` body (`provider`, `model`, `base_url`, `domain`, `side`, `document`, `topics`; same provider rules and
codes, same header `X-Provider-Key`) except `check_model` and `turnstile_token` (both refused: 422 `invalid_request`), plus:

```
"language": "en"|"uk"|"ru",
"tagging": { "digest", "tagging_version", "signature",           # as in the /api/tag reply
             "tags": {...}, "incomplete_reasons": [...], "topics": {...},   # the /api/tag reply fields, unchanged
             "client_tags": { "<clause id>": ["<topic id>", ...] } },   # add-only; optional, default {}
"flags": ["not_read_material"|"hidden_text_removed", ...],        # optional, default []
"annex_links": ["<clause id>", ...]                                # optional, default []
```

- `model` = the rating (strong) model. Absent: `MODEL_PAIRS[preset].strong`. `free`: `model` refused (`422 unexpected_model`).
- In `tagging.tags` only `model` and `check` entries count; `keyword` / `client` entries are ignored (recomputed or taken from `client_tags`).
- `tagging.topics` counts (`keyword_clauses`, `model_clauses`, `model_asserted`) are not signed and are ignored; only `model_tags_dropped` and `not_analyzed` count.
- Order of refusals: 413/422 request errors; safety errors (as `/api/tag`); selection errors; topic text errors; `422 keyword_budget_exceeded`;
  `409 tagging_signature_invalid`; `422 invalid_client_tag`, `422 too_many_client_tags`; `422 document_too_large_for_analysis`
  (document over `tag_max_document_chars`, or the worst case below over `analysis_max_calls`); free mode: `403 analysis_pass_invalid|expired`,
  `403 analysis_pass_document_mismatch`, `403 analysis_pass_exhausted`, `429 free_quota_exhausted`; `429 rate_limited`; `503 busy`.
  Every refusal is a normal JSON reply (`{"error": code}`) before the first stream byte. Hard provider errors (`provider_auth_failed` ...)
  arrive as an `error` event (the stream has started).
- Free mode: header `X-Analysis-Pass` only; no pass: `403 analysis_pass_invalid`; `turnstile_token` in the body: 422 `invalid_request`.
- Settings (choice): `analysis_per_minute=10`, `analysis_per_day=60` (per IP), `analysis_max_calls=80`, `analysis_deadline_seconds=480.0`,
  `analysis_call_deadline_seconds=90.0`, `analysis_heartbeat_seconds=15.0`, `analysis_send_timeout_seconds=30.0`. In flight: 1 per client, pool `max_concurrent_checks`.

## `/api/tag` change (signature v2)

Reply fields unchanged. `signature` now also covers `incomplete_reasons`, per topic `model_tags_dropped` and `not_analyzed`, the resolved topic
set (ids and definition hashes), `domain` and `side`. `verify_tag_signature` takes the extra keyword arguments (developer's choice; the
helper `_verify` in `tests/tag_api/test_reply.py` must follow).

## Reply (200)

`Content-Type: text/event-stream`, `Cache-Control: no-store`, `X-Accel-Buffering: no`, no `Content-Encoding`.
Event = `event: <name>\ndata: <one-line JSON>\n\n`, at most 65,536 bytes. Heartbeat = a comment block `: <text>\n\n` every `analysis_heartbeat_seconds`.
Order: `start`, then `topic` (one per selected topic, in topic order T1..), `other`, `progress`, last `done` (or `error`, no `done`).
`evidence` items are `[clause_id, start, end]` (expanded verified spans into the clause text); no clause text, topic text or quote text anywhere.

```
start    {"digest", "topics": n, "other_batches": n, "reserved_calls": n}
           topics = selected topics; other_batches = batches of the "Other" set; reserved_calls = 2*T + 2*B_all, T = topics with >=1 clause
           that are not already not_analyzed, B_all = batches (greedy, <=12,000 chars and <=40 clauses) of Other plus all clauses of those topics.
topic    {"topic_id", "state": "ok"|"model_tags_dropped"|"not_analyzed", "reason": null|"too_many_clauses"|"topic_call_cap"|"bad_output"|"timeout"|"budget",
          "clauses": [ids sent to the model], "missing": null|{"rating": "yellow"|"red"},
          "values": [{"attribute", "value": {as the model gave it}, "status": "verified"|"not_confirmed"|"not_stated", "reasons": [Reason], "evidence": [[c,s,e]]}],
          "findings": [{"rating", "attribute": null|id, "explanation": str, "reasons": [Reason], "unverified": bool, "evidence": [[c,s,e]], "attached": [[c,s,e]]}]}
other    {"batch": i, "part": j, "clauses": [ids], "rated": bool, "reason": null|"bad_output"|"timeout"|"budget",
          "no_issue": [ids], "findings": [{"clause", "rating", "explanation", "reasons", "unverified", "evidence", "attached"}]}
           (a batch whose events would pass 64 KiB is split over several parts; the parts together hold the batch)
progress {"done": n, "total": n}                          (calls, counts only)
done     {"digest", "incomplete": bool, "unrated_other": n, "greens_allowed": bool, "not_analyzed": [{"topic_id","reason"}],
          "flags": [applied flags], "result_signature": hex64, "analysis_version": str}
error    {"error": code}
```

A `not_stated` value (no evidence) keeps status `not_stated`.
`Reason` = the `app.analysis.verify.Reason` values. A withheld explanation is the string `explanation_withheld`.
`result_signature` = HMAC (per-process key) over the document digest, `analysis_version`, domain, side, model, language, flags hash and the verified result.
