# ruff: noqa: PLC0415, UP031
"""S8-T2 AC1, 2, 6: what the model sees (one document, opaque topics, batches, templates)."""

from __future__ import annotations

import json
import re

from app.ai.prompts import PromptTemplate
from tests.tag_api.helpers import (
    TagRig,
    custom,
    free_tag_rig,
    tag_body,
)

LABEL = "Q"
TITLE = "Zephyrtitle cover"
DESC = "Zephyrdesc rules of the cover"
SYN = "zephyrsyn"


def _wire_rig() -> tuple[TagRig, dict[str, object]]:
    rig = TagRig(lambda ids, n: {ids[0]: [("T1", "low")]})
    topics = {"custom": [custom(7, title=TITLE, desc=DESC, syn=[SYN, "zephyrother"])]}
    return rig, tag_body(
        "A clause about nothing special here.", "Plain clause.", topics=topics, label=LABEL
    )


def test_template_members_exist_and_differ() -> None:
    assert PromptTemplate.TAG_CLAUSES.value != PromptTemplate.CHECK_TAGS.value


def test_prompts_list_topics_by_opaque_index_with_title_and_description_only() -> None:
    rig, body = _wire_rig()
    assert rig.post(body).status_code == 200
    first = rig.tags.of("tag")[0][4]
    assert f"T1: {TITLE}" in first
    assert DESC in first
    for banned in (SYN, "zephyrother", "custom_7"):
        assert banned not in first, banned
    for _, _, _, _, text in rig.tags.of("check"):
        assert SYN not in text
        assert "custom_7" not in text


def test_prompts_for_catalog_topics_carry_no_id_and_no_synonym() -> None:
    rig = TagRig(lambda ids, n: {})
    ref = {
        "domain": "kasko",
        "topic_id": "theft_cover",
        "side": "insured",
        "lang": "en",
        "catalog_version": rig.catalog_version(),
    }
    assert rig.post(tag_body(topics={"catalog": [ref]})).status_code == 200
    text = rig.tags.of("tag")[0][4]
    assert "T1: Theft cover" in text
    assert "theft_cover" not in text
    assert "stolen" not in text.lower()


def test_prompts_contain_the_template_text_as_system_message() -> None:
    rig, body = _wire_rig()
    rig.post(body)
    sent = json.loads(rig.tags.seen[0].body)
    assert sent["messages"][0]["role"] == "system"
    assert sent["messages"][0]["content"] == PromptTemplate.TAG_CLAUSES.value
    assert "tools" not in sent
    assert "tool_choice" not in sent


def test_tag_and_check_calls_use_their_own_model() -> None:
    rig, body = _wire_rig()
    rig.post(body)
    assert {c[1] for c in rig.tags.of("tag")} == {"gpt-cheap-1"}
    assert {c[1] for c in rig.tags.of("check")} == {"gpt-strong-1"}


def test_check_model_defaults_to_model() -> None:
    rig = TagRig(lambda ids, n: {ids[0]: [("T1", "low")]})
    body = {k: v for k, v in tag_body("A clause about deductible.").items() if k != "check_model"}
    rig.post(body)
    assert {c[1] for c in rig.tags.of("check")} == {"gpt-cheap-1"}


def test_free_mode_uses_one_model_for_both_calls() -> None:
    rig = free_tag_rig(lambda ids, n: {ids[0]: [("T1", "low")]})
    r = rig.free_tag()
    assert r.status_code == 200
    assert {c[1] for c in rig.tags.calls} == {"@cf/openai/gpt-oss-120b"}
    assert {c[0] for c in rig.tags.calls} == {"tag", "check"}


def test_model_pairs_per_preset() -> None:
    from app.ai.presets import MODEL_PAIRS, PRESETS, PresetId

    assert PresetId.CUSTOM not in MODEL_PAIRS
    free = MODEL_PAIRS[PresetId.FREE]
    assert free.cheap == free.strong == "@cf/openai/gpt-oss-120b"
    for preset_id, pair in MODEL_PAIRS.items():
        if preset_id is PresetId.FREE:
            continue
        assert pair.cheap in PRESETS[preset_id].models
        assert pair.strong in PRESETS[preset_id].models
        assert pair.cheap != pair.strong


def test_batches_have_at_most_40_clauses_and_cover_each_clause_once() -> None:
    texts = tuple(f"Clause number {n} about deductible." for n in range(1, 101))
    rig = TagRig(lambda ids, n: {})
    assert rig.post(tag_body(*texts)).status_code == 200
    batches = [c[2] for c in rig.tags.of("tag")]
    assert len(batches) >= 3
    assert all(len(b) <= 40 for b in batches)
    flat = [cid for b in batches for cid in b]
    assert sorted(flat, key=lambda s: int(s[1:])) == [f"c{n}" for n in range(1, 101)]


def test_batches_have_at_most_12000_characters_of_clause_text() -> None:
    texts = tuple(("word%d " % n) * 500 for n in range(10))  # about 3,300 characters each
    rig = TagRig(lambda ids, n: {})
    assert rig.post(tag_body(*texts)).status_code == 200
    batches = [c[2] for c in rig.tags.of("tag")]
    assert len(batches) >= 3
    for ids in batches:
        assert sum(len(texts[int(i[1:]) - 1]) for i in ids) <= 12000
    assert sorted(i for b in batches for i in b) == sorted(f"c{n}" for n in range(1, 11))


def test_every_call_carries_clauses_of_the_one_document_only() -> None:
    rig = TagRig(lambda ids, n: {ids[0]: [("T1", "low")]})
    rig.tag()
    known = {"c1", "c2", "c3"}
    for _, _, ids, pairs, _ in rig.tags.calls:
        assert set(ids) <= known
        assert {c for c, _ in pairs} <= known


def test_wire_never_has_the_provider_key_in_the_body_or_url() -> None:
    from tests.check.helpers import CLIENT_KEY

    rig = TagRig(lambda ids, n: {ids[0]: [("T1", "low")]})
    rig.tag()
    for seen in rig.tags.seen:
        assert CLIENT_KEY not in seen.url
        assert CLIENT_KEY not in seen.body.decode()
        assert CLIENT_KEY in seen.headers.get("authorization", "")


def test_prompt_data_blocks_use_a_fresh_nonce_per_call() -> None:
    rig = TagRig(lambda ids, n: {})
    rig.post(tag_body(*[f"Clause {n} text deductible." for n in range(1, 90)]))
    nonces = [set(re.findall(r"\b[0-9a-f]{32}\b", c[4])) for c in rig.tags.of("tag")]
    assert len(nonces) >= 3
    assert all(n for n in nonces)
    assert len({frozenset(n) for n in nonces}) == len(nonces)
