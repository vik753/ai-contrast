# ruff: noqa: PLR0912
"""Helpers for the S5-T1 segmentation tests (no fixtures, no assertions about
the implementation): fixture loading, request building and the cover checker.

Everything goes through the public interface: ``POST /api/segment``.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

SEGMENT = "/api/segment"
JSON_HEADERS = {"Content-Type": "application/json"}
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "segment"
MIB = 1024 * 1024

Block = dict[str, Any]
Clause = dict[str, Any]


def fixture_paths() -> list[Path]:
    return sorted(FIXTURE_DIR.glob("[0-9][0-9]_*.json"))


def load_fixture(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def block(text: str, part: str = "body", page: int | None = None) -> Block:
    return {"text": text, "part": part, "page": page}


def body_bytes(blocks: Sequence[Block]) -> bytes:
    """Compact UTF-8 JSON (Cyrillic not escaped, so 1 M characters stay near 2 MB)."""
    return json.dumps({"blocks": list(blocks)}, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def post_blocks(client: TestClient, blocks: Sequence[Block]) -> Any:
    return client.post(SEGMENT, content=body_bytes(blocks), headers=JSON_HEADERS)


def post_raw(client: TestClient, raw: bytes) -> Any:
    return client.post(SEGMENT, content=raw, headers=JSON_HEADERS)


def clause_text(clause: Clause, blocks: Sequence[Block]) -> str:
    """Rebuild the clause text from its spans (no ``text`` field in the reply)."""
    return "\n".join(blocks[i]["text"][s:e] for i, s, e in clause["spans"])


def heading_text(clause: Clause, blocks: Sequence[Block]) -> str | None:
    span = clause["heading_span"]
    if span is None:
        return None
    i, s, e = span
    text: str = blocks[i]["text"][s:e]
    return text.strip()


# Warnings of the detector (S5b-T1, ADR 0015 point 1); the segmentation tests ignore them.
DETECTOR_WARNINGS = frozenset(
    {"requisites_condition", "placeholder_lookalike", "masked_next_to_amount"}
)


def warning_codes(data: dict[str, Any], include_detector: bool = False) -> list[str]:
    """Sorted warning codes; the detector's own codes only on request."""
    return sorted(
        w["code"]
        for w in data["warnings"]
        if include_detector or w["code"] not in DETECTOR_WARNINGS
    )


def cover_problems(data: dict[str, Any]) -> list[str]:
    """Every non-white-space character of the returned (cleaned) blocks is
    covered by exactly one span; spans are in range, ascending inside a clause,
    and clauses are in document order of their first span. Empty list = ok."""
    blocks = data["blocks"]
    clauses = data["clauses"]
    problems: list[str] = []
    covered: Counter[tuple[int, int]] = Counter()
    previous_first: tuple[int, int] | None = None
    for position, clause in enumerate(clauses):
        if clause["id"] != f"c{position + 1}":
            problems.append(f"id {clause['id']!r} at position {position}")
        spans = clause["spans"]
        if not spans:
            problems.append(f"{clause['id']}: no spans")
            continue
        last: tuple[int, int] | None = None
        for i, s, e in spans:
            if not (0 <= i < len(blocks)) or not (0 <= s < e <= len(blocks[i]["text"])):
                problems.append(f"{clause['id']}: bad span {[i, s, e]}")
                continue
            if last is not None and (i, s) < last:
                problems.append(f"{clause['id']}: spans not ascending")
            last = (i, e)
            for k in range(s, e):
                covered[(i, k)] += 1
        first = (spans[0][0], spans[0][1])
        if previous_first is not None and first < previous_first:
            problems.append(f"{clause['id']}: clauses not in document order")
        previous_first = first
    for i, b in enumerate(blocks):
        for k, ch in enumerate(b["text"]):
            n = covered[(i, k)]
            if not ch.isspace() and n != 1:
                problems.append(f"block {i} char {k}: covered {n} times")
                if len(problems) > 20:
                    return problems
            elif ch.isspace() and n > 1:
                problems.append(f"block {i} char {k} (space): covered {n} times")
    return problems


def contract_problems(data: dict[str, Any]) -> list[str]:
    """Shape of the 200 reply (AC2)."""
    problems: list[str] = []
    # S5b-T1 (ADR 0015 point 1) adds the detector fields to the S5 reply.
    expected = {
        "clauses", "blocks", "removed", "warnings",
        "detector_version", "entities", "requisites", "neutralized",
    }  # fmt: skip
    if set(data) != expected:
        problems.append(f"top-level keys {sorted(data)}")
    clause_keys = {
        "id",
        "number",
        "level",
        "part_index",
        "section_kind",
        "part",
        "pages",
        "spans",
        "heading_span",
    }
    parts = {"body", "footnote", "endnote", "header", "footer", "textbox", "running", "preamble"}
    ids = {c["id"] for c in data["clauses"]}
    for c in data["clauses"]:
        if set(c) != clause_keys:
            problems.append(f"{c.get('id')}: keys {sorted(c)}")
            continue
        if c["part"] not in parts:
            problems.append(f"{c['id']}: part {c['part']!r}")
        if c["section_kind"] not in (None, "requisites"):
            problems.append(f"{c['id']}: section_kind {c['section_kind']!r}")
        if not (c["number"] is None or isinstance(c["number"], str)):
            problems.append(f"{c['id']}: number type")
        if not (isinstance(c["level"], int) and c["level"] >= 0):
            problems.append(f"{c['id']}: level")
        if not (isinstance(c["part_index"], int) and c["part_index"] >= 0):
            problems.append(f"{c['id']}: part_index")
        if c["part"] in ("preamble", "running") and c["level"] != 0:
            problems.append(f"{c['id']}: {c['part']} level {c['level']}")
        if not all(isinstance(p, int) for p in c["pages"]):
            problems.append(f"{c['id']}: pages")
        if c["heading_span"] is not None and len(c["heading_span"]) != 3:
            problems.append(f"{c['id']}: heading_span")
    for w in data["warnings"]:
        if set(w) != {"code", "clause"} or (w["clause"] is not None and w["clause"] not in ids):
            problems.append(f"warning {w}")
    for r in data["removed"]:
        if set(r) != {"reason", "count", "sample"}:
            problems.append(f"removed {r}")
    for b in data["blocks"]:
        if set(b) != {"text", "part", "page"}:
            problems.append(f"block keys {sorted(b)}")
            break
    return problems
