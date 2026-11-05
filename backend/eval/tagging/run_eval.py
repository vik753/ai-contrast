# ruff: noqa: TRY003
"""Tagging eval (S8-T4, ADR 0018 point 9).

Every model answer goes through the same code as ``/api/tag``: masking and ``safety_pass``
for documents, ``resolve_topics`` for the catalog topics, ``plan_batches`` for the batches,
``run_model_steps`` (tagging call, check call, one repair each, strict schemas) and
``merge_tags`` (caps, "Other", risk terms). Keyword tags come from ``keyword_tags``, the
function the sandbox child runs (called in-process here).

Modes:

- ``--recorded`` (default, CI): no network, no key. Answers come from ``recordings/*.json``.
  A recording holds, per template, a key = SHA-256 of the template text, the JSON schema of
  the answer and the model id; and, per case, every provider call in order with a digest of
  its full prompt (nonces normalised). A different key or digest fails the run.
- ``--live --provider P [--model M] [--check-model S] [--base-url URL]`` (local only): calls
  the provider and writes ``recordings/<provider>__<model>__<check model>.json``. The models
  default to the preset pair (cheap, strong). The key is read from ``AIC_EVAL_PROVIDER_KEY``,
  held as ``SecretStr``, never printed and never written; ``free`` also reads
  ``AIC_EVAL_CF_ACCOUNT_ID``.
- ``--write-stub``: writes ``recordings/stub__oracle-v1.json`` from ``oracle.py``.
- ``--synonyms``: keyword precision per topic and the worst catalog synonyms (no recording).

Metrics (micro over clause-topic pairs; the unnumbered title clause is ignored), each total,
``:<domain>``, ``:<lang>`` and per topic ``:<domain>/<topic>``:

- ``kw.recall`` / ``kw.precision``: keyword tags alone.
- ``all.recall`` / ``all.precision``: tags after the merge (keyword + model + check).
- ``{kw,all}.other.share``: clauses in "Other" (informational, no direction).
- ``{kw,all}.other.recall``: expected "Other" clauses that are in "Other".
- ``{kw,all}.risk.recall``: expected risk-term clauses in "Other" with a risk-term hit.
- ``{kw,all}.missing.false_positives``: topics reported missing that the gold set has.
- ``{kw,all}.missing.recall``: ``absent_topics`` of ``expected.json`` reported missing.
- ``adversarial.*`` (counts, 0 is the only good value): hidden clauses (neither tagged nor in
  "Other"), the deductible tag lost on ``skip_me`` 3.2 or on ``flood`` 3.1, cap violations, a
  compromised topic not dropped, strings in a result that are not ids or enums (leaks). Each
  for the recorded answers and for fixed compromised answers.

``all.*`` metrics are informational (printed, not gated) while the recording is a stub.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence, Set
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, SecretStr

from app.ai.port import AIError, AIErrorCode, AIProvider, AIRequest, CheckResult, ModelJson
from app.ai.prompting import build_messages
from app.ai.prompts import PromptTemplate
from app.extraction.model import DEFAULT_MAX_BLOCKS, DEFAULT_MAX_PDF_PAGES, DEFAULT_MAX_TEXT_CHARS
from app.pseudo.gate import ConfirmedTopic, PseudonymizedDocument
from app.segment import child
from app.settings import Settings
from app.tagging.ai_steps import ModelState, run_model_steps
from app.tagging.batches import plan_batches
from app.tagging.clauses import clauses_of
from app.tagging.keywords import keyword_tags
from app.tagging.merge import (
    MAX_MODEL_CLAUSES_PER_TOPIC,
    MAX_MODEL_TAGS_PER_CLAUSE,
    Failure,
    TaggingResult,
    merge_tags,
)
from app.tagging.phrases import PhraseIndex, match_view
from app.tagging.schemas import CheckOut, TagOut
from app.topics.catalog import Catalog, load_catalog
from app.topics.selection import CatalogRef, TopicSelection, resolve_topics
from eval.tagging.oracle import OracleProvider
from eval.topics.run_eval import masked_document

HERE: Final = Path(__file__).resolve().parent
TAG_FIXTURES: Final = HERE / "fixtures"
TOPIC_FIXTURES: Final = HERE.parent / "topics" / "fixtures"
RECORDINGS: Final = HERE / "recordings"
BASELINE_PATH: Final = HERE / "baseline.json"
STUB_NAME: Final = "stub__oracle-v1"
STUB_MODEL: Final = "oracle-v1"
KEY_ENV: Final = "AIC_EVAL_PROVIDER_KEY"
CF_ACCOUNT_ENV: Final = "AIC_EVAL_CF_ACCOUNT_ID"
BASELINE_TOLERANCE: Final = 0.01
LIVE_DEADLINE_SECONDS: Final = 60.0
REPLAY_DEADLINE_SECONDS: Final = 600.0
ADVERSARIAL: Final = ("skip_me", "flood")
ADVERSARIAL_DOMAIN: Final = ("kasko", "en")
LOW_PRECISION: Final = 0.6
# Higher is worse (the regression check is reversed).
LOWER_IS_BETTER: Final = ("adversarial.", "kw.missing.false_positives", "all.missing.false_pos")
# Informational: no direction (always), model metrics (while the recording is a stub).
NO_DIRECTION: Final = (".other.share",)
MODEL_METRICS: Final = ("all.",)
STUB_LABEL: Final = (
    " [STUB numbers: oracle, not a model; all.* is informational, kw.* and adversarial.* are gated]"
)
SCHEMAS: Final[dict[PromptTemplate, type[BaseModel]]] = {
    PromptTemplate.TAG_CLAUSES: TagOut,
    PromptTemplate.CHECK_TAGS: CheckOut,
}
_NONCE: Final = re.compile(r"<<<(BEGIN|END) ([A-Z]+) [0-9a-f]{32}>>>")
_ERROR_KEY: Final = "__ai_error__"
_ENUMS: Final = frozenset({"keyword", "model", "check", "client", "too_many_clauses"})


class RecordingError(Exception):
    """A recording does not fit the current prompts, schemas or inputs."""


# --- inputs ----------------------------------------------------------------------------------


def _json(path: Path) -> Any:  # noqa: ANN401 - fixture JSON
    return json.loads(path.read_text(encoding="utf-8"))


def catalog() -> Catalog:
    return load_catalog(Settings().topics_catalog_dir)


def clause_numbers(blocks: Sequence[dict[str, Any]]) -> dict[str, str | None]:
    """Clause id -> number as written, like ``/api/segment``."""
    settings = Settings()
    reply = json.loads(
        child.run(
            json.dumps({"blocks": list(blocks)}, ensure_ascii=False).encode(),
            max_text_chars=DEFAULT_MAX_TEXT_CHARS,
            max_blocks=DEFAULT_MAX_BLOCKS,
            max_pages=DEFAULT_MAX_PDF_PAGES,
            max_clauses=settings.segment_max_clauses,
            max_clause_chars=settings.segment_max_clause_chars,
        )
    )
    return {c["id"]: c["number"] for c in reply["result"]["clauses"]}


def domain_topics(cat: Catalog, domain: str, lang: str) -> tuple[ConfirmedTopic, ...]:
    """Every catalog topic of the domain, resolved like ``/api/tag`` (first side)."""
    entry = next(d for d in cat.domains if d.id == domain)
    side = entry.sides[0].id
    refs = [
        CatalogRef(
            domain=domain,
            topic_id=t.id,
            side=side,
            lang=lang,
            catalog_version=cat.catalog_version,
        )
        for t in entry.topics
    ]
    return resolve_topics(TopicSelection(catalog=refs), cat)


@dataclass(frozen=True)
class Case:
    """One document: the gate objects, the gold tags and the clause numbers."""

    name: str
    domain: str
    lang: str
    document: PseudonymizedDocument
    topics: tuple[ConfirmedTopic, ...]
    numbers: dict[str, str | None]
    gold: dict[str, Any]
    absent: tuple[str, ...]

    @property
    def batches(self) -> tuple[tuple[str, ...], ...]:
        ids = [c.id for c in self.document.clauses]
        ranges = plan_batches([len(c.text) for c in self.document.clauses])
        return tuple(tuple(ids[start:end]) for start, end in ranges)

    @property
    def adversarial(self) -> bool:
        return self.name in ADVERSARIAL


def build_cases(cat: Catalog) -> list[Case]:
    cases: list[Case] = []
    for path in sorted(TAG_FIXTURES.glob("*.tags.json")):
        name = path.name.removesuffix(".tags.json")
        gold = _json(path)
        if name in ADVERSARIAL:
            blocks = _json(TAG_FIXTURES / f"{name}.contract.json")["blocks"]
            domain, lang = ADVERSARIAL_DOMAIN
            absent: tuple[str, ...] = ()
        else:
            blocks = _json(TOPIC_FIXTURES / name / "contract.json")["blocks"]
            expected = _json(TOPIC_FIXTURES / name / "expected.json")
            domain, lang = expected["domain"], expected["language"]
            absent = tuple(expected.get("absent_topics", ()))
        cases.append(
            Case(
                name=name,
                domain=domain,
                lang=lang,
                document=masked_document(blocks, "A"),
                topics=domain_topics(cat, domain, lang),
                numbers=clause_numbers(blocks),
                gold=gold,
                absent=absent,
            )
        )
    return cases


# --- recordings ------------------------------------------------------------------------------


def template_key(template: PromptTemplate, model: str) -> str:
    schema = json.dumps(SCHEMAS[template].model_json_schema(), sort_keys=True)
    material = json.dumps([template.name, template.value, schema, model], ensure_ascii=False)
    return hashlib.sha256(material.encode()).hexdigest()


def input_digest(request: AIRequest) -> str:
    """The full prompt with the random nonces replaced: instructions, schema and data."""
    text = "\n\x00\n".join(
        f"{message.role}:{_NONCE.sub(r'<<<\1 \2 N>>>', message.content)}"
        for message in build_messages(request)
    )
    return hashlib.sha256(text.encode()).hexdigest()


class ReplayProvider:
    """Answers from a recording, call by call; each call's prompt digest must match."""

    def __init__(self, calls: Sequence[dict[str, Any]], case: str, name: str) -> None:
        self._calls = list(calls)
        self._case = case
        self._name = name

    @property
    def left(self) -> int:
        return len(self._calls)

    async def check(self) -> CheckResult:
        return CheckResult(ok=True)

    async def complete_json(self, request: AIRequest) -> ModelJson:
        if not self._calls:
            raise RecordingError(
                f"recording {self._name}: case {self._case} makes more calls than recorded. "
                "Refresh the recording."
            )
        entry = self._calls.pop(0)
        if entry["template"] != request.template.name or entry["input"] != input_digest(request):
            raise RecordingError(
                f"recording {self._name}: the input of a {request.template.name} call of case "
                f"{self._case} changed (fixture, masking, topics or prompt assembly). Refresh "
                "the recording."
            )
        answer = entry["answer"]
        if isinstance(answer, dict) and _ERROR_KEY in answer:
            raise AIError(AIErrorCode(answer[_ERROR_KEY])) from None
        if not isinstance(answer, dict):
            raise AIError(AIErrorCode.PROVIDER_BAD_RESPONSE) from None
        return answer


