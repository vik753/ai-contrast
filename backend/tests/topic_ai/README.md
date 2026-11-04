# S7-T2 tests: public names (the contract for the implementation)

Written from `docs/agent/TASKS.md` S7-T2 (1-5, 3a), ADR 0017 points 3, 5, 6, ADR 0016 points 5-8 and threat model T1, T5, T6, T10, T11.
Run: `cd backend && uv run --locked pytest tests/topic_ai -q`. All tests fail until the feature exists.
Tests build on `tests/check/helpers.py` (`Rig`: fake provider and Turnstile transports, fixed clock 12:00 UTC) and the fixture catalog `tests/topics/fixtures/catalog_ok` (domains `kasko`, `lease`).
Gaps and choices below are the test engineer's; the tech lead may change a name, then the helpers in `helpers.py` change in one place.

## Endpoints

`POST /api/topics/suggest`, `POST /api/topics/propose-attributes`, `POST /api/topics/expand-synonyms`. JSON body, `Cache-Control: no-store` not tested.
Provider selection as in `tests/check/README.md`: body `provider`, `model`, `base_url` (custom), `turnstile_token` (free, first call only); header `X-Provider-Key` (not for free); same 422 codes (`invalid_request`, `invalid_provider`, `invalid_model`, `unexpected_base_url`, `invalid_provider_key`, `unexpected_provider_key`, `unexpected_turnstile_token`), same 503 `free_mode_unavailable`.
Extra body fields:

| Endpoint | Fields | Body cap |
| --- | --- | --- |
| suggest | `domain`, `side` (catalog ids), `document` = the `/api/safety-check` body (`label`, `detector_version`, `clauses`, `acknowledged_unmasked`) | 4 MiB (413 `request_too_large`) |
| propose-attributes | `topic` = a `TopicDefinition` JSON (`origin` is `suggested` or `custom`, `attributes` empty) | 16 KiB |
| expand-synonyms | `topic` = a `TopicDefinition` JSON (`origin` `suggested` or `custom`, attributes allowed) | 16 KiB |

Unknown fields: 422 `invalid_request`. A `domain`/`side` outside the catalog, `origin="catalog"`, a suggested topic with a description, propose with attributes: 422 `invalid_topic_definition`. Topic text errors: 422 `{"error": <code>, "field": <name>, "spans": [[s,e],...]}` (`spans` only for `topic_contains_identifier`) with the codes of `TopicTextError` / `TopicDefinitionError` (`invalid_topic_text`, `topic_contains_identifier`, `topic_flagged`, `invalid_direction`, `topic_too_large`, ...). Document errors of the safety pass: as `/api/safety-check`. Suggest input over 60,000 characters of clause text (sum, exactly 60,000 passes): 422 `document_too_large_for_suggest`, no AI call.
`Settings.topics_catalog_dir` selects the catalog; the topic is checked with `confirm_topic(..., catalog=catalog)`.

## Replies (200)

- suggest: `{"suggestions": [{"id": "suggested_<n>", "name", "description"}], "dropped": <int>}`; `n` counts the survivors from 1. The description is for the UI only.
- propose-attributes: `{"attributes": [<AttributeDefinition JSON>], "dropped": <int>}`; every `direction` is `"none"`, `order` is `[]`; the server sets `value_ids`.
- expand-synonyms: `{"synonyms_en": [...], "synonyms_uk": [...], "synonyms_ru": [...], "dropped": <int>}`.
- A call that verified a Turnstile token (free mode) adds `"free_pass": "<token>"` to the reply (any of the three).

## Model output schemas (strict: `extra="forbid"`, caps fail closed, no truncation)

- suggest: `{"topics": [{"name", "description"}]}`, 0..8 topics.
- propose: `{"attributes": [{"id", "label", "type", "units": [..], "values": [..]}]}`, 1..12 attributes (`units`, `values` optional, `values` at most 30). No `direction` field (a model that sends one fails the schema).
- expand: `{"synonyms_en": [..], "synonyms_uk": [..], "synonyms_ru": [..]}`, at most 40 each.
- Every name, description, label, value and synonym goes through `check_topic_text`; an item that fails is dropped and counted in `dropped`. Propose with no surviving attribute: `ai_bad_output`.
- Bad output (not JSON, schema violation, cap exceeded): one repair call (same inputs plus an error-code enum, never the previous output), then 502 `{"error": "ai_bad_output"}`. At most 2 upstream calls per request. `AIError` maps as in `tests/check/README.md`.

## Selection of topics (`app/topics/selection.py`, pure function; used by stage 9)

- `CatalogRef(BaseModel)`: `domain`, `topic_id`, `side`, `lang`, `catalog_version`. `TopicSelection(BaseModel)`: `catalog: list[CatalogRef] = []`, `suggested: list[TopicDefinition] = []`, `custom: list[TopicDefinition] = []`.
- `resolve_topics(selection, catalog: Catalog) -> tuple[ConfirmedTopic, ...]`: catalog topics are built by id from `Catalog.definition`, then `confirm_topic(..., catalog=catalog)`. `TopicSelectionError(code)` (`.code`): `too_many_topics` (over 30 catalog, 10 suggested, 10 custom), `catalog_version_mismatch`, `unknown_topic`. A definition with `origin` that does not match its list: `TopicDefinitionError("invalid_topic_definition")`.
- Every call of `confirm_topic` in `app/` outside `app/pseudo/gate.py` passes `catalog=` (AST policy test).

## Limits and settings (`Settings`, env = upper-case name)

`topics_per_minute=10` and `topics_per_day=60` per IP, all three endpoints together (429 `rate_limited` + `Retry-After`; minute table by /64, daily aligned UTC by /48); validation failures count nothing.
In flight: 1 per client, and the pool of `max_concurrent_checks=2` is shared with `/api/provider/check` (503 `busy` + `Retry-After`).
`topic_ai_deadline_seconds=60.0` total per AI call; on timeout 502 `provider_unavailable` and the slot is released.
`suggest_max_chars=60000`. Extraction slot is released before the AI call.

## Free pass

- First free topic call: body has `turnstile_token`, no header. Later calls: header `X-Free-Pass: <pass>`, no `turnstile_token` (both together: 422 `invalid_request`). The header is the only channel; the pass in a body field or the query string is not accepted. The issuing call is call 1 of the pass.
- Pass format `v1.<aud>.<expiry>.<client-key-hash>.<nonce>.<mac>`, `aud=topics`, HMAC-SHA256 with a per-process key (`secrets.token_bytes(32)`, compared with `hmac.compare_digest`), 900 s, same /48 (IPv4: same address), at most `free_pass_max_calls=20` calls, table of `free_pass_max_entries` (default and maximum 10000) live passes.
- Errors (all 403 unless noted): `free_pass_invalid` (malformed, longer than 256 characters, bad MAC, wrong aud, other process, other client, unknown nonce), `free_pass_expired`, `free_pass_exhausted`; issuing with a full table: 503 `free_pass_unavailable`; header with a non-free provider: 422 `unexpected_free_pass`; no pass and no token: 403 `turnstile_failed`.
- `/api/provider/check` refuses `X-Free-Pass` (422 `unexpected_free_pass`) and a pass used as a Turnstile token (403 `turnstile_failed`).
- Quota: `free_topic_calls_per_ip_per_day=40` per /48 (429 `free_quota_exhausted` + `Retry-After`); Neurons: `app.limits.free.TOPIC_NEURONS = 20` reserved per call before the AI call (not corrected: the port reports no usage); topic calls together use at most 30 % of `free_neuron_budget`.
