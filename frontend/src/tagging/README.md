# S8-T3 tagging step: public names (contract for the implementation)

Written from `docs/agent/TASKS.md` S8-T3, ADR 0018 points 1, 5, 7, 8, `backend/tests/tag_api/README.md`, `src/topics/README.md`, `src/provider/README.md`.
Run: `cd frontend && npx vitest run src/tagging`. All tests fail until the feature exists. Helpers: `src/test/tagging-fakes.ts`.
Names marked (choice) are the test engineer's; the tech lead may change one, then the helper changes in one place.

## Modules in `src/tagging/`

| File                 | Public names                                                                                                                                             |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `maskedDocsStore.ts` | `MaskedDoc = SafetyDocument & { digest: string }`; `createMaskedDocsStore()`; singleton `maskedDocsStore`; hook `useMaskedDocs(): readonly MaskedDoc[]`. |
| `tagApi.ts`          | `tagDocument(req, signal?)`, `TAG_ERROR_CODES`, types `TagReply`, `TagResult`.                                                                           |
| `estimate.ts`        | `estimateTagging(docs, topicCount)`, `modelPairOf(connection)`, `FREE_MODEL = "@cf/openai/gpt-oss-120b"`.                                                |
| `TaggingStep.tsx`    | `TaggingStep(props)`.                                                                                                                                    |

## maskedDocsStore

- In memory only. Never writes `localStorage`, `sessionStorage` or IndexedDB (no `setItem`, no `indexedDB.open`).
- `get(): readonly MaskedDoc[]` (ordered by label; a new array only when content changes), `set(doc: MaskedDoc)` (replaces the doc with the same `label`), `remove(label)`, `clearAll()`, `subscribe(fn): () => void` (fn runs after every change).
- `UploadForm` calls `maskedDocsStore.set` when the safety check of a contract is confirmed (the doc carries the masked clauses, `detectorVersion`, `acknowledgedUnmasked` and the `digest` of the safety reply) and `remove(label)` when that review is dropped or becomes "confirm again". `clearAllData()` (Delete all data) calls `maskedDocsStore.clearAll()`.
- `App` reads `useMaskedDocs()` and passes it to `TopicPanel` `documents` (Suggest enabled) and to `TaggingStep`.

## tagDocument

- `tagDocument({ provider, model?, checkModel?, baseUrl?, key?, turnstileToken?, analysisPass?, domain, side, document: SafetyDocument, topics: TopicSelection }, signal?)` -> `POST /api/tag`.
- Body keys (only those present): `provider`, `model`, `check_model`, `base_url`, `turnstile_token`, `domain`, `side`, `document: { label, detector_version, clauses, acknowledged_unmasked }`, `topics: { catalog, suggested, custom }`. The `digest` of a `MaskedDoc` is not sent.
- Key only in `X-Provider-Key`; analysis pass only in `X-Analysis-Pass`; never in body, URL or query. `X-Free-Pass` is never sent. `Content-Type: application/json`. Fetch options `credentials: "omit"`, `redirect: "error"`, `cache: "no-store"`.
- Result: `{ ok: true; data: TagReply; analysisPass?: string } | { ok: false; code: string }`. `TagReply` is the wire reply of the backend README (snake_case, `analysis_pass` excluded and returned as `analysisPass`). A malformed reply, an extra top-level key, or an error code outside `TAG_ERROR_CODES` gives `code: "unknown"`; a fetch failure gives `"network"`. Server text is never shown.
- `TAG_ERROR_CODES`: `request_too_large invalid_request invalid_provider invalid_model unexpected_model unexpected_base_url invalid_base_url unexpected_turnstile_token invalid_provider_key unexpected_provider_key unexpected_analysis_pass unmasked_identifier detector_version_mismatch too_many_topics unknown_topic no_topics catalog_version_mismatch topic_flagged keyword_budget_exceeded document_too_large_for_tagging too_many_documents free_too_large analysis_pass_invalid analysis_pass_expired analysis_pass_exhausted analysis_pass_unavailable turnstile_failed free_quota_exhausted free_mode_unavailable rate_limited busy provider_auth_failed provider_model_not_found provider_bad_request provider_blocked_host`. The UI adds `digest_mismatch`, `network`, `unknown`.

## estimate

- `estimateTagging(docs, topicCount) -> { calls, maxCheckCalls, inputTokens }`. Per document with `chars` = code points of all clause texts and `n` clauses: `batches = chars === 0 ? 0 : max(ceil(chars / 12000), ceil(n / 40))`; `calls = sum(batches)`, `maxCheckCalls = sum(batches)`, `inputTokens = sum(ceil(chars / 3) + batches * (200 + 60 * topicCount))`.
- `modelPairOf({ provider, model?, checkModel? }) -> { cheap, strong }`: `free` gives `FREE_MODEL` twice; otherwise `cheap = model`, `strong = checkModel ?? model`.