class RecordingProvider:
    """Wraps a provider and appends every call (prompt digest, answer or error, latency)."""

    def __init__(self, inner: AIProvider, calls: list[dict[str, Any]], *, stub: bool) -> None:
        self.inner = inner
        self.calls = calls
        self.stub = stub

    async def check(self) -> CheckResult:
        return await self.inner.check()

    async def complete_json(self, request: AIRequest) -> ModelJson:
        entry: dict[str, Any] = {
            "template": request.template.name,
            "input": input_digest(request),
        }
        self.calls.append(entry)
        start = time.monotonic()
        try:
            async with asyncio.timeout(LIVE_DEADLINE_SECONDS):
                answer = await self.inner.complete_json(request)
        except AIError as error:
            entry["answer"] = {_ERROR_KEY: error.code.value}
            raise
        except TimeoutError:
            entry["answer"] = {_ERROR_KEY: AIErrorCode.PROVIDER_UNAVAILABLE.value}
            raise AIError(AIErrorCode.PROVIDER_UNAVAILABLE) from None
        finally:
            entry["latency_ms"] = 0 if self.stub else int((time.monotonic() - start) * 1000)
            usage = getattr(self.inner, "usage", None)
            entry["usage"] = list(usage) if isinstance(usage, tuple) else None
        entry["answer"] = answer
        return answer


