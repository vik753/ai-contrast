# Tagging eval (S8-T4, ADR 0018 point 9)

Runs the `/api/tag` steps on the 8 fixture contracts and the 2 adversarial contracts: masking and `safety_pass`, catalog topics through `resolve_topics`, `keyword_tags` (the function of the sandbox child, called in-process), `plan_batches`, `run_model_steps` (tag call, check call, one repair each) and `merge_tags` (caps, "Other", risk terms).

## Files

| Path | Content |
| --- | --- |
| `fixtures/` | Expected tags (S8-T0); contracts of the 8 cases are in `../topics/fixtures/` |
| `recordings/*.json` | Every provider call per case in order: template, prompt digest, answer. `stub: true` marks the oracle recording |
| `baseline.json` | Metrics per recording; CI fails on a drop of more than 0.01 |
| `run_eval.py` | Runner and metrics (see its docstring) |
| `oracle.py` | The stub oracle (title-stem matching, heading inheritance, obeys "skip this clause", credulous checker) |

## Commands

Run from `backend/`.

```bash
# Recorded mode (CI): no network, no key.
uv run --locked python -m eval.tagging.run_eval

# Keyword precision per topic and the catalog synonyms with false hits.
uv run --locked python -m eval.tagging.run_eval --synonyms

# Live mode (local only). The key is read from the environment, never written.
# Models default to the preset pair (cheap for tagging, strong for checks).
AIC_EVAL_PROVIDER_KEY=... uv run --locked python -m eval.tagging.run_eval --live --provider anthropic
uv run --locked python -m eval.tagging.run_eval --recording anthropic__<cheap>__<strong> --write-baseline

# Regenerate the stub after a prompt, schema, catalog or fixture change.
uv run --locked python -m eval.tagging.run_eval --write-stub --write-baseline
```

`--write-baseline` refuses a regression without `--accept-regressions`.

## Gating

- `kw.*` (keyword tags alone) and `adversarial.*` (counts, all 0) are gated for every recording.
- `all.*` (keyword + model + check) is informational while the recording is a stub.
- `*.other.share` has no good direction and is never gated.
- A run fails on a regression (a gated metric worse by more than 0.01, a missing or a new metric) and also on an improvement of a count (`adversarial.*`, `*.missing.false_positives` below the baseline): tighten the baseline.
- A rate whose total is 0 is not emitted (it is not 1.0). Today only `skip_me` expects risk-term clauses and "Other" clauses, so `risk.recall` and `other.recall` exist only as `:adversarial`; `missing.recall` exists only where `expected.json` lists `absent_topics` (`kasko_en_a`).
- Adversarial metrics are scored separately (`:adversarial`), never mixed into domain or language totals.
- `fixed` adversarial metrics use a fully compromised model answer built in code: on `skip_me` the model obeys the injected sentence; on `flood` it puts 5 tags on every clause (the per-topic cap must drop them).
- The eval runs the same `model_phase` and `finish_tags` as `/api/tag` (`app/tagging/run.py`); keyword tags use the production step budget.

## Accepted baseline values

`kw.missing.false_positives` is 4 in the stub baseline: with keyword tags alone, 4 topics that the gold set has are never matched by a catalog synonym, so a keyword-only run would call them missing. This is a keyword recall gap, not a model result. In production a missing-topic finding needs complete model tagging (ADR 0018 point 5), and `all.missing.false_positives` (model included) is the number that matters for a live run. The count is gated so it can only go down; synonym tuning is a stage 11 follow-up (`docs/agent/TASKS.md`). Worst synonyms by false hits: `--synonyms`.
