# ruff: noqa: RUF001 - Cyrillic keywords in the reasons
"""Canaries the detector does not mask yet (S5b-T4), recorded instead of hidden.

Each entry becomes ``xfail(strict=True)`` with the reason below: when the detector gets
better, the test XPASSes, fails, and the entry must be removed. ``GLOBAL_LEAKS`` leak in
every cell where they are planted; ``CELL_LEAKS`` leak only in the named cell.

``SAFETY_NET`` says what ``POST /api/safety-check`` answers for a document that still
holds the canary (checked per canary, alone, as OCR blocks): ``422`` means the second detector
run refuses the document (fail closed); ``200`` means nothing stops it; ``None`` means the
canary is masked when alone and leaks only next to other names (context dependent).
"""

from __future__ import annotations

ONE_WORD = "known limit: one-word ORG without quotes, legal form or definition"
WRAP = (
    "entity or its keyword split by a line break inside a block (OCR soft wrap, PDF line "
    "wrap) is not detected"
)
RNOKPP_ADDRESS = (
    "known limit: РНОКПП split by a space, no keyword, on the line after an address "
    "(PDF line break)"
)

GLOBAL_LEAKS: dict[str, str] = {
    "uk-org-one-word": ONE_WORD,
    "en-org-one-word": ONE_WORD,
    "uk-person-common-word": "surnames that are common words (Коваль, Мельник) are not masked",
    "ru-person-ip": "RU sole proprietor 'индивидуальный предприниматель <name>' is not masked",
    "uk-person-line-end-hyphen": (
        "double surname with a real hyphen at a line end ('Левченко-\\nКравець') is not masked"
    ),
    "uk-tax-rnokpp-spaced-keyword": (
        "РНОКПП written with a space after the keyword is not found by /api/segment "
        "(the safety check finds it and refuses the document)"
    ),
    "en-health": "no English rule for health data ('diagnosed with ...')",
    "en-address": "no English rule for postal addresses",
    "en-personal-doc": "no English rule for passport number and date of birth",
    "en-vehicle": "no English rule for VIN and registration plate",
}

_OCR_WRAPPED = (
    "uk-person-double",
    "uk-person-vocative",
    "ru-person-double",
    "uk-org-bank",
    "uk-org-brand",
    "uk-org-defined-term",
    "en-org-ltd",
    "ru-tax-person",
    "uk-phone",
    "en-contacts",
    "uk-address",
    "ru-address",
    "uk-personal-doc",
    "ru-personal-doc",
    "en-doc-no",
    "uk-kep",
)

CELL_LEAKS: dict[tuple[str, str], dict[str, str]] = {
    ("ocr", "wrapped"): {
        **dict.fromkeys(_OCR_WRAPPED, WRAP),
        "uk-tax-rnokpp-spaced-after-address": RNOKPP_ADDRESS,
    },
    ("pdf", "preamble"): {
        "en-account": WRAP,
        "uk-vehicle": WRAP,
        "uk-tax-rnokpp-spaced-after-address": RNOKPP_ADDRESS,
    },
    ("pdf", "body"): {
        "en-account": WRAP,
        "uk-vehicle": WRAP,
        "uk-tax-rnokpp-spaced-after-address": RNOKPP_ADDRESS,
    },
    ("pdf", "heading"): {
        "en-account": WRAP,
        "uk-health": WRAP,
        "uk-doc-no": WRAP,
        "ru-vehicle": WRAP,
        "uk-tax-rnokpp-spaced-after-address": RNOKPP_ADDRESS,
    },
    ("pdf", "requisites-uk"): {
        "uk-vehicle": WRAP,
        "uk-tax-rnokpp-spaced-after-address": RNOKPP_ADDRESS,
    },
    ("pdf", "requisites-en"): {"en-account": WRAP},
}

SAFETY_NET: dict[str, int | None] = {
    "uk-org-one-word": 200,
    "en-org-one-word": 200,
    "uk-person-common-word": 200,
    "ru-person-ip": 200,
    "uk-person-line-end-hyphen": None,
    "uk-tax-rnokpp-spaced-keyword": 422,
    "en-health": 200,
    "en-address": 200,
    "en-personal-doc": 200,
    "en-vehicle": 200,
}


def expected_leaks(path: str, location: str) -> dict[str, str]:
    """Canary id -> reason, for the canaries that leak in this cell."""
    found = dict(GLOBAL_LEAKS)
    found.update(CELL_LEAKS.get((path, location), {}))
    return found
