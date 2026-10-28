# ruff: noqa: RUF001, E501
"""S5b-T2 review findings (PR #60): partial values next to placeholders, checksum codes
that cannot be acknowledged, gate subclassing, performance, full-width brackets,
check order. Values are generated in code; everything is synthetic.

Expected to fail until the review fixes are implemented.
"""

from __future__ import annotations

import ast
import importlib
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.pseudo_helpers import CARD, EDRPOU, IBAN, RNOKPP
from tests.safety_helpers import detector_version, doc, hit_spans, post_doc
from tests.test_safety_policy import APP_DIR, GATE_TYPES, _py_files

Make = Callable[..., TestClient]
FULL_IBAN_TAIL = IBAN[-15:]


def _unmasked(response: Any) -> list[list[Any]]:
    assert response.status_code == 422, response.text[:200]
    body = response.json()
    assert body["error"] == "unmasked_identifier", body
    spans: list[list[Any]] = body["spans"]
    return spans


def _overlaps(spans: list[list[Any]], piece: tuple[int, int]) -> bool:
    return any(s[0] == "c1" and s[1] < piece[1] and piece[0] < s[2] for s in spans)


def _case(text: str, *leftovers: str) -> tuple[str, list[tuple[int, int]]]:
    pieces = []
    for left in leftovers:
        start = text.index(left)
        pieces.append((start, start + len(left)))
    return text, pieces


PARTIALS = {
    "iban-tail-15-digits": _case(f"IBAN: [A.ACCOUNT_1]{FULL_IBAN_TAIL}", FULL_IBAN_TAIL),
    "iban-head-14-chars": _case(f"{IBAN[:14]}[A.ACCOUNT_1]", IBAN[:14]),
    "iban-spaced-around-placeholder": _case(
        "UA21 3223 [A.ACCOUNT_1] 2600 7233 5660 01", "UA21 3223", "2600 7233 5660 01"
    ),
    "edrpou-4-digits": _case(f"ЄДРПОУ: [A.TAX_ID_1]{EDRPOU[:4]}", EDRPOU[:4]),
    "card-12-digits": _case(f"{CARD[:12]}[A.ACCOUNT_1]", CARD[:12]),
    "phone-head": _case("+380 50 [A.PHONE_1]", "+380 50"),
    "phone-tail": _case("[A.PHONE_1] 123 45 67", "123 45 67"),
    "email-local-part": _case("ivan.petrenko@[A.URL_1]", "ivan.petrenko"),
    "plate-letters": _case("ВН [A.VEHICLE_1] АХ", "ВН", "АХ"),
}


@pytest.mark.parametrize("name", sorted(PARTIALS))
def test_safety_partial_value_next_to_placeholder_returns_unmasked_identifier(
    make_client: Make, name: str
) -> None:
    client = make_client()
    text, pieces = PARTIALS[name]

    spans = _unmasked(post_doc(client, doc(detector_version(client), text)))

    assert all(_overlaps(spans, piece) for piece in pieces), (spans, pieces)


def test_safety_partial_value_error_body_holds_no_text(make_client: Make) -> None:
    client = make_client()
    text, _pieces = PARTIALS["iban-tail-15-digits"]

    response = post_doc(client, doc(detector_version(client), text))

    assert FULL_IBAN_TAIL not in response.text


def test_safety_obligation_with_amount_and_term_next_to_placeholder_passes(
    make_client: Make,
) -> None:
    client = make_client()

    response = post_doc(
        client, doc(detector_version(client), "[A.ORG_1] сплачує 1000 грн протягом 10 днів")
    )

    assert response.status_code == 200


# --- checksum codes cannot be acknowledged -------------------------------------------------------


@pytest.mark.parametrize("code", [EDRPOU, RNOKPP], ids=["edrpou", "rnokpp"])
def test_safety_checksum_code_without_keyword_cannot_be_acknowledged(
    make_client: Make, code: str
) -> None:
    client = make_client()
    text = f"The value {code} was agreed for accounting."
    hits = [h for h in hit_spans(client, text) if code in text[h[0] : h[1]]]
    start, end = (
        (hits[0][0], hits[0][1]) if hits else (text.index(code), text.index(code) + len(code))
    )

    response = post_doc(client, doc(detector_version(client), text, ack=[["c1", start, end]]))

    assert response.status_code == 422
    assert response.json()["error"] in {"unmasked_identifier", "invalid_request"}


