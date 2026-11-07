"""Scale statements in the form of marks and glued letters (backend-dev tests)."""

import pytest

from app.analysis.verify import ValueIn, ValueStatus, verify_value

from .helpers import c, ctx, ev
from .test_values import nv

TEXT = "The insurer pays within 10 days after notice."


def _status(note: str) -> ValueStatus:
    out = verify_value(
        ctx(c("c1", TEXT), c("c2", note)),
        ValueIn("a", (ev("c1", TEXT),), number=nv("10", "days")),
    )
    return out.status


@pytest.mark.parametrize(
    "note",
    [
        "Amounts in USD'000.",
        "Amounts in USD '000.",
        "Amounts in (000) USD.",
        "Amounts in USD 000.",
        "Amounts in K USD.",
        "Amounts in k€.",
        "Amounts in TUSD.",
        "Amounts in kUSD.",
    ],
)
def test_scale_statement_marks_make_the_document_scaled(note: str) -> None:
    assert _status(note) is ValueStatus.not_confirmed


@pytest.mark.parametrize("note", ["Address: m. Kyiv, k. 5, mm 3.", "м. Київ, к. 5."])
def test_bare_letters_stay_exempt(note: str) -> None:
    assert _status(note) is ValueStatus.verified
