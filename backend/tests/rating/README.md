# S9-T2 tests: public API of the rating calls

Written from ADR 0019 points 2 and 10 and TASKS S9-T2, before the implementation.
Run: `cd backend && uv run --locked pytest tests/rating -q`. All tests fail (ImportError) before the implementation.
No network, no real provider: `FakeProvider` in `helpers.py` records every `AIRequest`.

## Names (the contract)

`app.ai.port` (next to `TaggingRequest`):
- `OutputLanguage(StrEnum)`: `EN="en"`, `UK="uk"`, `RU="ru"`.
- `ReasoningEffort(StrEnum)`: `LOW`, `MEDIUM`, `HIGH` (values lower case).
- `Usage(input_tokens: int, output_tokens: int)`: frozen dataclass.
- `AIRequest.effort: ReasoningEffort | None = None` (new field). The OpenAI-compatible adapter sends it as `reasoning_effort`.
- `AIProvider.usage -> Usage | None` (protocol member; both adapters). Replaces `getattr(provider, "usage")` in `app.limits.free.reported_neurons`.
- `RateTopicRequest(AIRequest)`: template `RATE_TOPIC`, `document` and `topic` required, `text` forbidden, field `language: OutputLanguage`, schema `TopicRatingOut`.
- `RateOtherRequest(AIRequest)`: template `RATE_OTHER`, `document` required, `topic` and `text` forbidden, fields `side: str` (catalog side id, named in the instruction) and `language`, schema `OtherRatingOut`.
  Both raise `TypeError` for a wrong template, wrong schema, wrong fields or a `language` that is not an `OutputLanguage`.
  `AIRequest(PromptTemplate.RATE_*, ...)` built directly raises `TypeError`.
- `PromptTemplate.RATE_TOPIC`, `PromptTemplate.RATE_OTHER`.

`app.ai.presets`:
- `REASONING_EFFORT: Mapping[PresetId, ReasoningEffort | None]`: a key for every `PresetId`; `FREE` is not `None`.
- `strong_model(preset: PresetId, client_model: str | None = None) -> str`: `MODEL_PAIRS[preset].strong`; a given `client_model` wins except for `FREE` (the one model); `CUSTOM` without a model raises `ConnectionConfigError`.

`app.analysis.schemas` (Pydantic, `extra="forbid"`, strict): `TopicRatingOut`, `OtherRatingOut`, `BadOutputError` (the same class as `app.tagging.schemas.BadOutputError`).
JSON shapes:
- evidence item `{clause: "c<n>", quote: 1..1000 chars}`.
- finding `{rating: green|yellow|red, attribute: id|null, explanation: 1..400 code points, evidence: 1..3 items}`.
- `TopicRatingOut {attributes: <=12 of {attribute, value, evidence: 0..3}, findings: <=8, injection_suspected: <=3 evidence items}`.
- value (discriminated by `type`): `amount {number, currency}` (currency in UAH USD EUR percent_of_sum percent_of_loss), `percentage {number}`, `duration {number, unit}` (hours days working_days months years), `enum {value}`, `categories {values: <=30}`, `text {text: <=200}`, `not_stated {}`. `number`: finite JSON number, 0..1e12, no bool.
- `OtherRatingOut {clauses: <=40 of {clause, no_issue: bool, findings: <=2}}`; `no_issue` is true exactly when `findings` is empty.

`app.analysis.rate`:
- `async rate_topic(provider, document, topic, *, language, effort=None) -> TopicRatingOut`.
- `async rate_other(provider, document, *, side, language, effort=None) -> OtherRatingOut`.
- `clean_explanation(text: str) -> str` and `EXPLANATION_WITHHELD == "explanation_withheld"`.
- `topic_max_tokens(topic) -> int`, `other_max_tokens(clause_count) -> int` (1..16384).
- Both calls check the answer against the request (below), clean every explanation, make at most one repair call, raise `BadOutputError` after the second bad answer, and let hard `AIError` codes through without a repair (any code except `PROVIDER_BAD_RESPONSE`).
- Checks `rate_topic`: evidence clause ids (attributes, findings, injection) are in `document`; attribute ids are in `topic` and appear once; value type equals attribute type; amount currency and duration unit are in the attribute's `units`; enum and categories ids are in `value_ids`, categories without repeats; a finding's `attribute` is null or a topic attribute.
- Checks `rate_other`: the answered clause ids equal the document's clause ids, each once; finding `attribute` is null.

## Not covered (gaps)

- Real adapter behaviour of `reasoning_effort` on Anthropic.

`RATE_TOPIC` and `RATE_OTHER` data blocks: role and special tokens (`<|start|>`, `<|im_start|>`, `[INST]`, `</document boundary=...>`, `Human:` at line start) are neutralized (absent verbatim); the nonce is never in clause text.

## Review round 1 additions

- `TextValue.text` is cleaned like an explanation (`clean_explanation` rules). On a Layer 2 hit (or empty after cleaning) the text becomes `EXPLANATION_WITHHELD` (the "withheld marker"; the value stays a `text` value, evidence kept; verification will not confirm it).
- A stated value (any type but `not_stated`) needs 1..3 evidence items; `not_stated` has none. Otherwise bad output (one repair). Enforced by schema or `rate_topic`.
- Topic free text (title, description, attribute and value labels) in the rating instruction is neutralized (`<|`, `|>`, `[INST]`, `</`, `<<<`, `>>>`, `Human:` at line start, also after NFKC). Tests lift the gate's text check with `monkeypatch.setattr(gate, "_check_texts", ...)` because the gate already refuses these texts.
- Neutralization covers every DOCUMENT and TEXT block of every template (tagging, check, suggest, document_json) and the TOPIC block of propose/expand, including fullwidth look-alikes (`＜｜`, `［INST］`).
- `rate_other(..., domain: str | None = None, catalog: Catalog | None = None)`: `side` must match `[a-z][a-z0-9_]{1,47}`; with a `catalog`, `catalog.has_side(domain, side)` must hold. Else `ValueError` before any call. More than 40 clauses: `ValueError` before any call.
- A string over its cap is the cap repair code (`REPAIR_CAP`).
- The Anthropic adapter puts no effort field on the wire.