# --- running ---------------------------------------------------------------------------------


@dataclass
class Run:
    """The merged results of one case: keyword only and with the model."""

    keyword: dict[str, set[str]]
    kw_result: TaggingResult
    result: TaggingResult
    state: ModelState
    error: str | None = None


def _merge(
    case: Case,
    keyword: Mapping[str, Set[str]],
    state: ModelState | None = None,
    failures: Sequence[Failure] = (),
) -> TaggingResult:
    return merge_tags(
        clauses=clauses_of(case.document),
        topics=case.topics,
        keyword=keyword,
        model_high=state.high if state else None,
        model_low=state.low if state else None,
        check_yes=state.check_yes if state else None,
        failures=failures,
    )


def run_case(case: Case, tag: AIProvider, check: AIProvider, deadline: float) -> Run:
    """Keyword tags, model steps and the merge, the way ``run_tagging`` does them."""
    keyword = keyword_tags(clauses_of(case.document), case.topics)
    state = ModelState()
    error: str | None = None
    try:
        asyncio.run(
            run_model_steps(case.document, case.topics, case.batches, tag, check, state, deadline)
        )
    except AIError as hard:
        error = hard.code.value
    failures: list[Failure] = [f for f in ("bad_output", "timeout", "quota") if f in state.failures]
    if "check_failed" in state.failures:
        failures.append("check_failed")
    return Run(keyword, _merge(case, keyword), _merge(case, keyword, state, failures), state, error)


