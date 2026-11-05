"""S8-T1 AC1: linear time at the caps (ADR 0018 point 2, ADR 0017 caps)."""
# ruff: noqa: S311, ANN001

from __future__ import annotations

import random
import time

from app.tagging.keywords import keyword_tags
from app.tagging.model import TagClause

from .helpers import clause, pseudo_word, topic

BUDGET_SECONDS = 6.0


def _topics(n_topics: int, n_synonyms: int, rng: random.Random) -> list:  # type: ignore[type-arg]
    result = []
    for n in range(1, n_topics + 1):
        syns = []
        for i in range(n_synonyms):
            if i % 3 == 2:
                syns.append(f"{pseudo_word(rng, 3)} {pseudo_word(rng, 3)}")
            else:
                syns.append(pseudo_word(rng, 4))
        result.append(topic(n, en=syns))
    return result


def _clauses(n: int, rng: random.Random, words: int = 45) -> list[TagClause]:
    return [
        clause(i, " ".join(pseudo_word(rng, rng.randint(2, 5)) for _ in range(words)))
        for i in range(1, n + 1)
    ]


def _cpu(fn) -> float:  # type: ignore[no-untyped-def]
    start = time.process_time()
    fn()
    return time.process_time() - start


def test_keyword_tags_at_caps_runs_within_cpu_budget() -> None:
    rng = random.Random(8)
    topics = _topics(50, 40, rng)
    cl = _clauses(2000, rng)
    elapsed = _cpu(lambda: keyword_tags(cl, topics))
    assert elapsed < BUDGET_SECONDS


def test_keyword_tags_time_grows_linearly_with_clauses() -> None:
    rng = random.Random(9)
    topics = _topics(50, 40, rng)
    small = _clauses(400, rng)
    large = _clauses(1600, rng)
    t_small = max(_cpu(lambda: keyword_tags(small, topics)), 0.01)
    t_large = _cpu(lambda: keyword_tags(large, topics))
    assert t_large / t_small < 8  # 4x the input; a quadratic cost would give about 16x


def test_keyword_tags_long_repeated_prefix_text_is_not_pathological() -> None:
    rng = random.Random(10)
    long_syn = "a" * 59
    topics = [topic(1, en=[long_syn, "a" * 30 + "b"]), *_topics(5, 40, rng)]
    cl = [clause(1, "a" * 200_000), clause(2, ("a " * 100_000)), clause(3, "ab" * 100_000)]
    assert _cpu(lambda: keyword_tags(cl, topics)) < BUDGET_SECONDS


def test_keyword_tags_many_phrase_words_with_much_whitespace_is_linear() -> None:
    topics = [topic(1, en=["aaa aaa aaa aaa aaa aab"])]
    cl = [clause(1, "aaa" + " " * 100_000 + "aaa " * 50_000)]
    assert _cpu(lambda: keyword_tags(cl, topics)) < BUDGET_SECONDS


def test_keyword_tags_at_caps_still_finds_planted_synonyms() -> None:
    rng = random.Random(11)
    topics = _topics(50, 40, rng)
    cl = _clauses(300, rng)
    cl[137] = clause(138, "prefix words and franchise here")
    topics.append(topic(51, en=["franchise"]))
    assert "custom_51" in keyword_tags(cl, topics)["c138"]
