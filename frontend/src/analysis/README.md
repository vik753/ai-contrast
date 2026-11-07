# S9-T4 analysis step: public names (contract for the implementation)

Written from `docs/agent/TASKS.md` S9-T4 (incl. 1a), ADR 0019 points 5, 8, 9, `backend/tests/analyze_api/README.md`, `src/tagging/README.md`.
Run: `cd frontend && npx vitest run src/analysis src/topics/TopicPanel.freepass.test.tsx`. All tests fail until the feature exists.
Helpers: `src/test/analysis-fakes.ts`. Names marked (choice) are the test engineer's; change one in one place (helper or README).
Wire shapes (snake_case) are exactly the events of the backend README. Events are typed as `AnalyzeEvent`.

## Modules in `src/analysis/`

| File               | Public names                                                                                                                                                                  |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `sseClient.ts`     | `MAX_EVENT_BYTES = 65536`, `MAX_STREAM_BYTES` (1..16 MiB, choice), `class SseError { code }`, `parseAnalysisStream(body, caps?)`, types `AnalyzeEvent`, `SseErrorCode`.       |
| `analyzeApi.ts`    | `analyzeDocument(req, onEvent, signal?, caps?)`, `ANALYZE_ERROR_CODES`, types `AnalyzeRequest`, `AnalyzeOutcome`, `DoneData`, `TopicEvent`, `OtherEvent`, `Finding`, `Value`. |
| `compare.ts`       | `compareValues(attribute, inputs)`, types `Direction`, `CompareInput`, `Mark`, `Comparison`.                                                                                  |
| `directions.ts`    | `directionsFromSelection(selection, catalog)`.                                                                                                                                |
| `cacheKey.ts`      | `buildAnalysisKey(parts)`, `selectionSignature(selection)`, `flagsHash(flags)`.                                                                                               |
| `ResultView.tsx`   | `ResultView(props)`, type `AnalysisResult`.                                                                                                                                   |
| `AnalysisStep.tsx` | `AnalysisStep(props)`.                                                                                                                                                        |

`CacheKey` is declared once, in `src/hash/key.ts`; `src/storage/cacheStore.ts` re-exports it (no second declaration). Existing tests may cast plain strings.
`TaggingResult` (in `TaggingStep.tsx`) gets `analysisPass?: string`: the pass held after that document's call (free mode); `App` passes the results to `AnalysisStep`.

## sseClient

- `parseAnalysisStream(body: ReadableStream<Uint8Array>, caps?: { maxEventBytes?, maxStreamBytes?, signal? }): AsyncGenerator<AnalyzeEvent>` where `AnalyzeEvent = { event: "start"|"topic"|"other"|"progress"|"done"|"error"; data: <wire object> }`.
- Event = `event: <name>\ndata: <one-line JSON>\n\n`. Comment blocks (`: ...`) are ignored. Chunks may split an event or a UTF-8 character.
- Throws `SseError` (`.code`): `unknown_event` (name not in the list), `malformed_json`, `malformed_event` (data not an object, a required key missing or of the wrong type, `done` without a 64-hex `result_signature`, `error` code not `^[a-z_]{1,64}$`, two `data:` lines, any event after `done`, or `start` not first), `event_too_large` (event over `maxEventBytes`, also an unterminated block that grows past it), `stream_too_large` (total bytes over `maxStreamBytes`).
- Abort: when `caps.signal` aborts, the reader is cancelled and the generator throws a `DOMException` named `AbortError`.

## analyzeDocument

- `analyzeDocument(req, onEvent, signal?, caps?) -> Promise<AnalyzeOutcome>`; `POST /api/analyze`. `onEvent` gets each parsed event at once (provisional).
- `AnalyzeRequest = { provider, model?, baseUrl?, key?, analysisPass?, domain, side, language: "en"|"uk"|"ru", document: SafetyDocument, topics: TopicSelection, tagging: TaggingResult, flags?: string[], annexLinks?: string[] }`.
- Body keys (only those present): `provider`, `model`, `base_url`, `domain`, `side`, `language`, `document { label, detector_version, clauses, acknowledged_unmasked }`, `topics { catalog, suggested, custom }`, `tagging { digest, tagging_version, signature, tags, incomplete_reasons, topics, client_tags }` (exactly these seven keys, values as received), `flags`, `annex_links`. Never: `check_model`, `turnstile_token`, `key`, `analysis_pass`.
- Headers: `Content-Type: application/json`, `Accept: text/event-stream`; key only in `X-Provider-Key`; pass only in `X-Analysis-Pass`; no `X-Free-Pass`. Fetch options `credentials: "omit"`, `redirect: "error"`, `cache: "no-store"`, `signal`.
- `AnalyzeOutcome`: `{ ok: true; done: DoneData | null; error: string | null }` (stream read to its end; `done` null when no `done` event came; `error` = code of an `error` event) | `{ ok: false; code }`. Refusal (non-200 JSON `{error}`): `code` from `ANALYZE_ERROR_CODES`, else `unknown`; reply not JSON or content type not `text/event-stream` on 200: `unknown`; fetch failure: `network`; a parser error: `stream_invalid`; abort: `aborted`. Server text is never returned.
- `ANALYZE_ERROR_CODES`: `request_too_large invalid_request invalid_provider invalid_model unexpected_model unexpected_base_url invalid_base_url unexpected_provider_key invalid_provider_key unexpected_analysis_pass unmasked_identifier detector_version_mismatch too_many_topics unknown_topic no_topics catalog_version_mismatch topic_flagged keyword_budget_exceeded tagging_signature_invalid invalid_client_tag too_many_client_tags document_too_large_for_analysis analysis_pass_invalid analysis_pass_expired analysis_pass_document_mismatch analysis_pass_exhausted free_quota_exhausted rate_limited busy provider_auth_failed provider_model_not_found provider_bad_request provider_blocked_host`. The UI adds `digest_mismatch`, `network`, `stream_invalid`, `aborted`, `unknown`.