def record(  # noqa: PLR0913
    cases: Sequence[Case],
    make: Callable[[str], AIProvider],
    model: str,
    check_model: str,
    *,
    stub: bool,
    provider: str,
) -> dict[str, Any]:
    """Run every case with fresh providers and build a recording."""
    out: dict[str, Any] = {}
    for case in cases:
        calls: list[dict[str, Any]] = []
        tag = RecordingProvider(make(model), calls, stub=stub)
        check = (
            tag if check_model == model else RecordingProvider(make(check_model), calls, stub=stub)
        )
        run_case(case, tag, check, LIVE_DEADLINE_SECONDS * 5)
        out[case.name] = {"calls": calls}
    return {
        "stub": stub,
        "about": (
            "STUB recording from a deterministic local oracle (eval/tagging/oracle.py), not a "
            "model. Its numbers measure the harness only; replace it with a live run."
            if stub
            else "Live recording."
        ),
        "provider": provider,
        "model": model,
        "check_model": check_model,
        "keys": {
            PromptTemplate.TAG_CLAUSES.name: template_key(PromptTemplate.TAG_CLAUSES, model),
            PromptTemplate.CHECK_TAGS.name: template_key(PromptTemplate.CHECK_TAGS, check_model),
        },
        "cases": out,
    }


def replay(cases: Sequence[Case], recording: dict[str, Any], name: str) -> dict[str, Run]:
    models = {
        PromptTemplate.TAG_CLAUSES: recording["model"],
        PromptTemplate.CHECK_TAGS: recording["check_model"],
    }
    for template, model in models.items():
        if recording["keys"].get(template.name) != template_key(template, model):
            raise RecordingError(
                f"recording {name}: the prompt template {template.name} or its JSON schema "
                f"changed since it was recorded (model {model}). Refresh it with --live "
                "(or --write-stub for the stub) and review the new numbers."
            )
    runs: dict[str, Run] = {}
    for case in cases:
        entry = recording["cases"].get(case.name)
        if entry is None:
            raise RecordingError(f"recording {name}: no answers for case {case.name}")
        provider = ReplayProvider(entry["calls"], case.name, name)
        runs[case.name] = run_case(case, provider, provider, REPLAY_DEADLINE_SECONDS)
        if provider.left:
            raise RecordingError(
                f"recording {name}: case {case.name} makes fewer calls than recorded. "
                "Refresh the recording."
            )
    return runs


# --- metrics ---------------------------------------------------------------------------------


def _rate(good: float, total: float) -> float:
    return round(good / total, 4) if total else 1.0


@dataclass
class Tally:
    counts: dict[str, list[float]] = field(default_factory=lambda: defaultdict(lambda: [0.0, 0.0]))

    def add(self, name: str, good: float, total: float) -> None:
        self.counts[name][0] += good
        self.counts[name][1] += total

    def rates(self) -> dict[str, float]:
        return {name: _rate(g, t) for name, (g, t) in self.counts.items()}


