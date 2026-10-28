"""Checksum validators (ADR 0008 point 1): ЄДРПОУ, РНОКПП, ИНН, ОГРН, СНИЛС, IBAN, Luhn.

Input is ASCII digits (and letters for IBAN) only; the callers fold digit look-alikes first.
"""

from __future__ import annotations

from typing import Final

_MOD11: Final = 11
_EDRPOU_MID_LOW: Final = 30_000_000
_EDRPOU_MID_HIGH: Final = 60_000_000
_IBAN_MOD: Final = 97
_LETTER_OFFSET: Final = 55  # "A" = 10
_SNILS_LIMIT: Final = 100
_SNILS_MIN_NUMBER: Final = 1_001_998
_RNOKPP_WEIGHTS: Final = (-1, 5, 7, 9, 4, 6, 10, 5, 7)
_INN10_WEIGHTS: Final = (2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_WEIGHTS_1: Final = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
_INN12_WEIGHTS_2: Final = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)


def _weighted(digits: str, weights: tuple[int, ...]) -> int:
    return sum(int(d) * w for d, w in zip(digits, weights, strict=False))


def edrpou_valid(value: str) -> bool:
    if len(value) != 8 or not value.isdigit():  # noqa: PLR2004
        return False
    number = int(value)
    mid = _EDRPOU_MID_LOW <= number < _EDRPOU_MID_HIGH
    first = (7, 1, 2, 3, 4, 5, 6) if mid else (1, 2, 3, 4, 5, 6, 7)
    second = (9, 3, 4, 5, 6, 7, 8) if mid else (3, 4, 5, 6, 7, 8, 9)
    check = _weighted(value[:7], first) % _MOD11
    if check == 10:  # noqa: PLR2004
        check = _weighted(value[:7], second) % _MOD11
        if check == 10:  # noqa: PLR2004
            check = 0
    return check == int(value[7])


def rnokpp_valid(value: str) -> bool:
    if len(value) != 10 or not value.isdigit():  # noqa: PLR2004
        return False
    return _weighted(value[:9], _RNOKPP_WEIGHTS) % _MOD11 % 10 == int(value[9])


def inn10_valid(value: str) -> bool:
    if len(value) != 10 or not value.isdigit():  # noqa: PLR2004
        return False
    return _weighted(value[:9], _INN10_WEIGHTS) % _MOD11 % 10 == int(value[9])


def inn12_valid(value: str) -> bool:
    if len(value) != 12 or not value.isdigit():  # noqa: PLR2004
        return False
    first = _weighted(value[:10], _INN12_WEIGHTS_1) % _MOD11 % 10
    second = _weighted(value[:11], _INN12_WEIGHTS_2) % _MOD11 % 10
    return first == int(value[10]) and second == int(value[11])


def ogrn_valid(value: str) -> bool:
    if len(value) != 13 or not value.isdigit():  # noqa: PLR2004
        return False
    return int(value[:12]) % _MOD11 % 10 == int(value[12])


def ogrnip_valid(value: str) -> bool:
    if len(value) != 15 or not value.isdigit():  # noqa: PLR2004
        return False
    return int(value[:14]) % 13 % 10 == int(value[14])


def snils_valid(value: str) -> bool:
    if len(value) != 11 or not value.isdigit():  # noqa: PLR2004
        return False
    if int(value[:9]) <= _SNILS_MIN_NUMBER:
        return True
    total = sum(int(d) * w for d, w in zip(value[:9], range(9, 0, -1), strict=True))
    if total >= _SNILS_LIMIT:
        total %= _SNILS_LIMIT + 1
        if total == _SNILS_LIMIT:
            total = 0
    return total == int(value[9:])


def luhn_valid(value: str) -> bool:
    if not value.isdigit() or not 13 <= len(value) <= 19:  # noqa: PLR2004
        return False
    total = 0
    for index, char in enumerate(reversed(value)):
        digit = int(char)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:  # noqa: PLR2004
                digit -= 9
        total += digit
    return total % 10 == 0


def iban_valid(value: str) -> bool:
    """ISO 13616 mod 97 on a compact upper-case IBAN."""
    if not 15 <= len(value) <= 34 or not value.isalnum() or not value.isascii():  # noqa: PLR2004
        return False
    rearranged = value[4:] + value[:4]
    number = "".join(str(ord(c) - _LETTER_OFFSET) if c.isalpha() else c for c in rearranged)
    return int(number) % _IBAN_MOD == 1
