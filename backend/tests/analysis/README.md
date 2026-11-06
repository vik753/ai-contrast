# S9-T1 tests: public API of `app.analysis.verify`

Written from ADR 0019 points 3 and 4 and TASKS S9-T1, before the implementation.
All types are frozen dataclasses (`slots` allowed). Enums are `StrEnum`.
Everything is exported from `app.analysis.verify`. Clause ids and offsets only leave the module, never clause text.

```python
Span = tuple[str, int, int]            # (clause_id, start, end) into Clause.text

class Rating(StrEnum): green, yellow, red
class Reason(StrEnum):
    quote_too_short, suspicious_span, check_exceptions, global_override,
    too_many_references, number_mismatch, document_flags, other_not_green,
    unverified, incomplete, unresolved_reference
class DocFlag(StrEnum): not_read_material, hidden_text_removed
class ValueStatus(StrEnum): verified, not_confirmed
class TopicState(StrEnum): ok, model_tags_dropped, not_analyzed

Clause(id: str, text: str, heading: str = "", number: str | None = None)   # number "1.1", "4.2"
Evidence(clause: str, quote: str)
NumericValue(number: Decimal, unit: str | None)   # catalog units: days, working_days, months, years, UAH, USD, EUR,
                                                  # percent_of_sum, percent_of_loss; None for a `percentage` attribute (a % sign or percent word)
Finding(rating: Rating, evidence: tuple[Evidence, ...], topic: str | None,  # None = "Other" finding
        attribute: str | None = None, value: NumericValue | None = None)
DocumentContext(clauses: tuple[Clause, ...],
    topic_clauses: Mapping[str, frozenset[str]] = {},       # topic id -> clause ids
    flags: frozenset[DocFlag] = frozenset(),
    unprovided_reference_clauses: frozenset[str] = frozenset(),
    layer2_spans: tuple[Span, ...] = (),
    layer2_heuristic_clauses: frozenset[str] = frozenset(),
    injection: tuple[Evidence, ...] = (),                   # injection_suspected items
    incomplete: bool = False)                               # document_completeness(...).incomplete
```

Functions (pure, no I/O, no regex built from client text):

- `verify_quote(clause: Clause, quote: str) -> QuoteCheck(ok: bool, spans: tuple[tuple[int, int], ...])`.
  Whitespace runs fold to one space on both sides; nothing else folds. `spans` are offsets into the
  original `clause.text` of EVERY occurrence. Empty or absent quote: `ok=False`, `spans=()`.
- `expand_quote(text: str, start: int, end: int, abbreviations: frozenset[str] | None = None) -> tuple[int, int]`.
  Sentence end is `. ; ! ?` followed by whitespace or end of text; the terminator is included, leading
  whitespace is not. A period after an abbreviation (case-insensitive token ending at the period, starting
  at text start, whitespace or `(`) is not a sentence end; a period between digits is not either.
  `None` means the checked-in lexicon list. Never leaves `[0, len(text)]`.
- `apply_green_rules(ctx, finding) -> RatedFinding`.
  `RatedFinding(rating, reasons: tuple[Reason, ...], verified_spans: tuple[Span, ...],
  attached: tuple[Span, ...], dropped_quotes: int, unverified: bool)`.
  `verified_spans` are expanded spans of every occurrence of every verified quote. `attached` holds the
  spans of the clauses that caused `check_exceptions` / `global_override`. Only a green can be capped (to
  yellow, reasons filled). Yellow and red never change rating and never go up. No verified quote: `unverified=True`,
  green becomes yellow with `Reason.unverified`. Other findings (`topic is None`): green becomes yellow with
  `other_not_green`. A clause in `injection` with a valid clause id blocks green for that clause
  (`suspicious_span`) whatever its quote.
- `reference_closure(clauses: Sequence[Clause], start_ids: Iterable[str], max_refs: int = 5) -> dict[str, ClosureEntry]`.
  `ClosureEntry(added: tuple[str, ...], needed: int, too_many: bool)`. Per start clause: distinct clauses (by
  `Clause.number`) referenced by it, excluding itself, in order of appearance, depth 1. `added` holds at most
  `max_refs`; `needed` is the full count; `too_many = needed > max_refs`. Cycles never loop.
- `verify_value(ctx, v: ValueIn) -> ValueOut`.
  `ValueIn(attribute: str, evidence: tuple[Evidence, ...], topic: str | None = None, number: NumericValue | None = None)`.
  `ValueOut(status: ValueStatus, reasons: tuple[Reason, ...])`. `verified` only with at least one verified
  quote, the number check (if `number` given), and none of: `check_exceptions`, `suspicious_span`,
  `too_many_references`, `global_override`, `document_flags`, `incomplete`. Otherwise `not_confirmed` (with those
  reasons, `number_mismatch`, or `unverified`). `quote_too_short` and `other_not_green` never affect a value.
- `missing_topic_findings(tagging: TaggingState, topics: Sequence[TopicInfo]) -> tuple[MissingTopicFinding, ...]`.
  `TaggingState(complete: bool, signed: bool)`; `TopicInfo(id: str, clause_count: int, state: TopicState, essential: bool)`;
  `MissingTopicFinding(topic: str, rating: Rating)` (yellow, or red when essential; never green).
  Not complete or not signed: empty tuple (fail closed). Only topics with `clause_count == 0` and `state == ok`.
- `document_completeness(other_total: int, other_rated: int) -> Completeness(incomplete: bool, unrated_other: int, greens_allowed: bool)`.
- `other_clause_ids(tagged_other: Sequence[str], topic_clauses: Mapping[str, Sequence[str]], not_analyzed: Collection[str]) -> tuple[str, ...]`:
  `tagged_other` first, then clauses of `not_analyzed` topics, no duplicates, first-seen order.

Number check (used by `apply_green_rules` and `verify_value`): the value's number is found in the expanded
quote next to a unit word of the value's unit (EN/UK/RU lexicon); forms: digits, decimal comma or point,
thousands separated by spaces, words 0-100, "десять (10)" (words plus digits = one number; contradicting
digits = mismatch). More than one number of the unit in the expanded quote = mismatch.

Run: `cd backend && uv run --locked pytest tests/analysis -q`. All tests fail with ImportError before the implementation.

## Hardening additions (S9-T0 security review)

- Matching of markers (exception, global override), clause references and unit words runs on normalized
  text: NFKC, case-folded, look-alike letters mapped (Latin/Cyrillic), hyphen variants (U+2011, dashes)
  mapped to `-`, apostrophe variants (`'` U+2019 U+02BC `` ` `` U+FF07) mapped to one, format characters removed.
  Offsets still refer to the original text.
- References: any dotted number equal to an existing `Clause.number` counts even without a prefix word. Ranges
  ("4.1-4.3", "4.1\u20134.9", "з 4.1 по 4.3", "с 4.1 по 4.3") expand to the existing flat-numbered clauses in range
  (ordered by number); they count toward `needed` and the limit of 5.
- `Reason.unresolved_reference`: the quoted clause holds a relative or external reference ("as set out above",
  "згідно з Правилами", "указанных выше") and caps the green.
- Number check: a number word the code cannot parse ("half", "two hundred", "півтора", "полтора") next to a unit
  word of the value's unit is `number_mismatch`; "десять (45)" (words contradict digits) is a mismatch for any value.