## compare (pure)

- `Direction = "none"|"lower_better"|"higher_better"|"more_better"|"fewer_better"|readonly string[]` (list = enum value ids, best first).
- `CompareInput = { status: "verified"|"not_confirmed"|"not_analyzed"; value?: Value; capped?: boolean }`; `Value` is the wire value (`amount {number,currency}`, `percentage {number}`, `duration {number,unit}`, `enum {value}`, `categories {values}`, `text {text}`, `not_stated`). A stated "not stated" is `{ status: "verified", value: { type: "not_stated" } }`.
- `compareValues({ type, direction }, inputs) -> { status: "compared"|"not_comparable"|"text"; reason?: "unit"|"type"|"too_few"; marks: Mark[] }`; `marks[i]` belongs to `inputs[i]`; `Mark = "better"|"worse"|"same"|"different"|"not_compared"`.
- Only `verified` inputs with a real value take part. Others, and `not_stated`, get `not_compared` (two missing values are never "same"). Fewer than two taking part: `not_comparable`, `too_few`, all `not_compared`. Type `text`: status `text`, all `not_compared`. Different units (currency or duration unit) or different value types: `not_comparable` (`unit` / `type`), all `not_compared`; no conversion.
- Numbers (amount, percentage, duration): equal -> `same` for all. Unequal: `none` -> `different`; `lower_better` / `higher_better` -> the best is `better`, the others `worse`. Enum: ids equal -> `same`; list direction ranks by index (earlier is better); `none` -> `different`. Categories: equal sets (any order) -> `same`; `more_better` / `fewer_better` rank by set size; equal size but different sets, or `none` -> `different`. A `capped` input is compared but gets `different` instead of `better`/`worse` (and the others of that comparison likewise stay `different`).

## directions

`directionsFromSelection(selection, catalog) -> Record<"<topic_id>/<attribute id>", Direction>`: catalog refs read `directions[side]` of the catalog attribute; suggested and custom definitions use the attribute `direction` (an enum with a non-empty `order` gives that list).

## cacheKey

- `buildAnalysisKey({ documentDigest, contractTextHash: string|null, selectionSignature, analysisVersion, domain, side, model, language, flagsHash }) -> Promise<CacheKey | null>`: `null` when `contractTextHash` is `null` (a missing hash never collapses to a shared key); else a 64-hex key that changes with every field.
- `selectionSignature(selection)`: 64 hex of the canonical JSON; order of catalog refs, suggested and custom does not matter; any content change changes it.
- `flagsHash(flags)`: 64 hex of the sorted, de-duplicated flags.

## ResultView

`ResultView({ results: readonly AnalysisResult[], documents: readonly MaskedDoc[], topicNames?, directions? })`.
`AnalysisResult = { label, digest, complete: boolean, done: DoneData | null, topics: TopicEvent[], others: OtherEvent[], error: string | null }`. `complete` is true only after `done` with a `result_signature`.

