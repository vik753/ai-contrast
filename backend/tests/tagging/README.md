# S8-T1 tests: public names (the contract for the implementation)

Written from `docs/agent/TASKS.md` S8-T1 and ADR 0018 points 2, 4, 5, 6 (plus ADR 0009 "tagging cannot hide a clause").
Run: `cd backend && uv run --locked pytest tests/tagging -q`. All tests fail until the feature exists.
All data is synthetic. No network, no AI.

## `app/tagging/model.py`

- `TagClause(id: str, text: str, heading: str | None = None)`: frozen dataclass. `id` is `c<n>`. The heading counts as clause text.
- `TagMergeError(Exception)` with `.code: str`; `str(error)` is the code only.

## `app/tagging/keywords.py`

- `keyword_tags(clauses: Sequence[TagClause], topics: Sequence[ConfirmedTopic]) -> dict[str, set[str]]`.
  Key: every clause id (empty set if no tag). Value: topic ids. All three synonym lists of a topic are used.
- Matching on the NFKC + confusable skeleton, case-insensitive. A synonym is a sequence of words; every word matches a word **prefix** of the clause word (stem). Words are split on non-letters/digits; whitespace between phrase words is any run of whitespace and line breaks. A match never starts mid-word. Synonym text is literal (no regex). Heading and text are both scanned, never joined into one phrase across the boundary.
- `KEYWORD_RULES_VERSION: str`: changes whenever the matching rules change (read at call time by `tagging_version`).

## `app/tagging/risk_terms.py`

- `scan_risk(text: str) -> list[tuple[int, int]]`: `[start, end)` offsets into `text`, sorted, one per hit, each starting at a word start. EN/UK/RU stems on the skeleton view.
- `RISK_TERMS_VERSION: str`.

## `app/tagging/merge.py`

`merge_tags(*, clauses, topics, keyword, model_high=None, model_low=None, check_yes=None, client=None, failures=()) -> TaggingResult`

- `keyword`: output of `keyword_tags`. `model_high`: `{clause_id: {topic_id}}` model tags with confidence high. `model_low`: low-confidence pairs. `check_yes`: low pairs the check call confirmed (source `check`). `client`: `{clause_id: {topic_id}}`. `failures`: reasons from `bad_output | timeout | quota | check_failed`.
- A low pair becomes a tag only if it is in `check_yes` and `check_failed` is not in `failures`. If `check_failed` is present, every low pair is dropped.
- Client tags: unknown clause id or topic id raises `TagMergeError` (`invalid_client_tag`); more than 5 client tags on one clause raises `TagMergeError` (`too_many_client_tags`). They only add.
- `TaggingResult` (frozen dataclass):
  - `tags: dict[str, dict[str, str]]`: every clause id -> `{topic_id: source}`, source in `keyword | model | check | client`. A pair present in several sources keeps the first of that order.
  - `other: list[str]`: clause ids in document order that need "Other" (no tag at all, or only tags of dropped/not-analyzed reasons below).
  - `risk: dict[str, list[tuple[int, int]]]`: for "Other" clauses with risk-term hits only (spans in `text`).
  - `topics: dict[str, TopicStatus]` for every topic: `TopicStatus(keyword_clauses: int, model_clauses: int, model_tags_dropped: bool, not_analyzed: str | None)`. `keyword_clauses` counts clauses with a keyword or client tag; `model_clauses` counts clauses with a model or check tag kept (0 after a drop); `not_analyzed` is `"too_many_clauses"` or `None`.
  - `model_tagging_incomplete: bool`, `incomplete_reasons: tuple[str, ...]` (sorted, unique, = `failures`).
  - `missing_topics: tuple[str, ...]` (topic order).
- Rules: model tags only add. At most 5 model/check-source tags per clause (keyword and client tags not part of that number). More than 60 clauses with model/check tags for one topic: all model/check tags of that topic dropped, flag, clauses without another tag go to `other`. More than 120 clauses with keyword or client tags for a topic: `not_analyzed`; its keyword tags stay, and a clause whose only tags belong to not-analyzed topics also goes to `other`. Missing topic: zero clauses, no failures, not dropped, not not-analyzed.

## `app/tagging/layer2.py`

- `clause_hits(clauses) -> dict[str, ClauseHits]`: only clauses with a hit. `ClauseHits(text: list[Hit], heading: list[Hit])`, `Hit` from `app.injection`, offsets relative to the scanned string. Results equal `scan()` of that string.

## `app/tagging/version.py`

- `tagging_version() -> str` matching `^[a-z0-9-]{1,64}$`, deterministic. Reads at call time (module attributes, so tests can patch them) `app.tagging.keywords.KEYWORD_RULES_VERSION`, `app.tagging.risk_terms.RISK_TERMS_VERSION` and `app.injection.patterns.PATTERNS_VERSION`.
