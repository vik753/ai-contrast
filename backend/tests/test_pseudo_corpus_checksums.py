"""One-time corpus check (S5b-T0 and held-out READMEs): recompute every checksum.

Covers the main corpus (``tests/fixtures/pseudo/``) and the held-out split
(``eval/pseudo/heldout/``). The validators here are written from the public algorithms
and do not use ``app.pseudo.checksums``, so a wrong detector algorithm cannot hide a
wrong fixture.

1. Every value in the README checksum tables passes its algorithm; a value marked
   "invalid on purpose" passes none.
2. Every ``high`` TAX_ID and ACCOUNT entity (codes with context, IBAN, card) passes at
   least one algorithm in every ASCII value form. Non-ASCII forms are skipped; in the
   VARIANTS files a Latin look-alike of zero is folded back first. Every entity needs
   at least one checked form.

Held-out failures report the reason only, never a value or a file name.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

BACKEND = Path(__file__).resolve().parents[1]
CORPORA = {
    "main": BACKEND / "tests" / "fixtures" / "pseudo",
    "heldout": BACKEND / "eval" / "pseudo" / "heldout",
}


def _w(digits: str, weights: tuple[int, ...]) -> int:
    return sum(int(d) * w for d, w in zip(digits, weights, strict=False))


def _edrpou(v: str) -> bool:
    if len(v) != 8:
        return False
    mid = 30_000_000 <= int(v) < 60_000_000
    first = (7, 1, 2, 3, 4, 5, 6) if mid else (1, 2, 3, 4, 5, 6, 7)
    second = (9, 3, 4, 5, 6, 7, 8) if mid else (3, 4, 5, 6, 7, 8, 9)
    check = _w(v, first) % 11
    if check == 10:
        check = _w(v, second) % 11 % 10
    return check == int(v[7])


def _okpo(v: str) -> bool:
    if len(v) != 8:
        return False
    check = _w(v, (1, 2, 3, 4, 5, 6, 7)) % 11
    if check == 10:
        check = _w(v, (3, 4, 5, 6, 7, 8, 9)) % 11 % 10
    return check == int(v[7])


def _rnokpp(v: str) -> bool:
    return len(v) == 10 and _w(v, (-1, 5, 7, 9, 4, 6, 10, 5, 7)) % 11 % 10 == int(v[9])


def _inn10(v: str) -> bool:
    return len(v) == 10 and _w(v, (2, 4, 10, 3, 5, 9, 4, 6, 8)) % 11 % 10 == int(v[9])


def _inn12(v: str) -> bool:
    if len(v) != 12:
        return False
    n11 = _w(v, (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)) % 11 % 10
    n12 = _w(v, (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)) % 11 % 10
    return (n11, n12) == (int(v[10]), int(v[11]))


def _ogrn(v: str) -> bool:
    return len(v) == 13 and int(v[:12]) % 11 % 10 == int(v[12])


def _ogrnip(v: str) -> bool:
    return len(v) == 15 and int(v[:14]) % 13 % 10 == int(v[14])


def _snils(v: str) -> bool:
    if len(v) != 11:
        return False
    total = _w(v, (9, 8, 7, 6, 5, 4, 3, 2, 1))
    check = total if total < 100 else (0 if total in {100, 101} else total % 101)
    return (0 if check == 100 else check) == int(v[9:])


def _luhn(v: str) -> bool:
    if not 13 <= len(v) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(v)):
        n = int(d) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


DIGIT_CHECKS: tuple[Callable[[str], bool], ...] = (
    _edrpou,
    _okpo,
    _rnokpp,
    _inn10,
    _inn12,
    _ogrn,
    _ogrnip,
    _snils,
    _luhn,
)


def _iban(v: str) -> bool:
    if not re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}", v):
        return False
    moved = v[4:] + v[:4]
    return int("".join(str(int(c, 36)) for c in moved)) % 97 == 1


def checksum_valid(value: str) -> bool:
    compact = re.sub(r"[\s\-]", "", value)
    if compact.isdigit():
        return any(check(compact) for check in DIGIT_CHECKS)
    return _iban(compact.upper())


def _fold(value: str) -> str:
    """Latin capital O back to zero after the country code (VARIANTS homoglyph forms)."""
    return value[:2] + value[2:].replace("O", "0")


def _readme_rows(directory: Path) -> list[tuple[str, bool]]:
    """(value, valid expected) from every table whose header is ``Value | Kind | Algorithm``."""
    rows: list[tuple[str, bool]] = []
    in_table = False
    for line in (directory / "README.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("| Value | Kind | Algorithm"):
            in_table = True
            continue
        if not line.startswith("|"):
            in_table = False
            continue
        if not in_table or line.startswith("| ---"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        valid = "invalid on purpose" not in cells[1]
        rows.extend((value.strip(), valid) for value in cells[0].split(", "))
    return rows


def _fixtures(directory: Path) -> list[dict[str, Any]]:
    paths = sorted(p for p in directory.glob("*.json") if re.match(r"h?[0-9]{2}_", p.name))
    return [json.loads(p.read_text(encoding="utf-8")) for p in paths]


@pytest.mark.parametrize("split", sorted(CORPORA))
def test_readme_checksum_tables_recompute(split: str) -> None:
    rows = _readme_rows(CORPORA[split])
    assert len(rows) >= 15
    wrong = sum(checksum_valid(value) != valid for value, valid in rows)
    assert wrong == 0, f"{split}: {wrong} of {len(rows)} README checksum values do not recompute"


@pytest.mark.parametrize("split", sorted(CORPORA))
def test_high_tax_and_account_entities_pass_a_checksum(split: str) -> None:
    checked = wrong = unchecked_entities = 0
    for fixture in _fixtures(CORPORA[split]):
        variants = "VARIANTS" in fixture["description"]
        for entity in fixture["expected"]["entities"]:
            if entity["class"] not in {"TAX_ID", "ACCOUNT"} or entity["precision"] != "high":
                continue
            forms = [f for f in entity["value_forms"] if f.isascii()]
            # A VARIANTS file may write a code with a Latin look-alike (O for zero):
            # recompute it after folding the look-alike back to the digit.
            valid = [checksum_valid(_fold(f) if variants else f) for f in forms]
            unchecked_entities += not forms
            checked += len(forms)
            wrong += valid.count(False)
    assert checked >= 10
    assert (wrong, unchecked_entities) == (0, 0), (
        f"{split}: {wrong} invalid, {unchecked_entities} unchecked"
    )


def test_validators_reject_a_broken_check_digit() -> None:
    assert checksum_valid("21045679")
    assert not checksum_valid("21045678")
    assert checksum_valid("GB82 WEST 1234 5698 7654 32")
    assert not checksum_valid("GB83 WEST 1234 5698 7654 32")
    assert checksum_valid("4111 1111 1111 1111")
    assert not checksum_valid("4111 1111 1111 1112")
