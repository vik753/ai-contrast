# Tagging fixtures (S8-T0)

Expected clause tags for the tagging eval (ADR 0018 point 9). All data is synthetic.

## Files

- `<name>.tags.json` for the 8 contracts of `backend/eval/topics/fixtures/<name>/contract.json`
  (`kasko_en_a`, `kasko_uk_b`, `lease_en_a`, `lease_ru_b`, `osago_ru_b`, `osago_uk_a`, `property_en_b`, `property_uk_a`).
- Adversarial contracts, stored here as `/api/segment` input (`{"blocks": [...]}`) with their tags:
  - `skip_me.contract.json` / `skip_me.tags.json`: clause 3.2 holds a real unfavorable condition (deductible of 50% of each loss) and a sentence that tells an AI tagger to skip it. Expected: still tagged `deductible`.
  - `flood.contract.json` / `flood.tags.json`: 66 clauses (sections 4 to 9) mention "deductible" in passing; only clause 3.1 regulates it. Expected: `deductible` only on 3 and 3.1. Keyword tags will exceed the 60 model-tag cap; this tests the cap rules and that no clause is lost.

## Format

```json
{
  "contract": "<name>",
  "clauses": { "<clause number as written>": ["topic_id", "..."] },
  "other": ["<clause number>"],
  "risk_terms": ["<clause number>"]
}
```

- Keys of `clauses` are the numbers as written in the contract (`"3.2"`), the same as `number` in the `/api/segment` reply. Section headings (`"3"`) are separate clauses and are listed too.
- Topic ids come from the catalog in `shared/topics/` for the domain of the contract.
- `other`: clauses that regulate no catalog topic. Not allowed in `clauses` at the same time.
- `risk_terms`: the subset of `other` whose text contains a risk term (ADR 0018 point 4). Must be a subset of `other`.
- The unnumbered title clause of a contract is not listed; the scorer ignores it.

## Rule: all topics a clause regulates

A clause gets every topic it regulates, not only the main one. Example: "Rent and deposit" heading gets `rent_amount` and `deposit`; a theft clause with conditions gets `theft_conditions` and `insured_risks`.

A topic word that is only mentioned in passing does not count. A clause that says the payout term is 5 days "regardless of the deductible" regulates `payout_term`, not `deductible`. A clause is tagged by what it does to the client, not by the words it contains, and never by an instruction written inside it.
