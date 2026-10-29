"""Detector eval (S5b-T4 AC 2, ADR 0015 point 7).

Runs the detector through the same path as ``POST /api/segment`` (the sandbox child's
``run``: strict request validation, cleaning, segmentation, detection), in-process, on
the main corpus (``tests/fixtures/pseudo/``) and on the held-out split
(``eval/pseudo/heldout/``). Both use the format of ``tests/fixtures/pseudo/README.md``.

Metrics, per split:

- **Recall** per language x class x precision tier (``high`` / ``normal``), counted per
  expected span (one mention). A span is found only if every code point of it is covered
  by detected spans of the same class in the same block: a partially masked value is a
  miss.
- **Precision** per language (and per class, for information): a detected span is
  correct if it overlaps an expected span of the same class or of an allowed overlap
  class (ORG/PERSON for ФОП and ИП, SIGNATURE/PERSON for signature lines).
- **Requisites decision accuracy**: correct drop/keep decisions / (expected records +
  detected lines without a record).
- **must_not_mask violations**: occurrences of a ``must_not_mask`` string that overlap
  any detected span. Must be 0.
- **Tier agreement** (information only): found mentions whose covering detection has
  the expected precision tier.

The language of a file is its ``language`` field (mixed files count for their main
language). Gates (ADR 0015 point 7): recall 1.0 for every ``high`` group, recall >= 0.95
for every ``normal`` group, precision >= 0.85 per language, 0 ``must_not_mask``
violations.

The held-out report prints aggregate numbers only: never values, spans or file names
(TASKS S5b-T4 AC 2). ``--details`` lists the misses of the main corpus only.

Usage (from ``backend/``)::

    uv run --locked python -m eval.pseudo.run_eval [--split main|heldout|all]
        [--details] [--write-baseline]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from app.extraction.model import DEFAULT_MAX_BLOCKS, DEFAULT_MAX_PDF_PAGES, DEFAULT_MAX_TEXT_CHARS
from app.segment import child
from app.settings import Settings

BACKEND: Final = Path(__file__).resolve().parents[2]
SPLITS: Final = {
    "main": BACKEND / "tests" / "fixtures" / "pseudo",
    "heldout": BACKEND / "eval" / "pseudo" / "heldout",
}
BASELINE_PATH: Final = Path(__file__).resolve().parent / "baseline.json"

GATE_RECALL_HIGH: Final = 1.0
GATE_RECALL_NORMAL: Final = 0.95
GATE_PRECISION: Final = 0.85
BASELINE_TOLERANCE: Final = 0.01

# Pairs of classes whose spans overlap by corpus convention (README decisions 3 and 4,
# held-out decision 2).
ALLOWED_OVERLAPS: Final = frozenset(
    {("ORG", "PERSON"), ("PERSON", "ORG"), ("SIGNATURE", "PERSON"), ("PERSON", "SIGNATURE")}
)

Span = tuple[int, int, int]


class CorpusError(Exception):
    """A fixture is inconsistent (span text not in ``value_forms``) or was rejected.

    The message holds a reason code only (no file name, value or span): it may come from
    the held-out split.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(f"corpus error: {reason}")


@dataclass
class Ratio:
    total: int = 0
    hits: int = 0

    def add(self, hit: bool) -> None:
        self.total += 1
        self.hits += int(hit)

    @property
    def value(self) -> float:
        return self.hits / self.total if self.total else 1.0


@dataclass
class Miss:
    """One missed mention or false detection; only printed for the main corpus."""

    file: str
    kind: str
    cls: str
    text: str


@dataclass
class SplitResult:
    files: int = 0
    seconds: float = 0.0
    recall: dict[tuple[str, str, str], Ratio] = field(default_factory=lambda: defaultdict(Ratio))
    precision: dict[str, Ratio] = field(default_factory=lambda: defaultdict(Ratio))
    precision_by_class: dict[tuple[str, str], Ratio] = field(
        default_factory=lambda: defaultdict(Ratio)
    )
    requisites: Ratio = field(default_factory=Ratio)
    tier_agreement: Ratio = field(default_factory=Ratio)
    must_not_mask_violations: int = 0
    misses: list[Miss] = field(default_factory=list)


def corpus_paths(split: str) -> list[Path]:
    directory = SPLITS[split]
    pattern = "[0-9][0-9]_*.json" if split == "main" else "h[0-9][0-9]_*.json"
    return sorted(directory.glob(pattern))


