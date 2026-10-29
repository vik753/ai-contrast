"""Fixtures of the canary harness (S5b-T4)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.canary.harness import CellRun, WireCapture, run_cell


@pytest.fixture
def wire_capture() -> WireCapture:
    """Stage 6 plugs the fake ``AIProvider`` here: ``provider.on_request = wire_capture.record``."""
    return WireCapture()


@pytest.fixture
def canary_pipeline() -> Callable[[str, str], CellRun]:
    """``canary_pipeline("docx", "body")``: the cached pipeline run of one cell.

    ``CellRun.safety_payload`` is the exact body that passed ``/api/safety-check``;
    stage 6 sends it through its analysis endpoint with a recording fake provider.
    """
    return run_cell
