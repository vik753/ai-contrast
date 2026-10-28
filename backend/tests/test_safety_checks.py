# ruff: noqa: RUF001, RUF015, E501
"""S5b-T2 AC2 and AC4: every check of ``POST /api/safety-check``, in order.

Order: 409 detector_version_mismatch, 422 input_not_clean, 422 invalid_placeholder,
422 unmasked_identifier (clause-relative spans), then the acknowledged_unmasked
rules (422 invalid_request). Test data is synthetic; checksummed codes come from
``tests/pseudo_helpers.py``.

Expected to fail until ``/api/safety-check`` exists (S5b-T2 not implemented).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.pseudo_helpers import EDRPOU, IBAN
from tests.safety_helpers import (
    JSON_HEADERS,
    SAFETY,
    build_masked,
    detector_version,
    doc,
    eligible_fixture_names,
    hit_spans,
    post_doc,
)

Make = Callable[..., TestClient]
EMAIL = "ivan.testov@example.com"
MFO_TEXT = "Bank details: MFO 320478 for payment."  # a `normal` hit (no checksum)


def _err(response: Any) -> dict[str, Any]:
    body: dict[str, Any] = response.json()
    return body


# --- 200: masked documents pass -------------------------------------------------------


@pytest.mark.parametrize("name", eligible_fixture_names())
def test_safety_corpus_file_masked_with_correct_placeholders_returns_200(
    make_client: Make, name: str
) -> None:
    client = make_client()
    payload, _pairs = build_masked(client, name)

    response = post_doc(client, payload)

    assert response.status_code == 200, (name, response.text[:200])
    assert response.json()["ok"] is True


@pytest.mark.parametrize("name", eligible_fixture_names()[:6])
def test_safety_masked_text_hides_every_original_value(make_client: Make, name: str) -> None:
    """Guards the test helper itself: the masked request has no original value."""
    client = make_client()
    payload, pairs = build_masked(client, name)
    joined = "\n".join(c["text"] for c in payload["clauses"])

    assert all(placeholder in joined for _orig, placeholder in pairs)
    assert not any(orig in joined for orig, _p in pairs if len(orig) > 6)


@pytest.mark.parametrize(
    "text",
    [
        "ЄДРПОУ [A.TAX_ID_1], рахунок [A.ACCOUNT_1], пошта [A.EMAIL_1].",
        "Seller [A.ORG_1], tel [A.PHONE_1], site [A.URL_1].",
        "Contact [A.PERSON_1] at [A.EMAIL_1]; [A.PERSON_2] signs.",
    ],
)
def test_safety_placeholders_hiding_high_precision_values_pass(
    make_client: Make, text: str
) -> None:
    client = make_client()

    response = post_doc(client, doc(detector_version(client), text))

    assert response.status_code == 200


def test_safety_neutralized_lookalike_brackets_are_ordinary_text(make_client: Make) -> None:
    client = make_client()
    text = "Pay ⟦A.ORG_7⟧ and ⟦A.NOPE_0⟧ within 30 days."

    response = post_doc(client, doc(detector_version(client), text))

    assert response.status_code == 200


def test_safety_neutralized_lookalike_does_not_count_for_numbering(make_client: Make) -> None:
    client = make_client()
    text = "Pay [A.ORG_1] and ⟦A.ORG_5⟧."

    response = post_doc(client, doc(detector_version(client), text))

    assert response.status_code == 200


def test_safety_repeated_placeholder_is_one_number(make_client: Make) -> None:
    client = make_client()
    text = "[A.ORG_1] pays [A.ORG_2]; later [A.ORG_1] again."

    assert post_doc(client, doc(detector_version(client), text)).status_code == 200


def test_safety_numbering_is_per_class_and_spans_clauses(make_client: Make) -> None:
    client = make_client()
    version = detector_version(client)

    ok = post_doc(client, doc(version, "[A.ORG_1] and [A.PERSON_1].", "[A.ORG_2] here."))
    gap = post_doc(client, doc(version, "[A.ORG_1] and [A.PERSON_1].", "[A.ORG_3] here."))

    assert ok.status_code == 200
    assert (gap.status_code, _err(gap)) == (422, {"error": "invalid_placeholder"})


def test_safety_label_b_document_with_label_b_placeholders_passes(make_client: Make) -> None:
    client = make_client()

    response = post_doc(client, doc(detector_version(client), "[B.ORG_1] pays.", label="B"))

    assert response.status_code == 200


# --- digest ---------------------------------------------------------------------------------


def test_safety_digest_is_stable_for_equal_input(make_client: Make) -> None:
    client = make_client()
    payload = doc(detector_version(client), "[A.ORG_1] pays within 30 days.", "Second clause.")

    first = post_doc(client, payload).json()["digest"]
    second = post_doc(client, payload).json()["digest"]

    assert first == second


def test_safety_digest_changes_with_text_label_and_clause_order(make_client: Make) -> None:
    client = make_client()
    v = detector_version(client)
    digests = {
        post_doc(client, doc(v, "One clause.", "Two clause.")).json()["digest"],
        post_doc(client, doc(v, "One clause.", "Two clauses.")).json()["digest"],
        post_doc(client, doc(v, "Two clause.", "One clause.")).json()["digest"],
        post_doc(client, doc(v, "One clause.", "Two clause.", label="B")).json()["digest"],
    }

    assert len(digests) == 4


# --- 409 ---------------------------------------------------------------------------------------


def test_safety_wrong_detector_version_returns_409(make_client: Make) -> None:
    client = make_client()

    response = post_doc(client, doc("not-the-version", "1. Payment is due."))

    assert (response.status_code, _err(response)) == (409, {"error": "detector_version_mismatch"})


def test_safety_version_mismatch_is_checked_before_every_other_check(make_client: Make) -> None:
    client = make_client()
    text = f"Pay [A.FOO_9] \u200b {EMAIL}"

    response = post_doc(client, doc("old-version", text))

    assert response.status_code == 409


# --- 422 input_not_clean ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "char",
    ["\u200b", "\u202e", "\ufeff", "\u2060", "\x00", "\u00ad", "\u200d"],
    ids=["zwsp", "rlo", "bom", "word-joiner", "nul", "soft-hyphen", "zwj"],
)
def test_safety_text_changed_by_layer_1_returns_input_not_clean(
    make_client: Make, char: str
) -> None:
    client = make_client()

    response = post_doc(client, doc(detector_version(client), f"Payment{char} is due."))

    assert (response.status_code, _err(response)) == (422, {"error": "input_not_clean"})


def test_safety_not_clean_is_checked_before_placeholder_grammar(make_client: Make) -> None:
    client = make_client()
    text = "Pay [A.FOO_9] \u200b now."

    response = post_doc(client, doc(detector_version(client), text))

    assert _err(response) == {"error": "input_not_clean"}


def test_safety_not_clean_is_checked_before_unmasked_identifier(make_client: Make) -> None:
    client = make_client()

    response = post_doc(client, doc(detector_version(client), f"Mail \u200b {EMAIL}"))

    assert _err(response) == {"error": "input_not_clean"}


# --- 422 invalid_placeholder ---------------------------------------------------------------------------


INVALID_PLACEHOLDERS = [
    pytest.param("Pay [B.ORG_1].", id="wrong-label"),
    pytest.param("Pay [A.FOO_1].", id="unknown-class"),
    pytest.param("Pay [A.org_1].", id="lowercase-class"),
    pytest.param("Pay [A.ORG_0].", id="n-zero"),
    pytest.param("Pay [A.ORG_01].", id="n-leading-zero"),
    pytest.param("Pay [A.ORG_5001].", id="n-above-5000"),
    pytest.param("Pay [A.ORG_-1].", id="n-negative"),
    pytest.param("Pay [A.ORG_].", id="n-missing"),
    pytest.param("Pay [ORG_1].", id="no-label"),
    pytest.param("Pay [A.ORG1].", id="no-underscore"),
    pytest.param("Pay [A.ORG_2].", id="starts-at-2"),
    pytest.param("Pay [A.ORG_1] and [A.ORG_3].", id="gap-in-numbering"),
    pytest.param("Pay [A.ORG_1] and [A.PERSON_2].", id="gap-in-second-class"),
    pytest.param("Pay [А.ORG_1].", id="cyrillic-A-in-label"),
    pytest.param("Pay [A.ОRG_1].", id="cyrillic-O-in-class"),
    pytest.param("Pay [A.ORG_l].", id="letter-l-for-digit-1"),
    pytest.param("Pay [A.ORG_１].", id="fullwidth-digit"),
    pytest.param("Pay [A.ΟRG_1].", id="greek-omicron-in-class"),
    pytest.param("Pay [A.ORG_1] and [Α.PERSON_1].", id="greek-alpha-label-second"),
]


@pytest.mark.parametrize("text", INVALID_PLACEHOLDERS)
def test_safety_invalid_placeholder_returns_422(make_client: Make, text: str) -> None:
    client = make_client()

    response = post_doc(client, doc(detector_version(client), text))

    assert (response.status_code, _err(response)) == (422, {"error": "invalid_placeholder"})


def test_safety_gap_found_across_clauses(make_client: Make) -> None:
    client = make_client()

    response = post_doc(client, doc(detector_version(client), "Pay [A.ORG_1].", "Then [A.ORG_3]."))

    assert _err(response) == {"error": "invalid_placeholder"}


def test_safety_label_must_equal_document_label(make_client: Make) -> None:
    client = make_client()

    response = post_doc(client, doc(detector_version(client), "[A.ORG_1] pays.", label="B"))

    assert _err(response) == {"error": "invalid_placeholder"}


def test_safety_invalid_placeholder_is_checked_before_unmasked_identifier(
    make_client: Make,
) -> None:
    client = make_client()
    text = f"Pay [A.FOO_1] to {EMAIL}."

    response = post_doc(client, doc(detector_version(client), text))

    assert _err(response) == {"error": "invalid_placeholder"}


# --- 422 unmasked_identifier -------------------------------------------------------------------------------


def _unmasked(response: Any) -> list[list[Any]]:
    assert response.status_code == 422, response.text[:200]
    body = response.json()
    assert set(body) == {"error", "spans"}
    assert body["error"] == "unmasked_identifier"
    spans: list[list[Any]] = body["spans"]
    return spans


def test_safety_leftover_email_returns_span_of_the_email(make_client: Make) -> None:
    client = make_client()
    text = f"Write to {EMAIL} about the contract."

    spans = _unmasked(post_doc(client, doc(detector_version(client), text)))

    assert [s[0] for s in spans] == ["c1"]
    assert text[spans[0][1] : spans[0][2]] == EMAIL


def test_safety_leftover_checksummed_code_is_found(make_client: Make) -> None:
    client = make_client()
    text = f"Seller code ЄДРПОУ {EDRPOU} is stated here."

    spans = _unmasked(post_doc(client, doc(detector_version(client), text)))

    assert any(EDRPOU in text[s[1] : s[2]] for s in spans)


def test_safety_leftover_iban_is_found(make_client: Make) -> None:
    client = make_client()
    text = f"Pay to IBAN {IBAN} within 5 days."

    spans = _unmasked(post_doc(client, doc(detector_version(client), text)))

    assert any(IBAN in text[s[1] : s[2]] for s in spans)


def test_safety_leftover_company_name_is_found(make_client: Make) -> None:
    client = make_client()
    text = "The Supplier is ТОВ «Альфа Захист» and pays on time."

    spans = _unmasked(post_doc(client, doc(detector_version(client), text)))

    assert any("Альфа Захист" in text[s[1] : s[2]] for s in spans)


def test_safety_unmasked_spans_are_relative_to_their_own_clause(make_client: Make) -> None:
    client = make_client()
    first = "1. Payment is due within 30 days after the invoice, as agreed."
    second = f"2. Write to {EMAIL} please."
    third = f"3. Or to {EMAIL.replace('ivan', 'olga')} please."

    spans = _unmasked(post_doc(client, doc(detector_version(client), first, second, third)))

    by_clause = {s[0]: s for s in spans}
    assert set(by_clause) == {"c2", "c3"}
    assert second[by_clause["c2"][1] : by_clause["c2"][2]] == EMAIL
    assert third[by_clause["c3"][1] : by_clause["c3"][2]] == EMAIL.replace("ivan", "olga")


def test_safety_unmasked_spans_match_the_detector_on_the_same_text(make_client: Make) -> None:
    client = make_client()
    text = f"Write to {EMAIL} or call +380 44 123 45 67 now."
    expected = {(s, e) for s, e, _c, p in hit_spans(client, text) if p == "high"}

    spans = _unmasked(post_doc(client, doc(detector_version(client), text)))

    assert expected
    assert {(s[1], s[2]) for s in spans} >= expected


def test_safety_unmasked_spans_are_sorted_triples_with_ints(make_client: Make) -> None:
    client = make_client()
    text = f"A {EMAIL}, B {EMAIL.replace('ivan', 'petro')}, C {EMAIL.replace('ivan', 'anna')}."

    spans = _unmasked(post_doc(client, doc(detector_version(client), text)))

    assert len(spans) >= 3
    assert all(len(s) == 3 and isinstance(s[1], int) and isinstance(s[2], int) for s in spans)
    assert spans == sorted(spans)


def test_safety_unmasked_error_body_holds_no_text(make_client: Make) -> None:
    client = make_client()
    response = post_doc(client, doc(detector_version(client), f"Write to {EMAIL} now."))

    assert response.status_code == 422
    assert EMAIL not in response.text
    assert "example.com" not in response.text
    assert "Write" not in response.text


def test_safety_placeholder_next_to_leftover_still_reports_only_the_leftover(
    make_client: Make,
) -> None:
    client = make_client()
    text = f"[A.ORG_1] writes to {EMAIL} and to [A.EMAIL_1]."

    spans = _unmasked(post_doc(client, doc(detector_version(client), text)))

    assert [text[s[1] : s[2]] for s in spans] == [EMAIL]


# --- acknowledged_unmasked ---------------------------------------------------------------------------------------


def _normal_hit(client: TestClient) -> tuple[int, int]:
    hits = [h for h in hit_spans(client, MFO_TEXT) if h[3] == "normal"]
    assert len(hits) == 1, hits
    return hits[0][0], hits[0][1]


def test_safety_normal_hit_without_acknowledgement_returns_unmasked_identifier(
    make_client: Make,
) -> None:
    client = make_client()
    start, end = _normal_hit(client)

    spans = _unmasked(post_doc(client, doc(detector_version(client), MFO_TEXT)))

    assert ["c1", start, end] in spans


def test_safety_normal_hit_with_exact_acknowledged_span_returns_200(make_client: Make) -> None:
    client = make_client()
    start, end = _normal_hit(client)

    response = post_doc(client, doc(detector_version(client), MFO_TEXT, ack=[["c1", start, end]]))

    assert response.status_code == 200


def test_safety_acknowledged_span_is_clause_relative(make_client: Make) -> None:
    client = make_client()
    start, end = _normal_hit(client)
    version = detector_version(client)

    right = post_doc(client, doc(version, "First clause.", MFO_TEXT, ack=[["c2", start, end]]))
    wrong = post_doc(client, doc(version, "First clause.", MFO_TEXT, ack=[["c1", start, end]]))

    assert right.status_code == 200
    assert (wrong.status_code, _err(wrong)) == (422, {"error": "invalid_request"})


@pytest.mark.parametrize(
    "shift",
    [(-1, 0), (0, 1), (-1, 1), (1, 0), (0, -1)],
    ids=["wider-left", "wider-right", "wider-both", "narrower-left", "narrower-right"],
)
def test_safety_acknowledged_span_not_equal_to_a_hit_returns_invalid_request(
    make_client: Make, shift: tuple[int, int]
) -> None:
    client = make_client()
    start, end = _normal_hit(client)

    response = post_doc(
        client,
        doc(detector_version(client), MFO_TEXT, ack=[["c1", start + shift[0], end + shift[1]]]),
    )

    assert (response.status_code, _err(response)) == (422, {"error": "invalid_request"})


def test_safety_acknowledged_span_that_hits_nothing_returns_invalid_request(
    make_client: Make,
) -> None:
    client = make_client()

    response = post_doc(client, doc(detector_version(client), MFO_TEXT, ack=[["c1", 0, 4]]))

    assert (response.status_code, _err(response)) == (422, {"error": "invalid_request"})


def test_safety_acknowledged_high_precision_hit_is_refused(make_client: Make) -> None:
    client = make_client()
    text = f"Write to {EMAIL} about the contract."
    start = text.index(EMAIL)

    response = post_doc(
        client, doc(detector_version(client), text, ack=[["c1", start, start + len(EMAIL)]])
    )

    spans = _unmasked(response)
    assert ["c1", start, start + len(EMAIL)] in spans


def test_safety_acknowledged_checksummed_code_is_refused(make_client: Make) -> None:
    client = make_client()
    text = f"Seller code ЄДРПОУ {EDRPOU} is stated here."
    hits = [h for h in hit_spans(client, text) if EDRPOU in text[h[0] : h[1]]]
    assert hits

    response = post_doc(
        client, doc(detector_version(client), text, ack=[["c1", hits[0][0], hits[0][1]]])
    )

    assert response.status_code == 422
    assert _err(response)["error"] == "unmasked_identifier"


def _two_normal_hits() -> tuple[str, str]:
    return MFO_TEXT, "Second: MFO 305299 here."


def test_safety_two_normal_hits_acknowledged_in_order_return_200(make_client: Make) -> None:
    client = make_client()
    first, second = _two_normal_hits()
    a = _normal_hit(client)
    b = [h for h in hit_spans(client, second) if h[3] == "normal"][0]

    response = post_doc(
        client,
        doc(detector_version(client), first, second, ack=[["c1", *a], ["c2", b[0], b[1]]]),
    )

    assert response.status_code == 200


def test_safety_acknowledged_list_not_sorted_returns_invalid_request(make_client: Make) -> None:
    client = make_client()
    first, second = _two_normal_hits()
    a = _normal_hit(client)
    b = [h for h in hit_spans(client, second) if h[3] == "normal"][0]

    response = post_doc(
        client,
        doc(detector_version(client), first, second, ack=[["c2", b[0], b[1]], ["c1", *a]]),
    )

    assert (response.status_code, _err(response)) == (422, {"error": "invalid_request"})


def test_safety_acknowledged_duplicate_span_returns_invalid_request(make_client: Make) -> None:
    client = make_client()
    start, end = _normal_hit(client)

    response = post_doc(
        client,
        doc(detector_version(client), MFO_TEXT, ack=[["c1", start, end], ["c1", start, end]]),
    )

    assert (response.status_code, _err(response)) == (422, {"error": "invalid_request"})


def test_safety_acknowledged_overlapping_spans_return_invalid_request(make_client: Make) -> None:
    client = make_client()
    start, end = _normal_hit(client)

    response = post_doc(
        client,
        doc(
            detector_version(client), MFO_TEXT, ack=[["c1", start, end], ["c1", start + 2, end + 3]]
        ),
    )

    assert (response.status_code, _err(response)) == (422, {"error": "invalid_request"})


def test_safety_acknowledged_unknown_clause_returns_invalid_request(make_client: Make) -> None:
    client = make_client()
    start, end = _normal_hit(client)

    response = post_doc(client, doc(detector_version(client), MFO_TEXT, ack=[["c7", start, end]]))

    assert (response.status_code, _err(response)) == (422, {"error": "invalid_request"})


def test_safety_acknowledged_beyond_text_returns_invalid_request(make_client: Make) -> None:
    client = make_client()

    response = post_doc(client, doc(detector_version(client), "Short.", ack=[["c1", 0, 10_000]]))

    assert (response.status_code, _err(response)) == (422, {"error": "invalid_request"})


def test_safety_more_than_50000_acknowledged_spans_return_invalid_request(
    make_client: Make,
) -> None:
    client = make_client()
    ack = [["c1", i, i + 1] for i in range(50_001)]

    response = post_doc(client, doc(detector_version(client), "x" * 50_100, ack=ack))

    assert (response.status_code, _err(response)) == (422, {"error": "invalid_request"})


def test_safety_acknowledged_spans_with_placeholder_inside_are_not_exempt(
    make_client: Make,
) -> None:
    client = make_client()
    text = "Bank [A.ACCOUNT_1], MFO 320478 for payment."
    plain = text.replace("[A.ACCOUNT_1]", "x" * len("[A.ACCOUNT_1]"))
    hits = [
        h for h in hit_spans(client, plain) if h[3] == "normal" and "320478" in plain[h[0] : h[1]]
    ]
    assert hits
    version = detector_version(client)

    missing = post_doc(client, doc(version, text))
    given = post_doc(client, doc(version, text, ack=[["c1", hits[0][0], hits[0][1]]]))

    assert missing.status_code == 422
    assert given.status_code == 200


# --- caps for masked input ----------------------------------------------------------------------------------------------

_FILLER = "Payment is due within thirty days after the invoice. "


def _filler(n: int) -> str:
    return (_FILLER * (n // len(_FILLER) + 1))[:n].rstrip() + "."


def test_safety_clause_at_40000_chars_is_accepted(make_client: Make) -> None:
    client = make_client()
    text = _filler(40_000)
    assert len(text) == 40_000

    response = post_doc(client, doc(detector_version(client), text))

    assert response.status_code == 200


def test_safety_clause_above_40000_chars_returns_422_too_much_text(make_client: Make) -> None:
    client = make_client()
    text = _filler(40_001)
    assert len(text) == 40_001

    response = post_doc(client, doc(detector_version(client), text))

    assert (response.status_code, _err(response)) == (422, {"error": "too_much_text"})


def test_safety_document_at_2_000_000_chars_is_accepted(make_client: Make) -> None:
    client = make_client()
    texts = [_filler(40_000) for _ in range(50)]

    response = post_doc(client, doc(detector_version(client), *texts))

    assert response.status_code == 200


def test_safety_document_above_2_000_000_chars_returns_422_too_much_text(
    make_client: Make,
) -> None:
    client = make_client()
    texts = [_filler(40_000) for _ in range(50)] + ["x."]

    response = post_doc(client, doc(detector_version(client), *texts))

    assert (response.status_code, _err(response)) == (422, {"error": "too_much_text"})


def test_safety_more_than_2000_clauses_return_422_too_much_text(make_client: Make) -> None:
    client = make_client()
    texts = [f"Clause {i}." for i in range(2_001)]

    response = post_doc(client, doc(detector_version(client), *texts))

    assert (response.status_code, _err(response)) == (422, {"error": "too_much_text"})


def test_safety_2000_clauses_are_accepted(make_client: Make) -> None:
    client = make_client()
    texts = [f"Clause {i}." for i in range(2_000)]

    assert post_doc(client, doc(detector_version(client), *texts)).status_code == 200


def test_safety_check_route_is_post_only(make_client: Make) -> None:
    client = make_client()

    assert client.get(SAFETY).status_code in (404, 405)
    assert client.post(SAFETY, content=b"{}", headers=JSON_HEADERS).status_code == 422