def run_detector(blocks: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """The ``/api/segment`` child path in-process, with the default server caps."""
    settings = Settings()
    request = json.dumps({"blocks": list(blocks)}, ensure_ascii=False).encode()
    reply = json.loads(
        child.run(
            request,
            max_text_chars=DEFAULT_MAX_TEXT_CHARS,
            max_blocks=DEFAULT_MAX_BLOCKS,
            max_pages=DEFAULT_MAX_PDF_PAGES,
            max_clauses=settings.segment_max_clauses,
            max_clause_chars=settings.segment_max_clause_chars,
        )
    )
    if "result" not in reply:
        raise CorpusError(str(reply.get("error")))
    result: dict[str, Any] = reply["result"]
    return result


def _covered(span: Span, detected: Iterable[Span]) -> bool:
    block, start, end = span
    cover = bytearray(end - start)
    for b, s, e in detected:
        if b != block or e <= start or s >= end:
            continue
        for i in range(max(s, start), min(e, end)):
            cover[i - start] = 1
    return all(cover)


def _overlaps(a: Span, b: Span) -> bool:
    return a[0] == b[0] and a[1] < b[2] and b[1] < a[2]


def _evaluate_file(fixture: dict[str, Any], name: str, out: SplitResult) -> None:
    lang: str = fixture["language"]
    expected = fixture["expected"]
    data = run_detector(fixture["blocks"])
    texts = [b["text"] for b in data["blocks"]]

    want: list[tuple[str, str, Span]] = []
    for entity in expected["entities"]:
        for b, s, e in entity["spans"]:
            if texts[b][s:e] not in entity["value_forms"]:
                raise CorpusError("span_not_a_value_form")
            want.append((entity["class"], entity["precision"], (b, s, e)))
    got: list[tuple[str, str, Span]] = [
        (entity["class"], entity["precision"], (sp[0], sp[1], sp[2]))
        for entity in data.get("entities", [])
        for sp in entity["spans"]
    ]

    for cls, tier, span in want:
        same = [g for g in got if g[0] == cls]
        found = _covered(span, (g[2] for g in same))
        out.recall[lang, cls, tier].add(found)
        if found:
            covering = [g for g in same if _overlaps(g[2], span)]
            out.tier_agreement.add(all(g[1] == tier for g in covering))
        else:
            out.misses.append(Miss(name, "missed", cls, texts[span[0]][span[1] : span[2]]))

    for cls, _tier, span in got:
        correct = any(
            _overlaps(span, w[2]) and (w[0] == cls or (cls, w[0]) in ALLOWED_OVERLAPS) for w in want
        )
        out.precision[lang].add(correct)
        out.precision_by_class[lang, cls].add(correct)
        if not correct:
            out.misses.append(Miss(name, "false", cls, texts[span[0]][span[1] : span[2]]))

    _evaluate_requisites(expected.get("requisites", []), data, texts, name, out)

    spans = [g[2] for g in got]
    for value in expected.get("must_not_mask", []):
        for b, text in enumerate(texts):
            start = text.find(value)
            while start != -1:
                if any(_overlaps((b, start, start + len(value)), sp) for sp in spans):
                    out.must_not_mask_violations += 1
                    out.misses.append(Miss(name, "must_not_mask", "-", value))
                start = text.find(value, start + 1)


def _evaluate_requisites(
    records: list[dict[str, Any]],
    data: dict[str, Any],
    texts: list[str],
    name: str,
    out: SplitResult,
) -> None:
    lines = [
        (
            line["span"][0],
            texts[line["span"][0]][line["span"][1] : line["span"][2]].strip(),
            line["action"],
        )
        for item in data.get("requisites", [])
        for line in item["lines"]
    ]
    used: set[int] = set()
    for record in records:
        matches = [
            i
            for i, (b, text, _action) in enumerate(lines)
            if b == record["block"] and text.startswith(record["line_text_starts_with"])
        ]
        ok = len(matches) == 1 and lines[matches[0]][2] == record["action"]
        used.update(matches)
        out.requisites.add(ok)
        if not ok:
            got = lines[matches[0]][2] if len(matches) == 1 else "none"
            out.misses.append(
                Miss(
                    name,
                    f"requisites {record['action']}->{got}",
                    "-",
                    record["line_text_starts_with"],
                )
            )
    for i, (_b, text, action) in enumerate(lines):
        if i not in used:
            out.requisites.add(False)
            out.misses.append(Miss(name, f"requisites unexpected {action}", "-", text))


def evaluate(paths: Sequence[Path], *, keep_misses: bool = False) -> SplitResult:
    """Score the files. Misses (values) are kept only on request (main corpus details)."""
    out = SplitResult(files=len(paths))
    began = time.perf_counter()
    for path in paths:
        fixture: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        _evaluate_file(fixture, path.stem, out)
    out.seconds = time.perf_counter() - began
    if not keep_misses:
        out.misses.clear()
    return out


# ---------------------------------------------------------------- metrics and gates


def metrics(result: SplitResult) -> dict[str, float]:
    """Flat metric map: the baseline and the regression check use these names."""
    flat: dict[str, float] = {}
    for (lang, cls, tier), ratio in sorted(result.recall.items()):
        flat[f"recall:{lang}:{cls}:{tier}"] = round(ratio.value, 4)
    for lang, ratio in sorted(result.precision.items()):
        flat[f"precision:{lang}"] = round(ratio.value, 4)
    flat["requisites_accuracy"] = round(result.requisites.value, 4)
    flat["must_not_mask_violations"] = float(result.must_not_mask_violations)
    return flat


@dataclass(frozen=True)
class Gate:
    id: str
    value: float
    threshold: float
    passed: bool


def gates(result: SplitResult) -> list[Gate]:
    out: list[Gate] = []
    for (lang, cls, tier), ratio in sorted(result.recall.items()):
        limit = GATE_RECALL_HIGH if tier == "high" else GATE_RECALL_NORMAL
        out.append(Gate(f"recall:{lang}:{cls}:{tier}", ratio.value, limit, ratio.value >= limit))
    for lang, ratio in sorted(result.precision.items()):
        out.append(
            Gate(f"precision:{lang}", ratio.value, GATE_PRECISION, ratio.value >= GATE_PRECISION)
        )
    count = float(result.must_not_mask_violations)
    out.append(Gate("must_not_mask_violations", count, 0.0, count == 0))
    return out


def regressions(current: dict[str, float], baseline: dict[str, float]) -> list[str]:
    """Metric names that dropped more than the tolerance below the baseline (or vanished)."""
    found: list[str] = []
    for name, base in baseline.items():
        if name not in current:
            found.append(f"{name}: missing (baseline {base})")
        elif name == "must_not_mask_violations":
            if current[name] > base:
                found.append(f"{name}: {current[name]:g} > baseline {base:g}")
        elif current[name] < base - BASELINE_TOLERANCE:
            found.append(f"{name}: {current[name]:.4f} < baseline {base:.4f}")
    found.extend(f"{name}: not in baseline" for name in current if name not in baseline)
    return found


# ---------------------------------------------------------------- report


def _table(result: SplitResult) -> list[str]:
    rows = ["| Language | Class | Tier | Found / expected | Recall | Gate |", "| --- " * 6 + "|"]
    for (lang, cls, tier), ratio in sorted(result.recall.items()):
        limit = GATE_RECALL_HIGH if tier == "high" else GATE_RECALL_NORMAL
        mark = "pass" if ratio.value >= limit else "FAIL"
        rows.append(
            f"| {lang} | {cls} | {tier} | {ratio.hits}/{ratio.total} | {ratio.value:.3f} | {mark} |"
        )
    rows += ["", "| Language | Correct / detected | Precision | Gate |", "| --- " * 4 + "|"]
    for lang, ratio in sorted(result.precision.items()):
        mark = "pass" if ratio.value >= GATE_PRECISION else "FAIL"
        rows.append(f"| {lang} | {ratio.hits}/{ratio.total} | {ratio.value:.3f} | {mark} |")
    rows += ["", "| Language | Class | Correct / detected | Precision |", "| --- " * 4 + "|"]
    for (lang, cls), ratio in sorted(result.precision_by_class.items()):
        rows.append(f"| {lang} | {cls} | {ratio.hits}/{ratio.total} | {ratio.value:.3f} |")
    req, agree = result.requisites, result.tier_agreement
    rows += [
        "",
        f"Requisites decisions: {req.hits}/{req.total} = {req.value:.3f}",
        f"Tier agreement (info): {agree.hits}/{agree.total} = {agree.value:.3f}",
        f"must_not_mask violations: {result.must_not_mask_violations}",
        f"Files: {result.files}; runtime: {result.seconds:.2f} s",
    ]
    return rows


def report(split: str, result: SplitResult, *, details: bool) -> str:
    lines = [f"## Split: {split}", "", *_table(result)]
    failed = [g for g in gates(result) if not g.passed]
    lines += ["", f"Gates failed: {len(failed)}"]
    lines += [f"- {g.id}: {g.value:.3f} (gate {g.threshold:g})" for g in failed]
    if details and split == "main":
        lines += ["", "Misses (main corpus only):"]
        lines += [f"- {m.file}: {m.kind} {m.cls} {m.text!r}" for m in result.misses]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--split", choices=["main", "heldout", "all"], default="all")
    parser.add_argument("--details", action="store_true", help="list main-corpus misses")
    parser.add_argument("--write-baseline", action="store_true")
    args = parser.parse_args(argv)
    names = ["main", "heldout"] if args.split == "all" else [args.split]
    results = {
        name: evaluate(corpus_paths(name), keep_misses=args.details and name == "main")
        for name in names
    }
    for name, result in results.items():
        sys.stdout.write(report(name, result, details=args.details) + "\n")
    if args.write_baseline:
        if args.split != "all":
            parser.error("--write-baseline needs --split all")
        baseline = {name: metrics(result) for name, result in results.items()}
        BASELINE_PATH.write_text(
            json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return 1 if any(not g.passed for r in results.values() for g in gates(r)) else 0


if __name__ == "__main__":
    raise SystemExit(main())
