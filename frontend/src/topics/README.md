# S7-T3 topic panel: public names (contract for the implementation)

Written from `docs/agent/TASKS.md` S7-T3 (1, 1a, 2, 3), ADR 0017 points 3 and 7, `backend/tests/topic_ai/README.md`, `backend/tests/topics/README.md`.
Run: `cd frontend && npx vitest run src/topics`. All tests fail until the feature exists.
Wire names stay snake_case (`TopicDefinition`, `AttributeDefinition` as in the backend README). Helpers for the tests: `src/test/topics-fakes.ts`.

## Modules in `src/topics/`

| File             | Public names                                                                                                                                                                                                                                                                                                           |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `types.ts`       | `Catalog` (`{catalog_version, domains}`, body of `GET /api/topics/catalog`), `TopicDefinition`, `AttributeDefinition`, `CatalogRef` (`{domain, topic_id, side, lang, catalog_version}`), `TopicSelection` (`{catalog: CatalogRef[], suggested: TopicDefinition[], custom: TopicDefinition[]}`), `MAX_OWN_TOPICS = 10`. |
| `api.ts`         | `fetchCatalog(signal?)`, `suggestTopics(req, signal?)`, `proposeAttributes(req, signal?)`, `expandSynonyms(req, signal?)`, `TOPIC_ERROR_CODES`.                                                                                                                                                                        |
| `topicStore.ts`  | `createTopicStore({ storage?: Storage })` and the singleton `topicStore` (default `localStorage`).                                                                                                                                                                                                                     |
| `transfer.ts`    | `exportTopics(topics): string`, `importTopics(text: string): ImportResult`, `MAX_IMPORT_BYTES = 262144`.                                                                                                                                                                                                               |
| `TopicPanel.tsx` | `TopicPanel(props)` and the parts `DomainSelect`, `SideSelect`, `TemplateTopicList`, `SuggestedTopics`, `OwnTopicEditor`, `AttributeEditor` (own files, names as given). `App` renders `<TopicPanel>`; its provider props come from the provider settings (the implementation chooses how).                            |

## API helpers

- Common request: `{ provider: string; model?: string; baseUrl?: string; key?: string; turnstileToken?: string; freePass?: string }`.
- `suggestTopics({...common, domain, side, document: { label, detectorVersion, clauses, acknowledgedUnmasked }})` -> `POST /api/topics/suggest`, body keys `provider`, `model`, `base_url`, `turnstile_token`, `domain`, `side`, `document: { label, detector_version, clauses, acknowledged_unmasked }` (only keys that are present).
- `proposeAttributes({...common, topic})` -> `POST /api/topics/propose-attributes`; `expandSynonyms({...common, topic})` -> `POST /api/topics/expand-synonyms`; body `{ provider, ..., topic }`.
- Key only in header `X-Provider-Key`; free pass only in header `X-Free-Pass`; never in body, URL or query. `Content-Type: application/json`. Fetch options `credentials: "omit"`, `redirect: "error"`, `cache: "no-store"`. `fetchCatalog`: `GET /api/topics/catalog`, same options, no body, no key header.
- Result: `{ ok: true; data; freePass?: string } | { ok: false; code: string; field?: string; spans?: [number, number][] }`.
  `data`: suggest `{ suggestions: {id, name, description}[], dropped }`; propose `{ attributes: AttributeDefinition[], dropped }`; expand `{ synonyms_en, synonyms_uk, synonyms_ru, dropped }`; catalog: `fetchCatalog` returns `{ ok: true; data: Catalog }`.
  `freePass` is the reply's `free_pass` (string up to 256 characters). Malformed replies, extra keys at the top level and error codes outside `TOPIC_ERROR_CODES` give `code: "unknown"`; a fetch failure gives `"network"`. `field` and `spans` are kept only for `topic_contains_identifier` / text errors (numbers only). Server text is never shown.

## Topic store

- `getTopics(): readonly TopicDefinition[]` (own: `suggested` and `custom`), `add(t)`, `update(topic_id, t)`, `remove(topic_id)`, `replaceAll(list)`, `subscribe(fn): () => void`, `isPersisted(): boolean`, `setPersist(on: boolean)`, `clearAll()`.
- Memory by default; nothing is written to `localStorage`. `setPersist(true)` writes `aic.topics.v1` (JSON `{"version":1,"topics":[...]}`, topics only) and keeps it in step with every change; `setPersist(false)` and `clearAll()` remove the key (`clearAll` also empties memory). A store created over a storage that already holds a valid key starts persisted and loaded; invalid content is ignored and removed. Blocked storage never throws. App "Delete all data in this browser" calls `topicStore.clearAll()`.

## Import and export

