"""S5b-T4 AC 1: the Python masking reference agrees with the shared vectors.

``shared/pseudo-vectors.json`` also runs through ``frontend/src/pseudo/masking.ts``
(``masking.vectors.test.ts``). Both suites must pass; together they prove the Python
reference used by the canary harness is browser-equivalent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.canary.masking_ref import mask_segmentation

VECTORS_FILE = Path(__file__).resolve().parents[3] / "shared" / "pseudo-vectors.json"
CASES: list[dict[str, Any]] = json.loads(VECTORS_FILE.read_text(encoding="utf-8"))["cases"]


def _run(case: dict[str, Any]) -> Any:
    seg = {
        "blocks": [{"text": t, "part": "body", "page": None} for t in case["blocks"]],
        "clauses": case["clauses"],
        "entities": case["entities"],
        "requisites": case["requisites"],
        "neutralized": case["neutralized"],
    }
    return mask_segmentation(
        seg,
        case["label"],
        unmask=case["unmask"]["entities"],
        unmask_occurrences=[(e, i) for e, i in case["unmask"]["occurrences"]],
    )


def test_vectors_file_has_cases() -> None:
    assert len(CASES) >= 15
    assert len({c["name"] for c in CASES}) == len(CASES)


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_vector_masked_clauses_match(case: dict[str, Any]) -> None:
    assert _run(case).clauses == case["expected"]["masked"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_vector_acknowledged_spans_match(case: dict[str, Any]) -> None:
    assert _run(case).acknowledged == case["expected"]["acknowledged"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_vector_mapping_never_in_masked_text_except_unmasked(case: dict[str, Any]) -> None:
    """Every mapped original is gone from the masked text unless the same text is also
    left unmasked on purpose (acknowledged)."""
    result = _run(case)
    joined = "\n".join(c["text"] for c in result.clauses)
    if case["unmask"]["entities"] or case["unmask"]["occurrences"]:
        return
    for placeholder, original in result.mapping.items():
        assert placeholder in joined
        assert original not in joined