## TaggingStep

`TaggingStep({ connection: TopicConnection & { checkModel?: string }, turnstileToken?: string, documents: readonly MaskedDoc[], selection: TopicSelection, topicNames?: Readonly<Record<string, string>>, onResultsChange?(r: readonly TaggingResult[]): void })`.

- `TopicPanel.onSelectionChange(selection, names)` gets a second argument `names: Record<topic id, display name in the UI language>`; `App` passes both to `TaggingStep`.
- `TaggingResult = { label, digest, taggingVersion, signature, reply: TagReply, clientTags: Record<clauseId, string[]> }`. The signature is kept exactly as received.
- Domain and side come from the first topic of the selection (catalog ref or definition). Region named `tagging.title`; absent when `documents` is empty.
- Before start, in the region: `data-testid="tag-pair"` with `tagging.pair` (`{{cheap}}`, `{{strong}}`) and `data-testid="tag-cost"` with `tagging.cost` (`{{calls}}`, `{{checks}}`, `{{tokens}}`). Button `tagging.start`, disabled with an empty selection (then `tagging.noTopics` is shown).
- Start tags the documents one after another (one `POST /api/tag` each). Per document `data-testid="tag-progress-<label>"` shows `tagging.status.<pending|running|done|failed>`.
- Result per document `data-testid="tag-result-<label>"`: each clause is `[data-clause-id]` with its text (plain text) and chips `[data-topic-id][data-source]` where source is `keyword|model|check|client`. A chip holds the topic name (fallback: id), an icon element `[data-source-icon="<source>"]` (aria-hidden) and the text `tagging.source.<source>`.
- "Other": `data-testid="tag-other-<label>"` with heading `tagging.other.heading` and the clauses of `other`; risk-term spans are wrapped in `<mark data-risk>`; each such clause shows `tagging.risk.label`.
- Per topic `data-testid="tag-topic-<label>-<topic id>"`: counts `tagging.counts` (`{{keyword}}`, `{{model}}`), `tagging.flag.model_tags_dropped` when dropped, `tagging.flag.not_analyzed.<reason>` when not analyzed. `missing_topics`: `data-testid="tag-missing-<label>"`, heading `tagging.missing.heading`.
- `model_tagging_incomplete`: `data-testid="tag-incomplete-<label>"` with `tagging.incomplete.<reason>` for each reason.
- Layer 2: inside a clause, `[data-layer2="heuristic"|"high"]` with text `tagging.layer2.<cls>` (heading hits and text hits alike).
- Client tags: in each clause a `<select>` labelled `tagging.add.label` (options: selected topics the clause has no tag for) and a button `tagging.add.button`. Keyword, model and check chips have no remove button; a client chip has `tagging.client.remove`. The select offers no topic whose `keyword_clauses` plus client tags reach 120, and is disabled with `tagging.add.clauseCap` when the clause already has 5 non-keyword tags (model, check, client). Only ids from the reply and the selection can be chosen.
- Errors: `role="alert"` with `tagging.error.<code>` (never server text). A reply whose `digest` differs from the document digest gives `digest_mismatch` and no result.
- Free mode (`connection.provider === "free"`): no `X-Provider-Key`. At the start of an analysis there is no pass: the first call mounts `TurnstileFrame` (unless `turnstileToken` is given) and sends `turnstile_token`; the reply `analysis_pass` is held in state and sent as `X-Analysis-Pass` (no `turnstile_token`) on the next document; an `analysis_pass_*` error drops it. Pressing start again begins a new analysis and needs a new Turnstile token.
- Plain text only: no `<a>`, `<img>`, `<script>` from clause text; no `dangerouslySetInnerHTML` in `src/tagging`.

## i18n keys (en, uk, ru; same keys; uk and ru translated)

`tagging.title`, `tagging.start`, `tagging.noTopics`, `tagging.pair`, `tagging.cost`, `tagging.status.{pending,running,done,failed}`, `tagging.source.{keyword,model,check,client}`, `tagging.risk.label`, `tagging.other.heading`, `tagging.counts`, `tagging.flag.model_tags_dropped`, `tagging.flag.not_analyzed.too_many_clauses`, `tagging.missing.heading`, `tagging.incomplete.{bad_output,timeout,quota,check_failed,clause_cap}`, `tagging.layer2.{heuristic,high}`, `tagging.add.{label,button,clauseCap}`, `tagging.client.remove`, `tagging.error.<code>` for every code of `TAG_ERROR_CODES` plus `digest_mismatch`, `network`, `unknown`.