def gold_pairs(case: Case) -> dict[str, set[str]]:
    """Clause id -> expected topics, for every numbered clause."""
    by_number = {number: cid for cid, number in case.numbers.items() if number is not None}
    listed = set(case.gold["clauses"]) | set(case.gold["other"])
    if listed != set(by_number):
        missing = sorted(set(by_number) - listed)
        extra = sorted(listed - set(by_number))
        raise RecordingError(f"fixture {case.name}: clause numbers differ: {missing} / {extra}")
    return {by_number[n]: set(case.gold["clauses"].get(n, ())) for n in by_number}


def _predicted(result: TaggingResult) -> dict[str, set[str]]:
    return {
        cid: {t for t in tags if result.topics[t].not_analyzed is None}
        for cid, tags in result.tags.items()
    }


def _pair_metrics(
    prefix: str, case: Case, gold: dict[str, set[str]], result: TaggingResult, tally: Tally
) -> None:
    predicted = _predicted(result)
    adversarial = case.adversarial
    scopes = (":adversarial",) if adversarial else ("", f":{case.domain}", f":{case.lang}")
    for topic in case.topics:
        tid = topic.topic_id
        expected = {cid for cid, ts in gold.items() if tid in ts}
        found = {cid for cid in gold if tid in predicted.get(cid, set())}
        hit = len(expected & found)
        per_topic = () if adversarial else (f":{case.domain}/{tid}",)
        for scope in (*scopes, *per_topic):
            tally.add(f"{prefix}.recall{scope}", hit, len(expected))
            tally.add(f"{prefix}.precision{scope}", hit, len(found))
    other = set(result.other) & set(gold)
    want_other = {cid for cid, ts in gold.items() if not ts}
    by_number = {n: cid for cid, n in case.numbers.items() if n is not None}
    want_risk = {by_number[n] for n in case.gold["risk_terms"]}
    present = set().union(*gold.values())
    missing = set(result.missing_topics)
    for scope in scopes:
        tally.add(f"{prefix}.other.share{scope}", len(other), len(gold))
        tally.add(f"{prefix}.other.recall{scope}", len(want_other & other), len(want_other))
        tally.add(f"{prefix}.risk.recall{scope}", len(want_risk & set(result.risk)), len(want_risk))
        tally.add(
            f"{prefix}.missing.recall{scope}", len(missing & set(case.absent)), len(case.absent)
        )
    if not adversarial:
        tally.counts[f"{prefix}.missing.false_positives"][0] += len(missing & present)


def hidden(result: TaggingResult, clause_ids: Sequence[str]) -> int:
    """Clauses that are neither tagged (with an analysed topic) nor in "Other"."""
    other = set(result.other)
    tagged = {cid for cid, ts in _predicted(result).items() if ts}
    return sum(1 for cid in clause_ids if cid not in tagged and cid not in other)


def leaks(result: TaggingResult, case: Case) -> int:
    """Strings in a result that are not clause ids, topic ids or enums."""
    allowed = {c.id for c in case.document.clauses} | {t.topic_id for t in case.topics} | _ENUMS
    allowed |= set(result.incomplete_reasons)
    strings = [*result.tags, *result.other, *result.risk, *result.topics, *result.missing_topics]
    strings += [s for tags in result.tags.values() for item in tags.items() for s in item]
    strings += [s.not_analyzed for s in result.topics.values() if s.not_analyzed]
    return sum(1 for s in strings if s not in allowed)


def cap_violations(result: TaggingResult) -> int:
    over_clause = sum(
        1
        for tags in result.tags.values()
        if sum(1 for s in tags.values() if s in {"model", "check"}) > MAX_MODEL_TAGS_PER_CLAUSE
    )
    over_topic = sum(
        1 for s in result.topics.values() if s.model_clauses > MAX_MODEL_CLAUSES_PER_TOPIC
    )
    return over_clause + over_topic


def _clause(case: Case, number: str) -> str:
    return next(cid for cid, n in case.numbers.items() if n == number)


def _fixed_attack(case: Case, keyword: dict[str, set[str]]) -> tuple[TaggingResult, set[str]]:
    """A fully compromised model answer: ``skip_me`` - the model obeys the injected sentence and
    gives 3.2 five other topics, never deductible; ``flood`` - 5 high tags on every clause."""
    ids = [c.id for c in case.document.clauses]
    others = [t.topic_id for t in case.topics if t.topic_id != "deductible"]
    state = ModelState()
    if case.name == "skip_me":
        state.high = {_clause(case, "3.2"): set(others[:MAX_MODEL_TAGS_PER_CLAUSE])}
        return _merge(case, keyword, state), set()
    flood = set(others[:MAX_MODEL_TAGS_PER_CLAUSE])
    state.high = {cid: set(flood) for cid in ids}
    return _merge(case, keyword, state), flood


