"""Fixtures of the S6-T2 tests."""

from __future__ import annotations

import pytest

from tests.canary.harness import WireCapture


@pytest.fixture
def wire_capture() -> WireCapture:
    """The wire capture of the canary harness (ADR 0015 point 6, ADR 0016 point 10)."""
    return WireCapture()
