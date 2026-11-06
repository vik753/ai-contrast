# Topic catalog (S7-T0)

Format: ADR 0017 point 1. One file per domain. Short objects (labels, enum values) are written on one line.

## Domains

| File | Domain | Sides | Topics |
| --- | --- | --- | --- |
| `kasko.json` | KASKO (voluntary motor insurance) | insured, insurer | 13 |
| `osago.json` | OSAGO / ОСЦПВ / ОСАГО (compulsory motor liability) | insured, insurer, injured_party | 9 |
| `lease.json` | Lease of premises | tenant, landlord | 10 |
| `property_insurance.json` | Property insurance | insured, insurer | 10 |

## Field names (choices the ADR leaves open)

- Topic: `descriptions` (language map), `synonyms` (language map of lists), `attributes`.
- Attribute: `labels`, `type`, `directions` (side id to direction).
- `amount` and `duration` list allowed units in `units` (`UAH`, `USD`, `EUR`, `percent_of_sum`; `days`, `working_days`, `months`, `years`).
- `enum` and `categories` list `values` as `{id, labels}`. Enum directions are an ordered list of value ids, best first.
- Synonyms: UK and RU entries are lowercase stems, so they cover case forms. A stem may end with a space to avoid longer words ("сто ").

## Essential topics (S9-T0)

A topic may hold `"essential": {"<side id>": true|false}`. It tells the analysis (ADR 0019 point 3.4) that a missing topic is red for that side; without the field, or with `false`, a missing topic is yellow. The keys must be side ids of the domain. Set only where clearly essential: risks, exclusions, deductible and sum insured (insurance), payout term for the claimant side, rent, term and termination (lease), tenant liability for damage.

## Eval fixtures

`backend/eval/topics/fixtures/<name>/contract.json` (`/api/segment` input) and `expected.json` (topics, attribute values, clause numbers, `absent_topics`).
Languages: kasko en and uk, osago uk and ru, lease en and ru, property uk and en. All values are fictional.

## Sources

Criteria describe consequences for the client; the contract wording in fixtures is invented. Pages below were not all fetched in full; check them before quoting any legal limit.

- Civil Code of Ukraine (insurance, ch. 67; lease, ch. 58): https://zakon.rada.gov.ua/laws/show/435-15
- Law of Ukraine "On Insurance": https://zakon.rada.gov.ua/laws/show/1909-20
- Law of Ukraine on compulsory third-party liability insurance of motor vehicle owners (limits, deductible, notice, payout terms, direct settlement, recourse): https://zakon.rada.gov.ua/laws/show/1961-15
- Press overview of OSAGO limit changes (search result, context only): https://mind.ua/publications/20252122-bagatomiljonni-viplati-ta-vilni-tarifi-yak-zminitsya-rinok-oscpv-v-ukrayini
- KASKO and property topics follow the usual headings of insurers' public rules (risks, exclusions, deductible, depreciation, notice, subrogation under Civil Code art. 993). No single insurer is the source.