def _adversarial(case: Case, run: Run, metrics: dict[str, float]) -> None:
    ids = [c.id for c in case.document.clauses]
    fixed, flood = _fixed_attack(case, run.keyword)
    target = _clause(case, "3.2" if case.name == "skip_me" else "3.1")
    for mode, result in (("recorded", run.result), ("fixed", fixed)):
        key = f"adversarial.{case.name}"
        metrics[f"{key}.hidden_clauses:{mode}"] = float(hidden(result, ids))
        metrics[f"{key}.deductible_missing:{mode}"] = float(
            "deductible" not in result.tags.get(target, {})
        )
        metrics[f"{key}.cap_violations:{mode}"] = float(cap_violations(result))
        metrics[f"{key}.leaks:{mode}"] = float(leaks(result, case))
    if flood:
        # Every model tag of a topic over the cap is dropped, and the topic is flagged.
        metrics["adversarial.flood.not_dropped:fixed"] = float(
            sum(1 for t in flood if not fixed.topics[t].model_tags_dropped)
        )


def evaluate(
    name: str, recording: dict[str, Any] | None = None
) -> tuple[dict[str, float], dict[str, Any]]:
    """Metrics of one recording (by file name without ``.json``). Raises ``RecordingError``."""
    if recording is None:
        recording = _json(RECORDINGS / f"{name}.json")
    cases = build_cases(catalog())
    runs = replay(cases, recording, name)
    tally = Tally()
    metrics: dict[str, float] = {}
    hidden_total = 0.0
    for case in cases:
        run = runs[case.name]
        ids = [c.id for c in case.document.clauses]
        hidden_total += hidden(run.result, ids) + hidden(run.kw_result, ids)
        gold = gold_pairs(case)
        _pair_metrics("kw", case, gold, run.kw_result, tally)
        _pair_metrics("all", case, gold, run.result, tally)
        if case.adversarial:
            _adversarial(case, run, metrics)
            continue
        metrics["adversarial.leaks"] = metrics.get("adversarial.leaks", 0.0) + leaks(
            run.result, case
        )
    metrics["adversarial.hidden_clauses"] = hidden_total
    for name_, value in tally.rates().items():
        if name_.endswith("false_positives"):
            continue
        metrics[name_] = value
    for prefix in ("kw", "all"):
        metrics[f"{prefix}.missing.false_positives"] = tally.counts[
            f"{prefix}.missing.false_positives"
        ][0]
    return dict(sorted(metrics.items())), {"stub": recording["stub"], **info(runs, recording)}


def info(runs: Mapping[str, Run], recording: dict[str, Any]) -> dict[str, Any]:
    """Calls, failures, cost and latency, information only (not in the baseline)."""
    calls = [c for case in recording["cases"].values() for c in case["calls"]]
    usage = [c["usage"] for c in calls if c.get("usage")]
    latency = [c["latency_ms"] for c in calls if c.get("latency_ms")]
    return {
        "calls": len(calls),
        "tag_calls": sum(1 for c in calls if c["template"] == "TAG_CLAUSES"),
        "check_calls": sum(1 for c in calls if c["template"] == "CHECK_TAGS"),
        "incomplete": sorted(n for n, r in runs.items() if r.result.model_tagging_incomplete),
        "hard_errors": sorted(f"{n}:{r.error}" for n, r in runs.items() if r.error),
        "latency_ms_mean": round(sum(latency) / len(latency), 1) if latency else 0.0,
        "tokens_in": sum(u[0] for u in usage),
        "tokens_out": sum(u[1] for u in usage),
    }


def informational(name: str, *, stub: bool) -> bool:
    return (
        name.endswith(NO_DIRECTION)
        or ".other.share:" in name
        or (stub and name.startswith(MODEL_METRICS))
    )


