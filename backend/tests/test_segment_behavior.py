# ruff: noqa: RUF001, PT018, E501
"""S5-T1 AC2a, AC3, AC7, AC9: divergence, caps, abuse rules (T3, T5, T6).

Black-box through ``POST /api/segment``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.segment_helpers import (
    MIB,
    block,
    body_bytes,
    clause_text,
    contract_problems,
    cover_problems,
    post_blocks,
    post_raw,
)


def _ok(client: TestClient, blocks: list[dict[str, Any]]) -> dict[str, Any]:
    response = post_blocks(client, blocks)
    assert response.status_code == 200, response.text[:200]
    data: dict[str, Any] = response.json()
    assert contract_problems(data) == []
    assert cover_problems(data) == []
    return data


# --- AC2a divergence ---------------------------------------------------------------------


def test_segment_divergence_blocks_are_cleaned_and_removed_is_reported(
    make_client: Callable[..., TestClient],
) -> None:
    blocks = [
        block("1. Pay\u200bment is due‍ in 30 days."),
        block("2. Notice\x01 in\x07 writing﻿."),
    ]

    data = _ok(make_client(), blocks)

    assert [b["text"] for b in data["blocks"]] == [
        "1. Payment is due in 30 days.",
        "2. Notice in writing.",
    ]
    assert sum(r["count"] for r in data["removed"]) >= 5
    assert all(r["reason"] and isinstance(r["sample"], str) for r in data["removed"])


def test_segment_divergence_spans_point_into_the_cleaned_blocks(
    make_client: Callable[..., TestClient],
) -> None:
    blocks = [block("1. A\u200bB first clause."), block("2. Second\x01 clause.")]

    data = _ok(make_client(), blocks)

    assert [clause_text(c, data["blocks"]) for c in data["clauses"]] == [
        "1. AB first clause.",
        "2. Second clause.",
    ]


def test_segment_divergence_zero_width_inside_number_does_not_hide_the_clause(
    make_client: Callable[..., TestClient],
) -> None:
    data = _ok(make_client(), [block("1\u200b. First clause."), block("2.\u200b Second clause.")])

    assert [c["number"] for c in data["clauses"]] == ["1", "2"]


def test_segment_divergence_lone_surrogate_input_is_cleaned_or_rejected(
    make_client: Callable[..., TestClient],
) -> None:
    raw = b'{"blocks":[{"text":"1. Pay\\ud800ment.","part":"body","page":null},{"text":"2. Next.","part":"body","page":null}]}'

    response = post_raw(make_client(), raw)

    assert response.status_code in (200, 422)
    if response.status_code == 200:
        data = response.json()
        assert cover_problems(data) == []
        assert data["blocks"][0]["text"] in ("1. Payment.", "1. Pay�ment.")


def test_segment_clean_input_reports_nothing_removed(
    make_client: Callable[..., TestClient],
) -> None:
    data = _ok(make_client(), [block("1. Plain clause."), block("2. Another clause.")])

    assert data["removed"] == []
    assert data["warnings"] == []


# --- clause rules from ADR 0014 ------------------------------------------------------------------


def test_segment_lettered_items_stay_inside_the_parent_clause(
    make_client: Callable[..., TestClient],
) -> None:
    data = _ok(
        make_client(),
        [block("1. Duties."), block("a) pay on time;"), block("(b) report;"), block("(i) log.")],
    )

    assert [c["number"] for c in data["clauses"]] == ["1"]
    assert "(i) log." in clause_text(data["clauses"][0], data["blocks"])


@pytest.mark.parametrize(
    ("line", "number"),
    [
        ("Article 5. Term", "5"),
        ("Стаття 7. Строк", "7"),
        ("Статья 9. Срок", "9"),
        ("Section 4. Fees", "4"),
        ("§ 3 Fees", "3"),
        ("IV. Liability", "IV"),
        ("1.2.3 Deep clause.", "1.2.3"),
        ("4) Paren clause.", "4"),
        ("4.1) Paren clause.", "4.1"),
    ],
)
def test_segment_clause_start_styles_give_number_without_the_word(
    make_client: Callable[..., TestClient], line: str, number: str
) -> None:
    data = _ok(make_client(), [block(line + " of the agreement.")])

    assert [c["number"] for c in data["clauses"]] == [number]


def test_segment_text_before_first_clause_is_one_preamble_clause(
    make_client: Callable[..., TestClient],
) -> None:
    data = _ok(make_client(), [block("AGREEMENT"), block("Made today."), block("1. First.")])

    first = data["clauses"][0]
    assert (first["part"], first["number"], first["level"]) == ("preamble", None, 0)
    assert clause_text(first, data["blocks"]).startswith("AGREEMENT")


def test_segment_no_numbering_gives_fallback_clauses_and_warning(
    make_client: Callable[..., TestClient],
) -> None:
    data = _ok(make_client(), [block("First paragraph."), block("Second paragraph.")])

    assert [c["part"] for c in data["clauses"]] == ["body", "body"]
    assert [w["code"] for w in data["warnings"]] == ["no_numbering_found"]


def test_segment_numbering_gap_restart_and_duplicate_are_warned_once_each(
    make_client: Callable[..., TestClient],
) -> None:
    gap = _ok(make_client(), [block("1. A."), block("2. B."), block("5. C.")])
    dup = _ok(make_client(), [block("1. A."), block("2. B."), block("2. C."), block("3. D.")])
    restart = _ok(
        make_client(),
        [block("1. A."), block("2. B."), block("3. C."), block("1. D."), block("2. E.")],
    )

    assert [w["code"] for w in gap["warnings"]] == ["numbering_gap"]
    assert [w["code"] for w in dup["warnings"]] == ["duplicate_number"]
    assert [w["code"] for w in restart["warnings"]] == ["numbering_restart"]


# --- AC7 caps -----------------------------------------------------------------------------------


def _numbered(count: int) -> list[dict[str, Any]]:
    return [block(f"{n}. Synthetic clause number {n}.") for n in range(1, count + 1)]


def test_segment_clauses_at_cap_are_accepted(make_client: Callable[..., TestClient]) -> None:
    data = _ok(make_client(segment_max_clauses=5), _numbered(5))

    assert len(data["clauses"]) == 5


def test_segment_clauses_above_cap_return_422_too_many_clauses(
    make_client: Callable[..., TestClient],
) -> None:
    response = post_blocks(make_client(segment_max_clauses=5), _numbered(6))

    assert response.status_code == 422
    assert response.json() == {"error": "too_many_clauses"}


def test_segment_fallback_clauses_above_cap_return_422_too_many_clauses(
    make_client: Callable[..., TestClient],
) -> None:
    blocks = [block(f"Paragraph without numbering {n}.") for n in range(6)]

    response = post_blocks(make_client(segment_max_clauses=5), blocks)

    assert (response.status_code, response.json()) == (422, {"error": "too_many_clauses"})


def test_segment_clause_cap_counts_non_body_parts_too(
    make_client: Callable[..., TestClient],
) -> None:
    blocks = [block("1. Body clause.")] + [block(f"Note {n}.", part="footnote") for n in range(5)]

    response = post_blocks(make_client(segment_max_clauses=5), blocks)

    assert (response.status_code, response.json()) == (422, {"error": "too_many_clauses"})


def test_segment_default_clause_cap_is_2000(make_client: Callable[..., TestClient]) -> None:
    client = make_client()

    at_cap = post_blocks(client, _numbered(2000))
    over = post_blocks(client, _numbered(2001))

    assert at_cap.status_code == 200 and len(at_cap.json()["clauses"]) == 2000
    assert (over.status_code, over.json()) == (422, {"error": "too_many_clauses"})


def test_segment_clause_of_exactly_cap_characters_is_one_clause(
    make_client: Callable[..., TestClient],
) -> None:
    text = "1. " + "a" * 97

    data = _ok(make_client(segment_max_clause_chars=100), [block(text)])

    assert len(data["clauses"]) == 1
    assert data["clauses"][0]["part_index"] == 0


def test_segment_single_sentence_above_cap_returns_422_clause_too_long(
    make_client: Callable[..., TestClient],
) -> None:
    response = post_blocks(make_client(segment_max_clause_chars=100), [block("1. " + "a" * 98)])

    assert response.status_code == 422
    assert response.json() == {"error": "clause_too_long"}


def test_segment_long_clause_is_split_at_block_boundaries_with_part_index(
    make_client: Callable[..., TestClient],
) -> None:
    blocks = [block("3. Start of a long clause.")] + [
        block(f"Continuation block {n} " + "b" * 30) for n in range(8)
    ]

    data = _ok(make_client(segment_max_clause_chars=100), blocks)

    parts = [c for c in data["clauses"] if c["number"] == "3"]
    assert len(parts) >= 3
    assert [c["part_index"] for c in parts] == list(range(len(parts)))
    assert all(len(clause_text(c, data["blocks"])) <= 100 for c in data["clauses"])
    assert len({c["id"] for c in data["clauses"]}) == len(data["clauses"])
    assert {c["level"] for c in parts} == {parts[0]["level"]}


def test_segment_oversized_block_is_split_at_line_breaks(
    make_client: Callable[..., TestClient],
) -> None:
    text = "1. Obligations\n" + "\n".join(f"line {n} " + "c" * 20 for n in range(10))

    data = _ok(make_client(segment_max_clause_chars=100), [block(text)])

    assert len(data["clauses"]) >= 3
    assert all(len(clause_text(c, data["blocks"])) <= 100 for c in data["clauses"])
    assert {c["number"] for c in data["clauses"]} == {"1"}


def test_segment_oversized_block_is_split_at_sentence_ends(
    make_client: Callable[..., TestClient],
) -> None:
    text = "1. " + " ".join(f"Sentence {n} is " + "d" * 15 + "." for n in range(12))

    data = _ok(make_client(segment_max_clause_chars=100), [block(text)])

    assert len(data["clauses"]) >= 3
    assert all(len(clause_text(c, data["blocks"])) <= 100 for c in data["clauses"])


def test_segment_split_loses_no_character(make_client: Callable[..., TestClient]) -> None:
    blocks = [block("1. Head.")] + [block(f"Body {n}. " + "e" * 40) for n in range(10)]

    data = _ok(make_client(segment_max_clause_chars=120), blocks)

    rebuilt = "".join(clause_text(c, data["blocks"]).replace("\n", "") for c in data["clauses"])
    original = "".join(b["text"] for b in blocks)
    assert rebuilt.replace(" ", "") == original.replace(" ", "")


def test_segment_default_clause_char_cap_is_20000(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client()

    at_cap = post_blocks(client, [block("1. " + "a" * 19_997)])
    over = post_blocks(client, [block("1. " + "a" * 19_998)])

    assert at_cap.status_code == 200 and len(at_cap.json()["clauses"]) == 1
    assert (over.status_code, over.json()) == (422, {"error": "clause_too_long"})


def test_segment_size_test_at_caps_reply_fits_the_result_cap(
    make_client: Callable[..., TestClient],
) -> None:
    """1,000,000 Cyrillic characters, 20,000 blocks, 2,000 clauses."""
    line = ("Сторони домовилися про виконання " * 3)[:40]
    blocks: list[dict[str, Any]] = []
    for clause in range(1, 2001):
        blocks.append(block(f"{clause}. " + line + "а" * (50 - len(f"{clause}. ") - len(line))))
        blocks.extend(block(line + "б" * (50 - len(line))) for _ in range(9))
    assert len(blocks) == 20_000
    assert sum(len(b["text"]) for b in blocks) == 1_000_000
    assert len(body_bytes(blocks)) < 4 * MIB

    response = post_blocks(make_client(), blocks)

    assert response.status_code == 200
    assert len(response.content) < 4 * MIB
    data = response.json()
    assert len(data["clauses"]) == 2000
    assert cover_problems(data) == []


# --- AC9 abuse rules ----------------------------------------------------------------------------


def _paged(
    pages: int, first: str, last: str | None = None, body: bool = True
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [block("1. Opening clause text.", page=1)]
    for page in range(1, pages + 1):
        out.append(block(first, page=page))
        if body:
            out.append(block(f"Unique body sentence on page {page}.", page=page))
        if last is not None:
            out.append(block(last, page=page))
    return out


def _running(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in data["clauses"] if c["part"] == "running"]


def test_segment_short_line_repeated_on_every_page_becomes_one_running_clause(
    make_client: Callable[..., TestClient],
) -> None:
    data = _ok(make_client(), _paged(4, "Confidential draft of the agreement."))

    running = _running(data)
    assert len(running) == 1
    assert running[0]["pages"] == [1, 2, 3, 4]
    assert len(running[0]["spans"]) == 4


def test_segment_line_of_120_characters_can_be_running(
    make_client: Callable[..., TestClient],
) -> None:
    line = "w" * 119 + "."

    data = _ok(make_client(), _paged(4, line))

    assert len(_running(data)) == 1


def test_segment_line_longer_than_120_characters_is_not_collapsed(
    make_client: Callable[..., TestClient],
) -> None:
    line = "w" * 120 + "."

    data = _ok(make_client(), _paged(4, line))

    assert _running(data) == []
    assert sum(clause_text(c, data["blocks"]).count(line) for c in data["clauses"]) == 4


def test_segment_clause_start_line_repeated_on_every_page_is_not_collapsed(
    make_client: Callable[..., TestClient],
) -> None:
    line = "5. The supplier may change prices at any time."

    data = _ok(make_client(), _paged(4, line))

    assert _running(data) == []
    assert sum(clause_text(c, data["blocks"]).count(line) for c in data["clauses"]) == 4


def test_segment_heading_line_repeated_on_every_page_is_not_collapsed(
    make_client: Callable[..., TestClient],
) -> None:
    line = "PAYMENT TERMS"

    data = _ok(make_client(), _paged(4, line))

    assert _running(data) == []
    assert sum(clause_text(c, data["blocks"]).count(line) for c in data["clauses"]) == 4


def test_segment_line_on_fewer_than_three_pages_is_not_running(
    make_client: Callable[..., TestClient],
) -> None:
    blocks = _paged(4, "Header seen on two pages only.")
    blocks = [b for b in blocks if b["text"] != "Header seen on two pages only." or b["page"] <= 2]

    data = _ok(make_client(), blocks)

    assert _running(data) == []


def test_segment_line_in_the_middle_of_pages_is_not_running(
    make_client: Callable[..., TestClient],
) -> None:
    blocks: list[dict[str, Any]] = [block("1. Opening clause.", page=1)]
    for page in range(1, 6):
        blocks += [
            block(f"Top line {page} one.", page=page),
            block(f"Top line {page} two.", page=page),
            block(f"Top line {page} three.", page=page),
            block("Same middle sentence.", page=page),
            block(f"Bottom line {page} one.", page=page),
            block(f"Bottom line {page} two.", page=page),
            block(f"Bottom line {page} three.", page=page),
        ]

    data = _ok(make_client(), blocks)

    assert _running(data) == []


def test_segment_running_header_and_footer_are_separate_running_clauses(
    make_client: Callable[..., TestClient],
) -> None:
    data = _ok(make_client(), _paged(5, "Header of the agreement.", "Footer of the agreement."))

    assert len(_running(data)) == 2
    assert all(c["pages"] == [1, 2, 3, 4, 5] for c in _running(data))


def test_segment_early_signatures_heading_does_not_make_numbered_clauses_requisites(
    make_client: Callable[..., TestClient],
) -> None:
    blocks = [
        block("1. First clause."),
        block("Signatures"),
        block("5. Late payment fee applies."),
        block("6. Governing law is Ukrainian law."),
    ]

    data = _ok(make_client(), blocks)

    numbered = [c for c in data["clauses"] if c["number"] in ("5", "6")]
    assert len(numbered) == 2
    assert all(c["section_kind"] is None for c in numbered)


def test_segment_requisites_heading_must_match_the_whole_line(
    make_client: Callable[..., TestClient],
) -> None:
    blocks = [block("1. First."), block("Signatures of both parties are required"), block("More.")]

    data = _ok(make_client(), blocks)

    assert all(c["section_kind"] is None for c in data["clauses"])


def test_segment_requisites_heading_matches_case_insensitively(
    make_client: Callable[..., TestClient],
) -> None:
    blocks = [block("1. First."), block("SIGNATURES"), block("Party A: ______")]

    data = _ok(make_client(), blocks)

    assert [c["section_kind"] for c in data["clauses"]] == [None, "requisites"]


def test_segment_numbered_clause_is_never_requisites(
    make_client: Callable[..., TestClient],
) -> None:
    blocks = [block("1. First."), block("Signatures"), block("2. Numbered after signatures.")]

    data = _ok(make_client(), blocks)

    assert next(c for c in data["clauses"] if c["number"] == "2")["section_kind"] is None


def test_segment_all_caps_obligation_is_analyzed_inside_exactly_one_clause(
    make_client: Callable[..., TestClient],
) -> None:
    line = "THE SUPPLIER IS NOT LIABLE FOR ANY DAMAGE WHATSOEVER"
    blocks = [block("1. Liability."), block(line), block("2. Term.")]

    data = _ok(make_client(), blocks)

    assert sum(clause_text(c, data["blocks"]).count(line) for c in data["clauses"]) == 1


def test_segment_same_input_gives_same_clauses(make_client: Callable[..., TestClient]) -> None:
    blocks = _paged(4, "Header of the agreement.", "Footer of the agreement.")
    client = make_client()

    first = post_blocks(client, blocks)
    second = post_blocks(client, blocks)

    assert first.status_code == 200
    assert first.content == second.content
