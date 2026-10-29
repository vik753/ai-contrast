"""S5b-T4 AC 1: every class x location x input path through the whole pipeline.

extract -> /api/segment -> browser-equivalent masking (Python) -> /api/safety-check.
One document per cell holds all canaries of that location (see ``builders.py``).

- ``test_canary_absent_from_masked_document``: one test per canary and cell. Documented
  detector gaps (``known_leaks.py``) are ``xfail(strict=True)`` with their reason.
- Per cell: the canaries are read from the file at all, the safety check answers 200 for
  the masked document, and no canary is in the logs or in the safety-check reply.
"""

from __future__ import annotations

import pytest

from tests.canary import builders
from tests.canary.catalogue import BY_ID, CANARIES
from tests.canary.harness import CellRun, find_leaks, run_cell
from tests.canary.known_leaks import expected_leaks

CELLS = [(path, loc) for path, locs in builders.LOCATIONS.items() for loc in locs]
CELL_IDS = [f"{path}-{loc}" for path, loc in CELLS]


def _canary_cases() -> list[object]:
    cases: list[object] = []
    for path, loc in CELLS:
        leaks = expected_leaks(path, loc)
        for canary in builders.applicable(path, loc):
            marks = []
            if canary.id in leaks:
                marks.append(pytest.mark.xfail(strict=True, reason=leaks[canary.id]))
            cases.append(
                pytest.param(path, loc, canary.id, marks=marks, id=f"{path}-{loc}-{canary.id}")
            )
    return cases


def _pipeline_ok(run: CellRun) -> None:
    assert run.extract_status == 200, f"extract answered {run.extract_status}"
    assert run.segment_status == 200, f"segment answered {run.segment_status}"


@pytest.mark.parametrize(("path", "location", "canary_id"), _canary_cases())
def test_canary_absent_from_masked_document(path: str, location: str, canary_id: str) -> None:
    run = run_cell(path, location, "all")
    _pipeline_ok(run)
    canary = BY_ID[canary_id]

    leaked = find_leaks(canary.needles, run.masked_text)

    assert leaked == [], (
        f"left in the masked document: {len(leaked)} of {len(canary.needles)} values"
    )


@pytest.mark.parametrize(("path", "location"), CELLS, ids=CELL_IDS)
def test_every_canary_is_read_from_the_file(path: str, location: str) -> None:
    """Guards against a vacuous pass: a canary that never reaches the blocks cannot leak."""
    run = run_cell(path, location, "all")
    _pipeline_ok(run)
    missing = [
        c.id for c in run.canaries if len(find_leaks(c.needles, run.block_text)) < len(c.needles)
    ]
    assert missing == []


@pytest.mark.parametrize(("path", "location"), CELLS, ids=CELL_IDS)
def test_safety_check_accepts_the_masked_document(path: str, location: str) -> None:
    run = run_cell(path, location, "clean")
    _pipeline_ok(run)
    assert run.safety_status == 200, run.safety_text[:200]


@pytest.mark.parametrize(("path", "location"), CELLS, ids=CELL_IDS)
def test_masked_document_holds_no_canary_when_safety_check_says_ok(
    path: str, location: str
) -> None:
    """The document the safety check accepted is the document without canaries."""
    run = run_cell(path, location, "clean")
    assert run.safety_status == 200
    needles = [n for c in run.canaries for n in c.needles]
    assert find_leaks(needles, run.safety_payload["clauses"][0]["text"], run.masked_text) == []


@pytest.mark.parametrize(("path", "location"), CELLS, ids=CELL_IDS)
@pytest.mark.parametrize("group", ["all", "clean"])
def test_no_canary_in_logs(path: str, location: str, group: str) -> None:
    run = run_cell(path, location, group)
    needles = [n for c in run.canaries for n in c.needles]
    assert run.logs, "the log tap saw nothing: the harness is broken"
    assert find_leaks(needles, run.logs) == []


@pytest.mark.parametrize(("path", "location"), CELLS, ids=CELL_IDS)
@pytest.mark.parametrize("group", ["all", "clean"])
def test_no_canary_in_safety_check_reply(path: str, location: str, group: str) -> None:
    """``/api/extract`` and ``/api/segment`` return text to the browser by design; every
    other reply must hold no canary (body and headers)."""
    run = run_cell(path, location, group)
    needles = [n for c in run.canaries for n in c.needles]
    assert run.safety_text
    headers = "\n".join(f"{k}: {v}" for k, v in run.safety_headers.items())
    assert find_leaks(needles, run.safety_text, headers) == []


def test_matrix_covers_every_input_path_and_the_docx_locations() -> None:
    assert set(builders.LOCATIONS) == set(builders.PATHS)
    for location in (
        "preamble",
        "body",
        "heading",
        "footnote",
        "endnote",
        "header",
        "footer",
        "textbox",
        "tracked-insertion",
        "content-control",
        "requisites-uk",
    ):
        assert location in builders.LOCATIONS["docx"]
        assert location in builders.LOCATIONS["gdoc"]
    for location in ("preamble", "body", "heading", "running-header", "running-footer"):
        assert location in builders.LOCATIONS["pdf"]
    assert len(CANARIES) >= 50
