"""Layer 2 of the prompt-injection defense (ADR 0009, ADR 0017 point 4)."""

from __future__ import annotations

from app.injection.patterns import PATTERNS_VERSION
from app.injection.scanner import Hit, scan

__all__ = ["PATTERNS_VERSION", "Hit", "scan"]