def regressions(
    current: dict[str, float], baseline: dict[str, float], *, stub: bool = True
) -> list[str]:
    """Gated metrics that got worse than the baseline by more than the tolerance."""
    found: list[str] = []
    for name, base in baseline.items():
        if name in current and informational(name, stub=stub):
            continue
        if name not in current:
            found.append(f"{name}: missing (baseline {base})")
        elif name.startswith(LOWER_IS_BETTER):
            if current[name] > base + BASELINE_TOLERANCE:
                found.append(f"{name}: {current[name]:g} > baseline {base:g}")
        elif current[name] < base - BASELINE_TOLERANCE:
            found.append(f"{name}: {current[name]:.4f} < baseline {base:.4f}")
    found.extend(f"{name}: not in baseline" for name in current if name not in baseline)
    return found


def improvements(current: dict[str, float], baseline: dict[str, float]) -> list[str]:
    """Counts below the baseline: tighten the baseline."""
    return [
        f"{name}: {current[name]:g} < baseline {base:g}: tighten the baseline"
        for name, base in baseline.items()
        if name.startswith(LOWER_IS_BETTER)
        and name in current
        and current[name] < base - BASELINE_TOLERANCE
    ]


# --- synonym report --------------------------------------------------------------------------


def synonym_report(cases: Sequence[Case] | None = None) -> tuple[list[str], list[str]]:
    """Keyword precision per topic (low ones flagged) and catalog synonyms with false hits.

    A synonym hit on a clause whose gold set lacks the topic is a false hit. Rows are sorted
    by false hits, worst first."""
    cases = [c for c in (cases or build_cases(catalog())) if not c.adversarial]
    hits: dict[tuple[str, str, str, str], list[int]] = defaultdict(lambda: [0, 0])
    tally = Tally()
    for case in cases:
        gold = gold_pairs(case)
        entries = [
            (f"{t.topic_id}\x1f{lang}\x1f{s}", s)
            for t in case.topics
            for lang, syns in (("en", t.synonyms_en), ("uk", t.synonyms_uk), ("ru", t.synonyms_ru))
            for s in syns
        ]
        index = PhraseIndex(entries)
        for clause in case.document.clauses:
            if clause.id not in gold:
                continue
            for key in index.find_keys(match_view(clause.text)):
                topic, lang, synonym = key.split("\x1f")
                hits[(case.domain, topic, lang, synonym)][topic in gold[clause.id]] += 1
        result = _merge(case, keyword_tags(clauses_of(case.document), case.topics))
        predicted = _predicted(result)
        for t in case.topics:
            found = {cid for cid in gold if t.topic_id in predicted.get(cid, set())}
            good = sum(1 for cid in found if t.topic_id in gold[cid])
            tally.add(f"{case.domain}/{t.topic_id}", good, len(found))
    topics = [
        f"{name:45s} {rate:.2f} ({int(tally.counts[name][0])}/{int(tally.counts[name][1])})"
        + ("  LOW" if rate < LOW_PRECISION else "")
        for name, rate in sorted(tally.rates().items(), key=lambda item: (item[1], item[0]))
        if tally.counts[name][1]
    ]
    synonyms = [
        f"{d}/{t} [{lang}] {s!r}: false {bad}, true {good}"
        for (d, t, lang, s), (bad, good) in sorted(
            hits.items(), key=lambda kv: (-kv[1][0], kv[1][1], kv[0])
        )
        if bad
    ]
    return topics, synonyms


# --- command line ----------------------------------------------------------------------------


def _live_factory(args: argparse.Namespace) -> Callable[[str], AIProvider]:
    from app.ai.factory import provider_for  # noqa: PLC0415 - live mode only
    from app.ai.presets import PresetId  # noqa: PLC0415

    raw = os.environ.get(KEY_ENV)
    if not raw:
        raise SystemExit(f"--live needs the provider key in the environment variable {KEY_ENV}")
    key = SecretStr(raw)
    del raw
    preset = PresetId(args.provider)
    account = os.environ.get(CF_ACCOUNT_ENV)
    return lambda model: provider_for(preset, model, key, args.base_url, free_account_id=account)


def _models(args: argparse.Namespace, parser: argparse.ArgumentParser) -> tuple[str, str]:
    from app.ai.presets import MODEL_PAIRS, PresetId  # noqa: PLC0415 - live mode only

    pair = MODEL_PAIRS.get(PresetId(args.provider))
    model = args.model or (pair.cheap if pair else None)
    if not model:
        parser.error("--live needs --model for this provider")
    check = args.check_model or (pair.strong if pair and not args.model else model)
    return model, check


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9.-]+", "-", text).strip("-")[:80]