- Root `data-testid="analysis-result"`. Per topic `result-topic-<topic id>` (heading: name, fallback id). State of a topic per document: `result-topicstate-<topic>-<label>` with `analysis.topic.state.<state>` and `analysis.topic.reason.<reason>`; `not_analyzed` is shown yellow.
- Attribute row `result-attr-<topic>-<attribute>`; cell `[data-doc="<label>"]` holds the value text: `5000 UAH`, `5 %`, `10 days`, enum id, category ids joined by `, `, the text. `not_confirmed`: only `analysis.value.not_confirmed` (the number is not shown); `not_stated`: `analysis.value.not_stated`; document without a complete result: `analysis.value.not_analyzed`.
- A mark is `[data-mark="<mark>"]` inside the cell, only for `better|worse|same|different`: icon `[data-mark-icon]` (aria-hidden) plus text `analysis.mark.<mark>`. A row note `result-note-<topic>-<attribute>`: `analysis.notComparable.<reason>` or, for `text`, `analysis.compareYourself`.
- Only documents with `complete` take part in the comparison; the others are `not_analyzed` cells. Direction from `directions["<topic>/<attribute>"]`, default `none`. A document with `done.greens_allowed === false` is `capped`.
- Finding: `[data-finding][data-rating="green|yellow|red"][data-doc="<label>"]` with icon `[data-rating-icon]` (aria-hidden), the text `analysis.rating.<rating>`, reasons `[data-reason="<code>"]` with `analysis.reason.<code>` placed before the explanation text, `analysis.explanationWithheld` instead of the string `explanation_withheld`, `analysis.unverified` when `unverified`. A green in a result that is not `complete` or has `greens_allowed === false` is shown yellow with reason `incomplete`.
- Quote: `[data-quote]` per evidence span, text = `clause.text.slice(start, end)` of the document's own masked clause. An unknown clause or a span outside the text shows nothing (no crash).
- "Other": `result-other-<label>`, heading `analysis.other.heading`; findings as above; `analysis.other.unrated` (`{{count}}`) when `done.unrated_other > 0`. Missing topic (`topic.missing`): `result-missing-<topic>-<label>` with the rating text and `analysis.missing.<yellow|red>`.
- `result-incomplete-<label>` with `analysis.incompleteNotice` when the result is not `complete` or `done.incomplete`.
- Plain text only: no `<a>`, `<img>`, `<script>`, no `dangerouslySetInnerHTML` in `src/analysis`.

## AnalysisStep

`AnalysisStep({ connection: TopicConnection & { checkModel? }, documents: readonly MaskedDoc[], selection, taggingResults: readonly TaggingResult[], topicNames?, directions?, language?: Lang, flags?: Record<label, string[]>, annexLinks?: Record<label, string[]>, textHashes?: Record<label, string|null>, cacheStore?: CacheStore, onResultsChange?(r: readonly AnalysisResult[]) })`.

- Region named `analysis.title`; absent when `taggingResults` is empty. Button `analysis.start`; `analysis.stop` while running. Language default: the UI language.
- Model: `modelPairOf(connection).strong` (free: none sent). Domain and side from the first topic of the selection. Free mode: no key; the pass of the last tagging result goes in `X-Analysis-Pass`; no pass: no call and an alert `analysis.error.analysis_pass_invalid`.
- Documents run one after another in `taggingResults` order (the next request starts after the previous stream ended). A result whose digest differs from the document with the same label is not analyzed.
- Per document `analysis-progress-<label>`: `analysis.status.<pending|running|done|incomplete|failed|stopped>`, and `role="progressbar"` `analysis-bar-<label>` (`aria-valuenow` = `progress.done`, `aria-valuemax` = `progress.total`). Per topic `analysis-topic-progress-<label>-<topic>` shows `analysis.topic.state.<state>` after its `topic` event.
- Provisional: while the stream runs, no `[data-rating="green"]`, no `[data-mark]`, no cache write. Done (`done` with `result_signature`): status `done`, `ResultView`, cache write. No `done` (stream ended, `error` event, abort, parser error): `incomplete` (or `failed` with an alert for refusal, error event or parser error; `stopped` after Stop); no greens, no marks, nothing cached.
- Errors: `role="alert"` with `analysis.error.<code>`, never server text.
- Cache: after `done` only, `cacheStore.put(key, "analysis", data)` once per document. `key` = `buildAnalysisKey` of: digest, `textHashes[label] ?? null`, `selectionSignature(selection)`, `done.analysis_version`, domain, side, model (free: `FREE_MODEL`), language, `flagsHash(flags[label] ?? [])`. `null` key: no write, the result is still shown. `data` holds no clause text. No cache read before a call (the version is unknown before `done`).
- Stop aborts the current stream; later documents are not sent. Clear all (`clearAllData()`) aborts every stream, drops results and statuses, and ignores any reply or event that comes later (nothing rendered, nothing cached, `onResultsChange` gets no results after it).

## i18n keys (en, uk, ru; same keys; uk and ru translated)

`analysis.title`, `.start`, `.stop`, `.status.{pending,running,done,incomplete,failed,stopped}`, `.topic.state.{ok,model_tags_dropped,not_analyzed}`, `.topic.reason.{too_many_clauses,topic_call_cap,bad_output,timeout,budget}`, `.rating.{green,yellow,red}`, `.reason.<every Reason>` (`quote_too_short suspicious_span check_exceptions global_override too_many_references unresolved_reference number_mismatch document_flags other_not_green unverified incomplete`), `.explanationWithheld`, `.unverified`, `.value.{not_confirmed,not_stated,not_analyzed}`, `.mark.{better,worse,same,different}`, `.notComparable.{unit,type,too_few}`, `.compareYourself`, `.other.heading`, `.other.unrated` (`{{count}}`), `.missing.{yellow,red}`, `.incompleteNotice`, `.error.<code>` for `ANALYZE_ERROR_CODES` plus the UI codes.

## Other follow-up covered (stage 7)

`src/topics/TopicPanel.freepass.test.tsx`: a free-pass reply that started before Clear all is not stored; the next topic call needs a new Turnstile token and sends no `X-Free-Pass`.
