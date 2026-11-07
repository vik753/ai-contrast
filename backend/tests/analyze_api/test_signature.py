# ruff: noqa: E501, E731, PLC0415, PT018
"""S9-T3 AC1: signature v2 on /api/tag, 409 tagging_signature_invalid, signed fields only, client tags."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from tests.analyze_api.helpers import AnalyzeRig, ref, topics_for
from tests.tag_api.helpers import TagRig, custom, tag_body

MODEL_TAG = lambda ids, n: {"c3": [("T2", "high")]}


def _rig() -> tuple[AnalyzeRig, dict[str, Any]]:
    rig = AnalyzeRig(MODEL_TAG)
    return rig, rig.ready(topics=topics_for(rig, "deductible"))


def _refused(rig: AnalyzeRig, body: dict[str, Any]) -> None:
    r = rig.analyze(body)
    assert (r.status, r.error) == (409, "tagging_signature_invalid")
    assert rig.up.rates == []


# --- /api/tag: the signature binds more (v2) --------------------------------------------------


def _sig(rig: TagRig, body: dict[str, Any]) -> str:
    r = rig.post(body)
    assert r.status_code == 200, r.text
    return str(r.json()["signature"])


def test_tag_signature_differs_for_another_side() -> None:
    rig = TagRig()
    a = _sig(rig, tag_body(topics={"catalog": [ref("deductible", rig)]}))
    b = _sig(rig, tag_body(side="insurer", topics={"catalog": [ref("deductible", rig, "insurer")]}))
    assert a != b


def test_tag_signature_differs_when_a_topic_definition_changes_with_the_same_id() -> None:
    rig = TagRig()
    one = {"custom": [custom(1, syn=["deductible"])]}
    two = {"custom": [{**custom(1, syn=["deductible"]), "description": "Changed rules"}]}
    assert _sig(rig, tag_body(topics=one)) != _sig(rig, tag_body(topics=two))


def test_tag_signature_differs_for_another_topic_set() -> None:
    rig = TagRig()
    one = {"custom": [custom(1, syn=["deductible"])]}
    two = {"custom": [custom(1, syn=["deductible"]), custom(2, syn=["towing"])]}
    assert _sig(rig, tag_body(topics=one)) != _sig(rig, tag_body(topics=two))


def test_tag_signature_differs_when_the_incomplete_reasons_differ() -> None:
    texts = ("The deductible applies.", "Notices go in writing.")
    rig = TagRig()
    ok = _sig(rig, tag_body(*texts))
    rig.tags.tag_fn = lambda ids, n: 503
    r = rig.post(tag_body(*texts))
    assert r.json()["incomplete_reasons"] == ["timeout"]
    assert r.json()["signature"] != ok


def test_tag_signature_differs_for_another_domain() -> None:
    rig = TagRig()
    kasko = tag_body(topics={"custom": [custom(1, syn=["rent"])]})
    lease = tag_body(
        domain="lease",
        side="tenant",
        topics={"custom": [{**custom(1, syn=["rent"]), "domain": "lease", "side": "tenant"}]},
    )
    assert _sig(rig, kasko) != _sig(rig, lease)


# --- /api/analyze: every signed field is checked ----------------------------------------------


def test_valid_tagging_gives_a_stream() -> None:
    rig, body = _rig()
    r = rig.analyze(body)
    assert r.status == 200 and r.is_stream


def _no_signature(b: dict[str, Any]) -> None:
    b["tagging"]["signature"] = ""


def _bad_signature(b: dict[str, Any]) -> None:
    sig = b["tagging"]["signature"]
    b["tagging"]["signature"] = sig[:-1] + ("0" if sig[-1] != "0" else "1")


def _version(b: dict[str, Any]) -> None:
    b["tagging"]["tagging_version"] = "old-" + b["tagging"]["tagging_version"]


def _digest_field(b: dict[str, Any]) -> None:
    b["tagging"]["digest"] = "0" * 64


def _document_text(b: dict[str, Any]) -> None:
    b["document"]["clauses"][3]["text"] += " Extra."


def _add_pair(b: dict[str, Any]) -> None:
    b["tagging"]["tags"]["c1"].append({"topic_id": "custom_1", "source": "model"})


def _remove_pair(b: dict[str, Any]) -> None:
    b["tagging"]["tags"]["c3"] = [t for t in b["tagging"]["tags"]["c3"] if t["source"] == "keyword"]


def _change_source(b: dict[str, Any]) -> None:
    for t in b["tagging"]["tags"]["c3"]:
        t["source"] = "check"


def _add_reason(b: dict[str, Any]) -> None:
    b["tagging"]["incomplete_reasons"] = ["timeout"]


def _drop_flag(b: dict[str, Any]) -> None:
    b["tagging"]["topics"]["custom_1"]["model_tags_dropped"] = True


def _not_analyzed(b: dict[str, Any]) -> None:
    b["tagging"]["topics"]["deductible"]["not_analyzed"] = "too_many_clauses"


def _topic_definition(b: dict[str, Any]) -> None:
    b["topics"]["custom"][0]["description"] = "Changed rules"


def _extra_topic(b: dict[str, Any]) -> None:
    b["topics"]["custom"].append(custom(2, title="Glass aid", syn=["windscreen"]))


def _side(b: dict[str, Any]) -> None:
    b["side"] = "insurer"
    b["topics"] = {"catalog": [ref("deductible", TagRig(), "insurer")]}


MUTATIONS: dict[str, Callable[[dict[str, Any]], None]] = {
    "missing-signature": _no_signature,
    "wrong-signature": _bad_signature,
    "tagging-version": _version,
    "digest-field": _digest_field,
    "document-text": _document_text,
    "added-model-pair": _add_pair,
    "removed-model-pair": _remove_pair,
    "changed-source": _change_source,
    "incomplete-reason": _add_reason,
    "model-tags-dropped": _drop_flag,
    "not-analyzed": _not_analyzed,
    "topic-definition": _topic_definition,
    "extra-topic": _extra_topic,
    "side": _side,
}


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_analyze_refuses_a_signed_field_that_changed(name: str) -> None:
    rig = AnalyzeRig(MODEL_TAG)
    tb = rig.base(
        topics={
            "custom": [custom(1, title="Towing aid", syn=["towing"])],
            "catalog": [ref("deductible", rig)],
        }
    )
    body = rig.body(tb, rig.tagged(tb))
    if name == "removed-model-pair":
        assert any(t["source"] == "model" for t in body["tagging"]["tags"]["c3"])
    MUTATIONS[name](body)
    _refused(rig, body)


def test_analyze_refuses_a_changed_domain() -> None:
    rig = AnalyzeRig()
    tb = tag_body(topics={"custom": [custom(1, syn=["rent"])]})
    body = rig.body(tb, rig.tagged(tb))
    body["domain"] = "lease"
    body["side"] = "tenant"
    body["topics"] = {"custom": [{**custom(1, syn=["rent"]), "domain": "lease", "side": "tenant"}]}
    _refused(rig, body)


def test_analyze_refuses_a_signature_of_another_app_instance() -> None:
    old = AnalyzeRig()
    body = old.ready()
    new = AnalyzeRig()
    _refused(new, body)


def test_the_refusal_comes_as_json_before_the_first_stream_byte() -> None:
    rig, body = _rig()
    _bad_signature(body)
    r = rig.analyze(body)
    assert not r.is_stream
    assert r.headers["content-type"].startswith("application/json")


def test_unsigned_topic_counts_do_not_matter() -> None:
    rig, body = _rig()
    for status in body["tagging"]["topics"].values():
        status["keyword_clauses"] = 999
        status["model_clauses"] = 999
        status["model_asserted"] = 999
    assert rig.analyze(body).status == 200


def test_keyword_entries_of_the_browser_are_not_trusted() -> None:
    rig, body = _rig()
    body["tagging"]["tags"]["c1"] = [{"topic_id": "custom_1", "source": "keyword"}]
    r = rig.analyze(body)
    assert r.status == 200
    assert "c1" in rig.up.topic_calls("deductible")[0].ids  # recomputed: c1 is a deductible clause
    assert "c1" not in rig.up.topic_calls("custom_1")[0].ids


# --- missing-topic findings and topic status only from signed fields -------------------------


def _missing(rig: AnalyzeRig, **over: Any) -> Any:
    return rig.run(topics=topics_for(rig, "deductible", "theft_cover", n_custom=0), **over)


def test_missing_topic_is_yellow_when_tagging_was_complete() -> None:
    rig = AnalyzeRig()
    r = _missing(rig)
    assert r.topic("theft_cover")["clauses"] == []
    assert r.topic("theft_cover")["missing"] == {"rating": "yellow"}
    assert rig.up.topic_calls("theft_cover") == []


def test_missing_topic_is_red_when_the_catalog_marks_it_essential(tmp_path: Any) -> None:
    from tests.topics.helpers import mutated

    def essential(kasko: dict[str, Any]) -> None:
        for t in kasko["topics"]:
            if t["id"] == "theft_cover":
                t["essential"] = {"insured": True}

    rig = AnalyzeRig(topics_catalog_dir=mutated(tmp_path, essential))
    assert _missing(rig).topic("theft_cover")["missing"] == {"rating": "red"}


def test_no_missing_finding_when_tagging_was_incomplete() -> None:
    rig = AnalyzeRig(lambda ids, n: 503)
    r = _missing(rig)
    assert r.topic("theft_cover")["missing"] is None


def test_a_browser_cannot_clear_the_incomplete_reasons_to_get_missing_findings() -> None:
    rig = AnalyzeRig(lambda ids, n: 503)
    tb = rig.base(topics=topics_for(rig, "deductible", "theft_cover", n_custom=0))
    body = rig.body(tb, rig.tagged(tb))
    body["tagging"]["incomplete_reasons"] = []
    _refused(rig, body)


def test_a_topic_with_clauses_is_never_missing() -> None:
    rig = AnalyzeRig()
    r = rig.run()
    assert r.topic("deductible")["missing"] is None


# --- client tags: add-only, capped --------------------------------------------------------------


def _client(rig: AnalyzeRig, tags: dict[str, list[str]]) -> Any:
    return _run_client(rig, topics_for(rig, "deductible", n_custom=2), tags)


def _run_client(rig: AnalyzeRig, topics: dict[str, Any], tags: dict[str, list[str]]) -> Any:
    tb = rig.base(topics=topics)
    body = rig.body(tb, rig.tagged(tb))
    body["tagging"]["client_tags"] = tags
    return rig.analyze(body)


def test_a_client_tag_adds_a_clause_to_the_topic_and_removes_it_from_other() -> None:
    rig = AnalyzeRig()
    r = _client(rig, {"c3": ["custom_1"]})
    assert r.status == 200
    assert "c3" in rig.up.topic_calls("custom_1")[0].ids
    assert all("c3" not in o.ids for o in rig.up.of("other"))


def test_a_client_tag_never_removes_a_keyword_tag() -> None:
    rig = AnalyzeRig()
    _client(rig, {"c1": ["custom_2"]})
    assert "c1" in rig.up.topic_calls("deductible")[0].ids
    assert "c1" in rig.up.topic_calls("custom_2")[0].ids


@pytest.mark.parametrize(
    "tags",
    [{"c99": ["custom_1"]}, {"c3": ["no_such_topic"]}, {"c3'; drop": ["custom_1"]}],
)
def test_a_client_tag_with_unknown_ids_is_422(tags: dict[str, list[str]]) -> None:
    rig = AnalyzeRig()
    r = _client(rig, tags)
    assert (r.status, r.error) == (422, "invalid_client_tag")
    assert rig.up.rates == []


def test_more_than_five_client_tags_on_a_clause_is_422() -> None:
    rig = AnalyzeRig()
    topics = {"custom": [custom(n, title=f"Zt{n}", syn=[f"zsyn{n}x"]) for n in (1, 2, 3)]}
    topics["custom"] += [
        {**custom(1, title=f"Zt{n}", syn=[f"zsyn{n}x"]), "topic_id": f"custom_{n}"}
        for n in (4, 5, 6)
    ]
    r = _run_client(rig, topics, {"c3": [f"custom_{n}" for n in range(1, 7)]})
    assert (r.status, r.error) == (422, "too_many_client_tags")


def _flood(rig: AnalyzeRig, n: int, client: dict[str, list[str]]) -> Any:
    texts = [f"The deductible applies to claim {i} of the insured." for i in range(n)]
    texts.append("Notices are sent in writing.")
    return _run_client_texts(rig, texts, client)


def _run_client_texts(rig: AnalyzeRig, texts: list[str], tags: dict[str, list[str]]) -> Any:
    tb = rig.base(*texts, topics=topics_for(rig, "deductible", n_custom=0))
    body = rig.body(tb, rig.tagged(tb))
    body["tagging"]["client_tags"] = tags
    return rig.analyze(body)


def test_client_tags_count_towards_the_keyword_cap_of_120() -> None:
    rig = AnalyzeRig()
    at_cap = _flood(rig, 120, {})
    assert at_cap.topic("deductible")["reason"] == "topic_call_cap"
    over = _flood(AnalyzeRig(), 120, {"c121": ["deductible"]})
    assert over.topic("deductible")["state"] == "not_analyzed"
    assert over.topic("deductible")["reason"] == "too_many_clauses"
