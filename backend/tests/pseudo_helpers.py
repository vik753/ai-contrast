# ruff: noqa: PT018
"""Helpers for the S5b-T1 detector tests: reply reading and checksum-valid
synthetic values. Everything goes through ``POST /api/segment``.

All numbers are generated with the public algorithms (ЄДРПОУ, РНОКПП, IBAN
mod 97, Luhn); they are fictional and never real personal data.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from typing import Any

from fastapi.testclient import TestClient

from tests.segment_helpers import block, post_blocks

Block = dict[str, Any]
Entity = dict[str, Any]
REQUISITES_HEADING = "Реквізити та підписи сторін"


# ---------------------------------------------------------------- checksums


def edrpou(seven: str) -> str:
    """8-digit ЄДРПОУ from the first seven digits."""
    assert len(seven) == 7 and seven.isdigit()
    digits = [int(c) for c in seven]
    mid = 30_000_000 <= int(seven + "0") < 60_000_000
    w1 = [7, 1, 2, 3, 4, 5, 6] if mid else [1, 2, 3, 4, 5, 6, 7]
    w2 = [9, 3, 4, 5, 6, 7, 8] if mid else [3, 4, 5, 6, 7, 8, 9]
    check = sum(d * w for d, w in zip(digits, w1, strict=True)) % 11
    if check == 10:
        check = sum(d * w for d, w in zip(digits, w2, strict=True)) % 11
        if check == 10:
            check = 0
    return seven + str(check)


def edrpou_valid(value: str) -> bool:
    return len(value) == 8 and value.isdigit() and edrpou(value[:7]) == value


def rnokpp(nine: str) -> str:
    """10-digit РНОКПП from the first nine digits."""
    assert len(nine) == 9 and nine.isdigit()
    weights = [-1, 5, 7, 9, 4, 6, 10, 5, 7]
    total = sum(int(d) * w for d, w in zip(nine, weights, strict=True))
    return nine + str(total % 11 % 10)


def iban_ua(mfo: str, account: str) -> str:
    """29-character UA IBAN with a correct mod 97 check."""
    assert len(mfo) == 6 and len(account) == 19
    bban = mfo + account
    rearranged = bban + "3010" + "00"  # U=30, A=10, check digits 00
    check = 98 - int(rearranged) % 97
    return f"UA{check:02d}{bban}"


def luhn_card(fifteen: str) -> str:
    assert len(fifteen) == 15 and fifteen.isdigit()
    total = 0
    for i, ch in enumerate(reversed(fifteen)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return fifteen + str((10 - total % 10) % 10)


def break_edrpou(value: str) -> str:
    msg = "no invalid variant"
    for d in "0123456789":
        cand = value[:7] + d
        if cand != value and not edrpou_valid(cand):
            return cand
    raise AssertionError(msg)


EDRPOU = edrpou("3200012")
RNOKPP = rnokpp("284561234")
IBAN = iban_ua("305299", "0000000026007233456")
IBAN_SPACED = " ".join(IBAN[i : i + 4] for i in range(0, len(IBAN), 4))
CARD = luhn_card("400000123456789")
CARD_SPACED = " ".join(CARD[i : i + 4] for i in range(0, 16, 4))


# ------------------------------------------------------------------ calling


def detect(client: TestClient, *texts: str, part: str = "body") -> dict[str, Any]:
    response = post_blocks(client, [block(t, part=part) for t in texts])
    assert response.status_code == 200, response.text[:200]
    data: dict[str, Any] = response.json()
    return data


def detect_blocks(client: TestClient, blocks: Sequence[Block]) -> dict[str, Any]:
    response = post_blocks(client, blocks)
    assert response.status_code == 200, response.text[:200]
    data: dict[str, Any] = response.json()
    return data


def span_text(data: dict[str, Any], span: Sequence[int]) -> str:
    i, s, e = span
    text: str = data["blocks"][i]["text"][s:e]
    return text


def entity_strings(data: dict[str, Any], entity: Entity) -> list[str]:
    return [span_text(data, sp) for sp in entity["spans"]]


def entities_of(data: dict[str, Any], *classes: str) -> list[Entity]:
    found: list[Entity] = [e for e in data["entities"] if not classes or e["class"] in classes]
    return found


def covering(data: dict[str, Any], fragment: str, classes: Collection[str]) -> list[Entity]:
    """Entities of the given classes with a span that fully contains ``fragment``."""
    return [
        e
        for e in data["entities"]
        if e["class"] in classes and any(fragment in s for s in entity_strings(data, e))
    ]


def all_masked_text(data: dict[str, Any]) -> str:
    return "\n".join(s for e in data["entities"] for s in entity_strings(data, e))


def clause_warning_codes(data: dict[str, Any]) -> list[str]:
    return sorted(w["code"] for w in data["warnings"])


def requisites_doc(*lines: str) -> list[Block]:
    """A short contract whose last section is the requisites section; one block per line."""
    return [
        block("1. The parties agree."),
        block(REQUISITES_HEADING),
        *[block(line) for line in lines],
    ]


def requisite_actions(data: dict[str, Any]) -> dict[str, str]:
    """Map line text -> action over all requisites clauses."""
    result: dict[str, str] = {}
    for item in data["requisites"]:
        for line in item["lines"]:
            result[span_text(data, line["span"]).strip()] = line["action"]
    return result
