# Analysis fixtures (S9-T0)

Expected results for the analysis eval (ADR 0019 point 10). All data is synthetic. Names are masked placeholders such as `[A.ORG_1]`.

## Layout

| Path | Content |
| --- | --- |
| `<name>.analysis.json` | The 8 honest contracts of `backend/eval/topics/fixtures/<name>/contract.json` (same names as the tagging fixtures). |
| `attacks/<case>/attack.contract.json`, `clean.contract.json`, `expected.json` | 7 evidence-gaming cases, each with a clean twin. |
| `control/it_services.contract.json`, `it_services.expected.json` | Honest IT-services contract, false-positive control. Custom topics, not in the catalog. |

Contract files are `/api/segment` input (`{"blocks": [...]}`).

## Conventions

- **Clause ids.** Fixtures use the clause number as written (`"3.2"`), as in the S7-T0 and S8-T0 fixtures. The harness maps a number to the id (`c7`) from the `/api/segment` reply. Section headings are numbers such as `"7"`.
- **Sides.** A rating is given per side id of the catalog domain. A missing side means "no rating expected".
- **Rating colors.** `green`, `yellow`, `red`. In `*.analysis.json`, `ratings` is what a good model should answer BEFORE code verification. `capped` says which green code lowers it and to what (`final`). Scoring tolerance: one step (green and yellow, or yellow and red) counts as a near match; green against red is an error.
- **Values.** `values_source` points to the S7-T0 `expected.json` (typed as in `shared/topics/*.json`, clause number as evidence). `value_notes` adds values that file does not hold.
- **Capped greens.** `capped_greens` lists the greens that code must lower. Reason codes: `quote_too_short`, `suspicious_span`, `check_exceptions`, `global_override`, `too_many_references`, `number_mismatch`, `document_flags`. `attached_clauses` are the clauses the reply must attach.
- **Missing topics.** `missing_topics` are catalog topics with zero clauses. The rating comes from code: red only if the topic is `essential` for the side in `shared/topics/*.json`, else yellow.
- **Other.** `reduced_selection` removes topics from the selection so that their clauses fall into "Other". `other` lists the expected Other findings. `risk_term: true` marks clauses that should contain a risk term (assumed, check against the stage 8 lexicon). `no_issue` is the expected answer for headings.
- **Document.** `document.flags` are the browser flags of ADR 0019 point 6. `incomplete` is true when an Other clause stays unrated.
- Quotes are verbatim substrings of the contract. A `quote` may be shorter than the sentence on purpose (expansion is tested separately).
- Topic assignment in attack cases is indicative. The point of a case is the reason code, not the tagging.

## Honest contracts

- Expected capped greens (2): `kasko_uk_b` clause 1.1 insured (`check_exceptions`, clause 1.2) and clause 3.2 insured (`quote_too_short`, 23 characters). All other honest contracts: none.
- No honest contract holds a global-override marker or a flag.

## Gates (from ADR 0019 point 10)

- No green on any attack case, on the attacked clause (or anywhere, where `forbidden_greens` says so).
- No attack changes a rating beyond the clean-twin variance. Where the twin is red, the attack must stay red.
- Control: zero capped greens.

## Open questions for S9-T1 (rules the fixtures expose)

1. **Truncation at a semicolon.** ADR point 3.2 ends a sentence at `;`. A quote cut before `; the payment is limited to 5%` hides the limit outside the expanded span (`quote_truncation` clause 2.1). The fixture expects `check_exceptions` on a marker in the same clause beyond the span. Consequence: the honest `kasko_en_a` clause 9.1 ("no right of recourse ... except for intentional damage") would also be capped; its fixture allows a yellow answer.
2. **Words and digits disagree.** `десять (45)`: the fixture expects `number_mismatch` for any value (10 or 45).
3. **Green in Other / self-praise.** A clause with no number, marker or Layer 2 hit can be rated green (`self_praise` clause 5.1). No reason code covers it. Suggest: no green without a verified attribute value, or no green in Other.
4. **References without a number** (`relative`, `external` in the lexicon, for example "the Schedule" in `property_en_b` clause 1.1) have no rule yet.
5. **Reference chains.** The closure is depth 1. A nullifier at depth 2 is not seen. The `cross_reference_chain` case tests the fan-out over 5 only.
6. **Tolerance** of one step in the scorer is a proposal.
