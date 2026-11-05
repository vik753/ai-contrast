"""S8-T1 AC3: never a clause lost (ADR 0009 "tagging cannot hide a clause")."""
# ruff: noqa: S311, C416

from __future__ import annotations

import random

import pytest

from app.tagging.merge import merge_tags

from .helpers import clause, topic

REASONS = ["bad_output", "timeout", "quota", "check_failed"]
WORDS = ["pay", "penalty", "cover", "term", "notice", "fine", "right", "list"]


def _case(seed: int) -> tuple[list, list, dict]:  # type: ignore[type-arg]
    rng = random.Random(seed)
    n_clauses = rng.choice([5, 40, 130, 200])
    n_topics = rng.randint(1, 4)
    ids = [f"c{i}" for i in range(1, n_clauses + 1)]
    tids = [f"custom_{i}" for i in range(1, n_topics + 1)]
    cl = [clause(i + 1, " ".join(rng.choices(WORDS, k=6))) for i in range(n_clauses)]

    def pick(prob: float, max_topics: int = 3) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for cid in ids:
            if rng.random() < prob:
                out[cid] = set(rng.sample(tids, rng.randint(1, min(max_topics, n_topics))))
        return out

    flood = rng.choice([0.05, 0.4, 0.9])
    low = pick(rng.choice([0.0, 0.2]))
    kwargs = {
        "keyword": {cid: set(v) for cid, v in pick(flood).items()} | {},
        "model_high": pick(rng.choice([0.0, 0.3, 0.9])),
        "model_low": low,
        "check_yes": {c: set(v) for c, v in low.items() if rng.random() < 0.5},
        "client": {c: v for c, v in pick(0.1, 2).items()},
        "failures": rng.sample(REASONS, rng.randint(0, 2)),
    }
    kwargs["keyword"] = {cid: kwargs["keyword"].get(cid, set()) for cid in ids}  # type: ignore[union-attr]
    return cl, [topic(i) for i in range(1, n_topics + 1)], kwargs


@pytest.mark.parametrize("seed", range(60))
def test_merge_every_clause_is_tagged_or_in_other(seed: int) -> None:
    cl, topics, kwargs = _case(seed)
    r = merge_tags(clauses=cl, topics=topics, **kwargs)
    assert set(r.tags) == {c.id for c in cl}
    for c in cl:
        assert r.tags[c.id] or c.id in r.other, (seed, c.id)
    assert len(set(r.other)) == len(r.other)
    assert set(r.other) <= {c.id for c in cl}


@pytest.mark.parametrize("seed", range(60))
def test_merge_keyword_tags_survive_every_cap(seed: int) -> None:
    cl, topics, kwargs = _case(seed)
    r = merge_tags(clauses=cl, topics=topics, **kwargs)
    for cid, tids in kwargs["keyword"].items():
        for tid in tids:
            assert r.tags[cid].get(tid) == "keyword", (seed, cid, tid)


@pytest.mark.parametrize("seed", range(60))
def test_merge_caps_hold_for_random_input(seed: int) -> None:
    cl, topics, kwargs = _case(seed)
    r = merge_tags(clauses=cl, topics=topics, **kwargs)
    for tags in r.tags.values():
        assert sum(1 for s in tags.values() if s in {"model", "check"}) <= 5
    for tid, status in r.topics.items():
        modelled = sum(1 for t in r.tags.values() if t.get(tid) in {"model", "check"})
        assert modelled <= 60
        assert status.model_clauses == modelled
        if status.model_tags_dropped:
            assert modelled == 0
        has_failure = bool(kwargs["failures"])
        if has_failure:
            assert tid not in r.missing_topics
    assert r.model_tagging_incomplete == bool(kwargs["failures"])
