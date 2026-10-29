"""Acknowledged container spans cover the non-high hits fully inside them."""

from __future__ import annotations

import importlib
import json
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.pseudo_helpers import RNOKPP
from tests.safety_helpers import detector_version, doc, find_untrusted_model, hit_spans, post_doc

Make = Callable[..., TestClient]
gate: Any = importlib.import_module("app.pseudo.gate")
SIGNATURE_TEXT = "____________ /Іваненко Іван Петрович/"
FOP_TEXT = f"ФОП Іваненко Іван Петрович, ІПН {RNOKPP}, тел. +380 44 123 45 67 уклали"


def _span(client: TestClient, text: str, cls: str) -> list[str | int]:
    start, end, _c, _p = next(h for h in hit_spans(client, text) if h[2] == cls)
    return ["c1", start, end]


def test_signature_with_inner_person_only_container_acknowledged_returns_200(
    make_client: Make,
) -> None:
    client = make_client()
    ack = [_span(client, SIGNATURE_TEXT, "SIGNATURE")]

    response = post_doc(client, doc(detector_version(client), SIGNATURE_TEXT, ack=ack))

    assert response.status_code == 200, response.text[:200]


def test_signature_with_inner_person_without_acknowledgement_is_refused(make_client: Make) -> None:
    client = make_client()

    response = post_doc(client, doc(detector_version(client), SIGNATURE_TEXT))

    assert response.status_code == 422
    assert response.json()["error"] == "unmasked_identifier"


def test_acknowledging_container_and_inner_person_is_invalid_request(make_client: Make) -> None:
    client = make_client()
    outer = _span(client, SIGNATURE_TEXT, "SIGNATURE")
    inner = _span(client, SIGNATURE_TEXT, "PERSON")

    response = post_doc(client, doc(detector_version(client), SIGNATURE_TEXT, ack=[outer, inner]))

    assert (response.status_code, response.json()) == (422, {"error": "invalid_request"})


def test_acknowledging_only_the_inner_person_leaves_the_container_unmasked(
    make_client: Make,
) -> None:
    client = make_client()
    inner = _span(client, SIGNATURE_TEXT, "PERSON")

    response = post_doc(client, doc(detector_version(client), SIGNATURE_TEXT, ack=[inner]))

    assert response.status_code == 422
    assert response.json()["error"] == "unmasked_identifier"


def test_acknowledged_container_does_not_cover_high_hits_next_to_it(make_client: Make) -> None:
    client = make_client()
    ack = [_span(client, FOP_TEXT, "ORG")]

    response = post_doc(client, doc(detector_version(client), FOP_TEXT, ack=ack))

    assert response.status_code == 422
    body = response.json()
    assert body["error"] == "unmasked_identifier"
    flagged = {FOP_TEXT[s[1] : s[2]] for s in body["spans"]}
    assert RNOKPP in flagged
    assert not any("Іваненко" in piece for piece in flagged)


def test_partial_overlap_with_container_is_still_invalid_request(make_client: Make) -> None:
    client = make_client()
    _c, start, end = _span(client, SIGNATURE_TEXT, "SIGNATURE")

    response = post_doc(
        client, doc(detector_version(client), SIGNATURE_TEXT, ack=[["c1", start, end - 1]])
    )

    assert (response.status_code, response.json()) == (422, {"error": "invalid_request"})


def test_high_hit_fully_inside_an_acknowledged_span_stays_refused(
    make_client: Make, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = make_client()
    text = "x" * 40
    found = [(0, 0, 30, False), (0, 5, 15, False), (0, 10, 20, True)]
    monkeypatch.setattr(
        gate, "_leftovers", lambda _t, _p: (found, {(b, s, e) for b, s, e, _h in found})
    )
    untrusted = find_untrusted_model().model_validate_json(
        json.dumps(doc(detector_version(client), text, ack=[["c1", 0, 30]]))
    )

    with pytest.raises(gate.SafetyError) as raised:
        gate.safety_pass(untrusted)

    assert raised.value.code == "unmasked_identifier"
    assert list(raised.value.spans) == [("c1", 10, 20)]