- `exportTopics(topics)`: JSON text `{"version":1,"topics":[...]}`; `importTopics(exportTopics(x))` returns `x` equal.
- `ImportResult = { ok: true; topics: TopicDefinition[] } | { ok: false; code: ImportError }`, `ImportError` = `too_large` (over 256 KiB in UTF-8 bytes, checked before parsing), `invalid_json`, `forbidden_key` (`__proto__`, `constructor`, `prototype` anywhere), `invalid_shape` (extra or missing keys, wrong types, bad enums, `origin` not `suggested`/`custom`, wrong version), `too_many` (over 10 topics, 12 attributes per topic, 30 values per attribute, 40 synonyms per language, text over the ADR 0017 point 3 length caps). No partial result. Never throws.
- UI: file input labelled `topics.import.label`; failure shows `role="alert"` with `topics.import.error.<code>`; a button `topics.export.button` downloads the file.

## UI contract (names come from the en locale values of these keys)

- `TopicPanel({ connection: { provider, model?, baseUrl?, key? }, turnstileToken?: string, documents: readonly SafetyDocument[], onSelectionChange?(s: TopicSelection): void })`. Region named `topics.title`. It fetches the catalog on mount.
- Free pass: held in panel state. First free call with no pass sends `turnstileToken` in the body; every later call sends `X-Free-Pass` and no `turnstile_token`; a `free_pass` in any reply replaces the held pass; a `free_pass_*` error drops it.
- Domain: `<select>` labelled `topics.domain.label`, first option value `""` text `topics.domain.none`, then domain ids named in the UI language. Side: `<select>` labelled `topics.side.label`, options = the domain's sides in the UI language (absent with no domain); first side selected.
- Template topics: heading `topics.templates.heading`; one `listitem` per topic, with a checkbox labelled with the topic name (UI language), checked by default; the item shows each attribute label and its direction text `topics.direction.<direction>` for the chosen side (enum with an order: `topics.direction.ordered`). `onSelectionChange` gets `catalog` refs of the checked topics (`lang` = UI language).
- Suggest: button `topics.suggest.button`; one `POST /api/topics/suggest` per document in `documents`. Each suggestion is a `listitem` with name, description (plain text) and a button `topics.suggest.accept`. When `dropped > 0` (summed) text `topics.suggest.dropped` with `{{count}}` is shown. Accepting opens the own-topic editor with the name filled in and the description field empty; the topic keeps `origin: "suggested"` and `description: ""`.
- Own editor (group named `topics.own.heading`): textbox `topics.own.name`, textbox `topics.own.description` (optional), button `topics.own.propose`, then the attribute list (list named `topics.attr.list`): per `listitem` a textbox `topics.attr.label`, a `<select>` `topics.attr.direction`, a button `topics.attr.remove`. Directions start at `none` (also when the model proposed attributes); allowed options by type: `amount|percentage|duration`: `none, lower_better, higher_better`; `categories`: `none, more_better, fewer_better`; `enum` and `text`: `none`. The client's choice sets `direction_source: "client"` (every own attribute is `client`). Button `topics.own.confirm` adds the topic to the store (`origin` `custom`, or `suggested` after accept) and to `onSelectionChange`.
- Errors: `role="alert"` with `topics.error.<code>` for `topic_contains_identifier`, `topic_flagged`, `invalid_topic_text`, `ai_bad_output`, `free_quota_exhausted`, `busy`, `catalog_version_mismatch`, `rate_limited`, `free_pass_invalid`, `free_pass_expired`, `free_pass_exhausted`, `turnstile_failed`, `network`, `unknown`. For `topic_contains_identifier` with `field: "title"` or `"description"` the offending text is shown with each span in a `<mark>`.
- Plain text: no `<a>`, `<img>`, `<script>` or other element comes from model text; no `dangerouslySetInnerHTML` in `src/topics`.
- Storage: checkbox `topics.persist.label` (unchecked by default) calls `topicStore.setPersist`.

## i18n keys (en, uk, ru; same keys; uk and ru translated)

`topics.title`, `topics.domain.label`, `topics.domain.none`, `topics.side.label`, `topics.templates.heading`, `topics.suggest.button`, `topics.suggest.accept`, `topics.suggest.dropped` (`{{count}}`), `topics.own.heading`, `topics.own.name`, `topics.own.description`, `topics.own.propose`, `topics.own.confirm`, `topics.attr.list`, `topics.attr.label`, `topics.attr.direction`, `topics.attr.remove`, `topics.persist.label`, `topics.export.button`, `topics.import.label`, `topics.import.error.<code>` (`too_large invalid_json forbidden_key invalid_shape too_many`), `topics.direction.<d>` (`none lower_better higher_better more_better fewer_better ordered`), `topics.error.<code>` (list above).
