# S7-T1 tests: public names (the contract for the implementation)

Written from `docs/agent/TASKS.md` S7-T1, ADR 0017 points 1-5, ADR 0009 Layer 2, ADR 0015 point 5.
Run: `cd backend && uv run --locked pytest tests/topics tests/test_injection_*.py tests/ai/test_ai_request_fieldsets.py tests/check -q`.
All new tests fail until the feature exists. Tests use synthetic catalogs in `tests/topics/fixtures/`, never `shared/topics/`.

## Catalog (`app/topics/catalog.py`)

- `load_catalog(path: Path) -> Catalog`. `path` is a directory; every `*.json` in it is one domain. Raises `CatalogError` (an `Exception`) for a missing or empty directory, a file that is not valid JSON, any schema or cap violation, an unknown key (`extra="forbid"`), a duplicate id, and any text that fails the topic safety pass.
- `Catalog` (Pydantic, frozen): `catalog_version: str` (SHA-256 hex of the file contents, independent of the path and of directory order), `domains: tuple[Domain, ...]` (sorted by `id`).
  `Catalog.model_dump(mode="json")` is exactly the body of `GET /api/topics/catalog`.
- `Domain`: `id`, `names`, `sides` (each `.id`, `.names`), `topics`. `Topic`: `id`, `names`, `descriptions`, `synonyms` (`{en, uk, ru}` lists), `attributes`. `Attribute`: `id`, `labels`, `type`, optional `units`, optional `values` (each `id`, `labels`), `directions` (side id to direction). Layout as in `shared/topics/README.md` (S7-T0).
- File format: see `fixtures/catalog_ok/*.json`. Direction per side id: `lower_better | higher_better | none` (amount, percentage, duration), a list of value ids, best first, or `"none"` (enum), `more_better | fewer_better | none` (categories), `"none"` only (text). Every side of the domain has an entry. `amount` units come from `UAH, USD, EUR, percent_of_sum, percent_of_loss`, `duration` units from `hours, days, working_days, months, years`; `units` is allowed on those two types only and is non-empty.
- `Catalog.definition(domain_id, topic_id, side, lang) -> TopicDefinition`: the catalog topic for one side and one UI language (`origin="catalog"`, every attribute `direction_source="catalog"`, all three synonym lists).
- App: `Settings.topics_catalog_dir: Path` (env `TOPICS_CATALOG_DIR`); `create_app` loads it at startup and fails on an invalid catalog. `GET /api/topics/catalog` -> 200 JSON, `Cache-Control` with `max-age`, no body or header needed, no AI call.

## Topic text (`app/topics/safety.py`)

- `TextKind` (`enum.StrEnum`): `NAME` (1-80), `DESCRIPTION` (1-200), `LABEL` (1-200), `VALUE` (1-60), `SYNONYM` (3+ letters, at most 60, no stop-word).
- `check_topic_text(text: str, kind: TextKind, lang: str | None = None) -> None`. Raises `TopicTextError` with `.code` in `invalid_topic_text | topic_contains_identifier | topic_flagged`, `.spans: tuple[tuple[int, int], ...]` (start, end in `text`; non-empty only for `topic_contains_identifier`), `.field: str | None` (set by `confirm_topic`, else `None`). `str(error)` is the code only: never the text. `lang` (`en|uk|ru`) selects the stop-word list of a synonym; `None` checks all three.
- Order: Layer 1 idempotent and NFC, grammar, placeholder look-alikes on the skeleton (all `invalid_topic_text`), identifier detector, Layer 2.

## Layer 2 (`app/injection/`)

- `scan(text: str) -> list[Hit]`; `Hit(cls: Literal["heuristic", "high"], start: int, end: int)` frozen dataclass, offsets into `text`, sorted by `start`. Input is Layer 1 clean text; NFKC and the confusable skeleton are applied inside. `PATTERNS_VERSION: str`.

## Gate (`app/pseudo/gate.py`)

- `TopicDefinition` (`app/topics/model.py`, Pydantic, frozen, `extra="forbid"`): `origin: "catalog" | "suggested" | "custom"`, `domain: str | None = None`, `topic_id: str`, `title: str`, `description: str = ""`, `side: str`, `attributes: tuple[AttributeDefinition, ...] = ()`, `synonyms_en/uk/ru: tuple[str, ...] = ()`.
  `AttributeDefinition`: `id`, `label`, `type` (`amount|percentage|duration|enum|categories|text`), `units: tuple[str, ...] = ()`, `direction: str = "none"`, `order: tuple[str, ...] = ()`, `values: tuple[str, ...] = ()`, `direction_source: "catalog" | "client" = "client"`.
- `confirm_topic(definition: TopicDefinition, *, catalog: Catalog | None = None) -> ConfirmedTopic`. Runs `check_topic_text` on every text (title NAME, description DESCRIPTION, labels LABEL, values VALUE, synonyms SYNONYM) and raises `TopicTextError` (with `.field`). Other refusals raise `TopicDefinitionError(code)` (`app/topics/model.py`): `invalid_topic_definition` (bad id, type or direction for the type, more than 12 attributes, 30 values or 40 synonyms per language, suggested topic with a description, `origin="catalog"` without `catalog`), `invalid_direction` (non-catalog attribute with direction other than `none` and `direction_source="catalog"`), `catalog_topic_changed` (`origin="catalog"` and the definition differs from the catalog's), `topic_too_large` (non-catalog topic over 4096 UTF-8 bytes in all text fields).
- `ConfirmedTopic` (frozen, slots, sentinel): `domain`, `topic_id`, `title`, `description`, `side`, `attributes: tuple[ConfirmedAttribute, ...]`, `synonyms_en/uk/ru: tuple[str, ...]`. No document field. `ConfirmedAttribute` (same protections): `id`, `label`, `type`, `units`, `direction`, `order`, `values`, `direction_source`.
- Direction for the attribute type: `amount|percentage|duration`: `lower_better|higher_better|none`; `enum`: `ordered` (needs `order`, a permutation of `values`) or `none`; `categories`: `more_better|fewer_better|none`; `text`: `none`.

## AI port

- `PromptTemplate` gains `SUGGEST_TOPICS`, `PROPOSE_ATTRIBUTES`, `EXPAND_SYNONYMS`. `AIRequest.document` becomes optional (keyword use only). Field sets (checked in `__post_init__`, `TypeError` or `ValueError`): `DOCUMENT_JSON`: document required, topic and text optional (unchanged); `SUGGEST_TOPICS`: document required, topic and text forbidden; `PROPOSE_ATTRIBUTES`, `EXPAND_SYNONYMS`: topic required, document and text forbidden.

## Stage 6 follow-up

- `create_app(settings=None, *, provider_transport=None, turnstile_transport=None, clock=None)` passes the hooks to `provider_check.install()`. `CheckState` never reads `app.state.provider_transport`, `.turnstile_transport` or `.clock`.
