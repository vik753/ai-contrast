"""S8-T4 review: ``finish_tags`` (the merge after the AI calls, shared by ``/api/tag`` and the
tagging eval) and the check-failure rule of ADR 0018 point 3: a failed check call drops only
its own low tags (``run_model_steps`` never records them); check tags confirmed by other
check calls stay; the document is ``model_tagging_incomplete`` with ``check_failed`` and has
no missing-topic finding."""

from __future__ import annotations

from app.tagging.ai_steps import ModelState
from app.tagging.run import finish_tags

from .helpers import clauses, topic


def _state(failures: set[str]) -> ModelState:
    # Batch 1 (c1): low tag on custom_1, confirmed by its check call.
    # Batch 2 (c2): its check call failed, so its low tag was never recorded.
    return ModelState(low={"c1": {"custom_1"}}, check_yes={"c1": {"custom_1"}}, failures=failures)


def test_failed_check_keeps_check_tags_of_other_batches() -> None:
    topics = [topic(1), topic(2)]
    cl = clauses(2)
    keyword: dict[str, set[str]] = {"c1": set(), "c2": set()}
    result = finish_tags(cl, topics, keyword, _state({"check_failed"}))
    assert result.tags["c1"] == {"custom_1": "check"}
    assert result.other == ["c2"]
    assert result.model_tagging_incomplete is True
    assert result.incomplete_reasons == ("check_failed",)
    assert result.missing_topics == ()


def test_check_failed_is_added_to_other_reasons() -> None:
    topics = [topic(1)]
    keyword: dict[str, set[str]] = {"c1": set(), "c2": set()}
    result = finish_tags(clauses(2), topics, keyword, _state({"check_failed", "timeout"}))
    assert result.incomplete_reasons == ("check_failed", "timeout")
    assert result.tags["c1"] == {"custom_1": "check"}


def test_complete_tagging_reports_missing_topics() -> None:
    topics = [topic(1), topic(2)]
    keyword: dict[str, set[str]] = {"c1": set(), "c2": set()}
    result = finish_tags(clauses(2), topics, keyword, _state(set()))
    assert result.model_tagging_incomplete is False
    assert result.missing_topics == ("custom_2",)
