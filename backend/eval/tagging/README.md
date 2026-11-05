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
- Adversarial metrics are scored separately (`:adversarial`), never mixed into domain or language totals.
- `fixed` adversarial metrics use a fully compromised model answer built in code: on `skip_me` the model obeys the injected sentence; on `flood` it puts 5 tags on every clause (the per-topic cap must drop them).
