# ADR 0015 — Pseudonymization: implementation in stage 5b

- Status: proposed (tech lead, 2026-10-28; waiting for `security-reviewer`)
- Date: 2026-10-28
- Related: ADR 0008 (design — this ADR only fixes the interfaces), ADR 0009 (Layers 1–2), ADR 0013 (no mapping in storage), ADR 0014 (segmentation), threat model T3, T5, T11

## Context

ADR 0008 defines what is masked, the pipeline, the type gate and the tests. Stage 5b builds it. Stages 6 and 9 add the AI provider and the analysis endpoint; they must find the gate, the safety pass and the canary harness ready.

## Decision

1. **Detection is part of `/api/segment`** (ADR 0014 point 1). The same child process segments and then detects, so all text passes one server path. The reply gets new fields:
   - `detector_version` (string; changes whenever rules or tables change);
   - `entities`: `[{ "id": "e1", "class": "ORG", "precision": "high" | "normal", "spans": [[block, start, end], …] }]` — one entity per distinct value in the document (case forms, initials and transliterations of the same name grouped by the detector); spans point into the returned cleaned blocks; **no value strings** in the reply (the browser reads them from the spans);
   - `requisites`: `[{ "clause": "c41", "lines": [{ "span": [block, start, end], "action": "drop" | "keep" }] }]`; a kept line adds the clause warning `requisites_condition`;
   - `neutralized`: spans of placeholder look-alikes in the source (`[ORG_2]`, `[A.PERSON_1]`), each also a clause warning `placeholder_lookalike`;
   - clause warnings `masked_next_to_amount`.
   Caps: at most 5,000 entities and 50,000 spans per file; above → `422 too_many_identifiers` (fail closed).
2. **Detector** (`app/pseudo/`): pure functions, linear-time patterns, tables checked into the repository (legal forms, context keywords, role words, obligation markers, requisites labels, UK/RU name-ending rules); checksum validators for ЄДРПОУ, РНОКПП, IBAN (ISO 13616) and cards (Luhn); matching on a de-hyphenated, NFKC + confusable-skeleton view with an offset map back to the cleaned text (ADR 0009: NFKC only for matching). No ML, no new runtime dependency; the confusable table (UTS #39 subset for Latin/Cyrillic/Greek/digits) is generated and checked in like the Layer 1 table.
3. **Browser preview** (`frontend/src/pseudo/`): the client sees every entity and requisites decision; can mask more text (select a range → choose a class) and unmask `normal` entities; `high` entities cannot be unmasked. Placeholders are assigned in the browser in first-occurrence order per document and class: `[A.ORG_1]`. The browser builds the masked clauses and the mapping; both live only in memory (ADR 0013 point 9a), are dropped with the contract, and the mapping is never in any request.
4. **Safety check endpoint** `POST /api/safety-check` (stateless): input `UntrustedMaskedDocument` = `{ "label": "A", "detector_version": "…", "clauses": [{ "id": "c1", "text": "…masked…" }] }`. Runs in the sandbox like `/api/segment` (same slot, limits and body rules). Checks in order: version (`409 detector_version_mismatch`), Layer 1 idempotence (`422 input_not_clean`), placeholder syntax (only `[<label>.<CLASS>_<n>]` for this document's label), high-precision rules on the masked text → `422 unmasked_identifier` with `{ "spans": [[clause_id, start, end], …] }` (offsets only, never values). Success → `200 { "ok": true, "detector_version": "…", "digest": "<sha256 of the canonical masked document>" }`. Stage 9's analysis endpoint runs the same `safety_pass()` again on its own input; the digest is informational only (not a token).
5. **Type gate** (`app/pseudo/gate.py`): `PseudonymizedDocument`, `PseudonymizedClause`, `PseudonymizedText`, `ConfirmedTopic` — frozen dataclasses with slots and a module-private sentinel; only `safety_pass()` (and, for topics, `confirm_topic()` in stage 7) create them. An AST policy test enforces ADR 0008 point 3 from now on, even before the AI layer exists.
6. **Canary harness** (`backend/tests/canary/`): a reusable fixture that plants canary identifiers of every class and location, runs the whole pipeline (extract → segment/detect → browser-equivalent masking in Python → safety check) and asserts no canary in the masked document, logs, error bodies or responses other than `/api/segment` (which must return the original text to the browser). Stage 6 plugs the `AIProvider` wire capture into the same harness. Matching: case-insensitive, NFKC, confusable skeleton, separators removed.
7. **Detector eval** (`backend/eval/pseudo/`): recall and precision per class and language on the S5b-T0 corpus. Gates for merge: recall 1.0 for high-precision classes with context; overall recall ≥ 0.95 and precision ≥ 0.85 per language on the corpus. The numbers are recorded in the PR; a drop fails CI.

## Consequences

- Positive: one server path for text; the browser never sends the mapping; stage 6/9 reuse the gate, safety pass and canary harness.
- Negative: `/api/segment` replies grow (entities and spans). The 4 MiB result cap still applies; the size test at the caps is extended.
- Residual risk (ADR 0008): detection is never complete; the mandatory preview is the final control.
