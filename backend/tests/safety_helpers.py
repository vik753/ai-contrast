# ruff: noqa: RUF007
"""Helpers for the S5b-T2 tests (``POST /api/safety-check``, ``app.pseudo.gate``).

Assumed interfaces (from TASKS.md S5b-T2 and ADR 0015 points 4 and 5):

- ``POST /api/safety-check`` takes JSON ``{"label", "detector_version", "clauses":
  [{"id", "text"}], "acknowledged_unmasked": [[clause_id, start, end], ...]}``.
- ``app.pseudo.gate``: ``PseudonymizedDocument`` (attribute ``clauses``: tuple of
  ``PseudonymizedClause`` with ``id`` and ``text``), ``PseudonymizedText``,
  ``ConfirmedTopic``, ``safety_pass(untrusted)``, ``SafetyError`` (``code``, ``spans``).
- ``UntrustedMaskedDocument`` is a Pydantic model in ``app.pseudo`` (any module) or
  ``app.api``; this file finds it by name.

Fixture people, companies and numbers are synthetic.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import Sequence
from typing import Any

from fastapi.testclient import TestClient

from tests.pseudo_helpers import detect_blocks
from tests.segment_helpers import FIXTURE_DIR, block, post_blocks

SAFETY = "/api/safety-check"
JSON_HEADERS = {"Content-Type": "application/json"}
PSEUDO_FIXTURES = FIXTURE_DIR.parent / "pseudo"
Doc = dict[str, Any]

CANDIDATE_MODULES = (
    "app.pseudo.gate",
    "app.pseudo.untrusted",
    "app.pseudo.models",
    "app.pseudo.safety",
    "app.pseudo",
    "app.api.safety_check",
    "app.api.safety",
)


def find_untrusted_model() -> Any:
    for name in CANDIDATE_MODULES:
        try:
            module = importlib.import_module(name)
        except ImportError:
            continue
        if hasattr(module, "UntrustedMaskedDocument"):
            return module.UntrustedMaskedDocument
    msg = "UntrustedMaskedDocument not found in app.pseudo.* or app.api.*"
    raise AssertionError(msg)


def detector_version(client: TestClient) -> str:
    data = detect_blocks(client, [block("1. Payment is due within 30 days.")])
    version: str = data["detector_version"]
    return version


def doc(
    version: str,
    *texts: str,
    label: str = "A",
    ack: Sequence[Sequence[Any]] = (),
) -> Doc:
    return {
        "label": label,
        "detector_version": version,
        "clauses": [{"id": f"c{i + 1}", "text": t} for i, t in enumerate(texts)],
        "acknowledged_unmasked": [list(a) for a in ack],
    }


def post_doc(client: TestClient, payload: Doc) -> Any:
    return client.post(
        SAFETY, content=json.dumps(payload, ensure_ascii=False).encode(), headers=JSON_HEADERS
    )


def hit_spans(client: TestClient, text: str) -> list[tuple[int, int, str, str]]:
    """Detector hits in one body block, as ``(start, end, class, precision)``.

    The safety check re-runs the same detector, so these are the spans it
    must report (clause text = block text for a one-block clause).
    """
    data = detect_blocks(client, [block(text)])
    assert data["blocks"][0]["text"] == text, "test text must be clean and un-neutralized"
    found = [
        (sp[1], sp[2], e["class"], e["precision"])
        for e in data["entities"]
        for sp in e["spans"]
        if sp[0] == 0
    ]
    return sorted(found)


# ------------------------------------------------------- masking from a corpus file


def eligible_fixture_names() -> list[str]:
    """Corpus files that can be masked mechanically: no overlapping spans, no
    requisites decisions, no neutralized spans, no invisible-character variants."""
    names: list[str] = []
    for path in sorted(PSEUDO_FIXTURES.glob("[0-9][0-9]_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        expected = data["expected"]
        if not expected["entities"] or expected["requisites"] or expected["neutralized"]:
            continue
        if path.name.startswith(("34_", "35_")):
            continue
        spans = sorted(tuple(s) for e in expected["entities"] for s in e["spans"])
        if any(a[0] == b[0] and b[1] < a[2] for a, b in zip(spans, spans[1:], strict=False)):
            continue
        names.append(path.name)
    return names


def build_masked(
    client: TestClient, name: str, label: str = "A"
) -> tuple[Doc, list[tuple[str, str]]]:
    """Mask every expected entity of a corpus file with a correct placeholder.

    Placeholders are numbered per class in first-occurrence order, like the
    browser does. Returns the request body and ``(original, placeholder)`` pairs.
    """
    data = json.loads((PSEUDO_FIXTURES / name).read_text(encoding="utf-8"))
    response = post_blocks(client, data["blocks"])
    assert response.status_code == 200
    seg = response.json()
    blocks = [b["text"] for b in seg["blocks"]]
    entities = sorted(data["expected"]["entities"], key=lambda e: min(tuple(s) for s in e["spans"]))
    counters: dict[str, int] = {}
    replace: dict[tuple[int, int, int], str] = {}
    pairs: list[tuple[str, str]] = []
    for entity in entities:
        counters[entity["class"]] = counters.get(entity["class"], 0) + 1
        placeholder = f"[{label}.{entity['class']}_{counters[entity['class']]}]"
        for i, s, e in entity["spans"]:
            replace[(i, s, e)] = placeholder
            pairs.append((blocks[i][s:e], placeholder))
    used: set[tuple[int, int, int]] = set()
    texts: list[str] = []
    for clause in seg["clauses"]:
        pieces: list[str] = []
        for i, s, e in clause["spans"]:
            piece, pos = "", s
            for (ri, rs, re_), placeholder in sorted(replace.items()):
                if ri == i and s <= rs and re_ <= e:
                    piece += blocks[i][pos:rs] + placeholder
                    pos = re_
                    used.add((ri, rs, re_))
            pieces.append(piece + blocks[i][pos:e])
        texts.append("\n".join(pieces))
    assert used == set(replace), "an expected entity is outside every clause span"
    return doc(seg["detector_version"], *texts, label=label), pairs