@pytest.mark.parametrize("code", [EDRPOU, RNOKPP], ids=["edrpou", "rnokpp"])
def test_safety_checksum_code_without_keyword_and_without_acknowledgement_is_refused(
    make_client: Make, code: str
) -> None:
    client = make_client()
    text = f"The value {code} was agreed for accounting."

    spans = _unmasked(post_doc(client, doc(detector_version(client), text)))

    assert any(text[s[1] : s[2]].find(code) >= 0 for s in spans)


# --- gate subclassing -------------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(GATE_TYPES))
def test_gate_subclassing_a_gate_type_fails_at_class_creation(name: str) -> None:
    gate: Any = importlib.import_module("app.pseudo.gate")
    base = getattr(gate, name)

    with pytest.raises(Exception):  # noqa: B017, PT011

        class Sub(base):  # type: ignore[misc,valid-type]
            pass


def subclass_problems(root: Path) -> list[str]:
    problems: list[str] = []
    for path in _py_files(root):
        if path.name == "gate.py" and path.parent.name == "pseudo":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    leaf = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
                    if leaf in GATE_TYPES or any(
                        isinstance(sub, ast.Name) and sub.id in GATE_TYPES for sub in ast.walk(base)
                    ):
                        problems.append(f"{path.name}:{node.lineno}: {node.name}")
    return problems


def test_policy_no_class_with_a_gate_type_as_base_outside_gate_py() -> None:
    assert subclass_problems(APP_DIR) == []


@pytest.mark.parametrize(
    "base", ["PseudonymizedText", "g.PseudonymizedDocument", "Generic[PseudonymizedText]"]
)
def test_policy_subclass_checker_flags_planted_module(tmp_path: Path, base: str) -> None:
    target = tmp_path / "app" / "ai" / "bad.py"
    target.parent.mkdir(parents=True)
    target.write_text(f"class Bad({base}):\n    pass\n", encoding="utf-8")

    assert subclass_problems(tmp_path / "app") != []


def test_policy_subclass_checker_accepts_unrelated_class(tmp_path: Path) -> None:
    target = tmp_path / "app" / "ok.py"
    target.parent.mkdir(parents=True)
    target.write_text("class Fine(dict):\n    pass\n", encoding="utf-8")

    assert subclass_problems(tmp_path / "app") == []


# --- performance ------------------------------------------------------------------------------------------


def test_safety_twenty_big_clauses_of_placeholder_and_email_finish_under_3_seconds(
    make_client: Make,
) -> None:
    client = make_client()
    unit = "[A.ORG_1] a@b.ua "
    clause = unit * (40_000 // len(unit))
    assert len(clause) <= 40_000
    payload = doc(detector_version(client), *[clause] * 20)

    start = time.monotonic()
    response = post_doc(client, payload)
    elapsed = time.monotonic() - start

    assert response.status_code in (200, 422)
    assert response.status_code < 500
    assert elapsed < 3.0, elapsed


# --- full-width brackets -------------------------------------------------------------------------------------


def test_safety_fullwidth_bracket_placeholder_returns_invalid_placeholder(
    make_client: Make,
) -> None:
    client = make_client()

    response = post_doc(client, doc(detector_version(client), "Pay ［A.ORG_1］ now."))

    assert (response.status_code, response.json()) == (422, {"error": "invalid_placeholder"})


# --- check order and duplicates -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ack",
    [[["c9", 5, 1]], [["c1", 2, 1]], [["c1", 0, 1], ["c1", 0, 1]]],
    ids=["unknown-clause", "end-before-start", "duplicate"],
)
def test_safety_wrong_version_is_checked_before_acknowledged_list_structure(
    make_client: Make, ack: list[list[Any]]
) -> None:
    client = make_client()

    response = post_doc(client, doc("old-version", "1. Pay.", ack=ack))

    assert (response.status_code, response.json()) == (409, {"error": "detector_version_mismatch"})


def test_safety_unmasked_identifier_spans_have_no_duplicates(make_client: Make) -> None:
    client = make_client()
    text = (
        "Write to ivan.testov@example.com or visit https://shop.example.org/a now. "
        f"Pay IBAN {IBAN} to ФОП Іваненко Іван Петрович, тел. +380 44 123 45 67."
    )

    spans = _unmasked(post_doc(client, doc(detector_version(client), text)))

    keys = [tuple(s) for s in spans]
    assert len(keys) == len(set(keys))
    assert len(keys) >= 3
