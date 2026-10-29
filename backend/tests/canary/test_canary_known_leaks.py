"""S5b-T4 AC 1: the documented detector gaps stay documented and stay current.

``known_leaks.py`` lists canaries the detector does not mask. The matrix marks them
``xfail(strict=True)``; this file checks the bookkeeping and what the safety check does
about each global gap, one canary alone in a document.
"""

from __future__ import annotations

import pytest

from tests.canary import builders
from tests.canary.catalogue import BY_ID
from tests.canary.harness import CellRun, find_leaks, pipeline
from tests.canary.known_leaks import CELL_LEAKS, GLOBAL_LEAKS, SAFETY_NET


def test_every_known_leak_names_an_existing_canary_and_cell() -> None:
    assert set(GLOBAL_LEAKS) <= set(BY_ID)
    for (path, location), leaks in CELL_LEAKS.items():
        assert location in builders.LOCATIONS[path]
        planted = {c.id for c in builders.applicable(path, location)}
        assert set(leaks) <= planted, f"{path}/{location}"
        assert not set(leaks) & set(GLOBAL_LEAKS), "already global"


def test_every_global_leak_has_a_safety_net_entry() -> None:
    assert set(SAFETY_NET) == set(GLOBAL_LEAKS)


def test_every_leak_has_a_reason() -> None:
    reasons = [*GLOBAL_LEAKS.values(), *[r for cell in CELL_LEAKS.values() for r in cell.values()]]
    assert all(len(reason) > 20 for reason in reasons)


@pytest.mark.parametrize("canary_id", sorted(GLOBAL_LEAKS))
def test_safety_check_answer_for_a_global_gap_alone_in_a_document(canary_id: str) -> None:
    """422: the second detector run refuses the document (fail closed).
    200: nothing stops the identifier; this is the real residual risk (T11)."""
    canary = BY_ID[canary_id]
    run = CellRun("ocr", "alone", [canary])
    blocks = builders.ocr_blocks("body", [canary])
    pipeline(blocks, run)

    assert run.segment_status == 200
    expected = SAFETY_NET[canary_id]
    if expected is None:
        assert find_leaks(canary.needles, run.masked_text) == [], "no longer context dependent"
        return
    assert run.safety_status == expected, run.safety_text[:120]
    if run.safety_status == 200:
        assert find_leaks(canary.needles, run.masked_text) != [], (
            "the identifier is masked when alone: the gap depends on neighbours; "
            "update known_leaks.py"
        )