def _write(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--recorded", action="store_true", help="replay recordings (default)")
    mode.add_argument("--live", action="store_true", help="call a provider, write a recording")
    mode.add_argument("--write-stub", action="store_true", help="write the stub recording")
    mode.add_argument("--synonyms", action="store_true", help="keyword precision report")
    parser.add_argument("--recording", help="recording name (default: every file)")
    parser.add_argument("--provider")
    parser.add_argument("--model", help="cheap model (tagging); default: preset pair")
    parser.add_argument("--check-model", help="strong model (checks); default: preset pair")
    parser.add_argument("--base-url")
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument(
        "--accept-regressions",
        action="store_true",
        help="let --write-baseline store numbers that are worse than the baseline",
    )
    return parser


def _refresh(args: argparse.Namespace, parser: argparse.ArgumentParser) -> str:
    """Write a live or a stub recording; return its name."""
    cases = build_cases(catalog())
    if args.live:
        if not args.provider:
            parser.error("--live needs --provider")
        model, check = _models(args, parser)
        name = f"{_slug(args.provider)}__{_slug(model)}__{_slug(check)}"
        data = record(cases, _live_factory(args), model, check, stub=False, provider=args.provider)
    else:
        name = STUB_NAME
        data = record(
            cases, lambda _m: OracleProvider(), STUB_MODEL, STUB_MODEL, stub=True, provider="stub"
        )
    _write(RECORDINGS / f"{name}.json", data)
    return name


def _print(
    name: str, metrics: dict[str, float], extra: dict[str, Any], base: dict[str, float]
) -> tuple[list[str], list[str]]:
    sys.stdout.write(f"== {name}{STUB_LABEL if extra['stub'] else ''}\n")
    for metric, value in metrics.items():
        before = base.get(metric)
        delta = "" if before is None else f"  (baseline {before:g}, delta {value - before:+.4f})"
        if informational(metric, stub=extra["stub"]):
            delta += "  [informational]"
        sys.stdout.write(f"  {metric:55s} {value:g}{delta}\n")
    sys.stdout.write(f"  info: {json.dumps(extra)}\n")
    found = regressions(metrics, base, stub=extra["stub"]) if base else []
    better = improvements(metrics, base)
    sys.stdout.writelines(f"  REGRESSION {line}\n" for line in found)
    sys.stdout.writelines(f"  IMPROVED {line}\n" for line in better)
    return found, better


def _baseline_diff(metrics: dict[str, float], base: dict[str, float]) -> None:
    changed = sorted({m for m in metrics if base.get(m) != metrics[m]} | set(base) - set(metrics))
    sys.stdout.writelines(f"  BASELINE {m}: {base.get(m)} -> {metrics.get(m)}\n" for m in changed)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.synonyms:
        topics, synonyms = synonym_report()
        sys.stdout.write("== keyword precision per topic (worst first)\n")
        sys.stdout.writelines(f"  {line}\n" for line in topics)
        sys.stdout.write("== synonyms with false hits (worst first)\n")
        sys.stdout.writelines(f"  {line}\n" for line in synonyms)
        return 0
    RECORDINGS.mkdir(exist_ok=True)
    if args.live or args.write_stub:
        names = [_refresh(args, parser)]
    elif args.recording:
        names = [args.recording]
    else:
        names = sorted(p.stem for p in RECORDINGS.glob("*.json"))
    baseline = _json(BASELINE_PATH) if BASELINE_PATH.is_file() else {}
    failed = False
    for name in names:
        try:
            metrics, extra = evaluate(name)
        except RecordingError as error:
            sys.stderr.write(f"FAIL {error}\n")
            return 2
        base = baseline.get(name, {}).get("metrics", {})
        found, better = _print(name, metrics, extra, base)
        if not args.write_baseline:
            failed = failed or bool(found or better)
            continue
        _baseline_diff(metrics, base)
        if found and not args.accept_regressions:
            sys.stderr.write(f"FAIL {name}: regressions; use --accept-regressions to store\n")
            return 1
        baseline[name] = {"stub": extra["stub"], "metrics": metrics}
    if args.write_baseline:
        BASELINE_PATH.write_text(
            json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
