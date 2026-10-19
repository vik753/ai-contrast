"""S1-T1b AC7: the Docker runtime stage fails closed (T2, T8)."""

from __future__ import annotations

import re
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parent.parent / "Dockerfile"


def _instructions() -> list[str]:
    """Dockerfile instructions with comments dropped and continuations joined."""
    lines: list[str] = []
    current = ""
    for raw in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not current and (not stripped or stripped.startswith("#")):
            continue
        if stripped.startswith("#"):
            continue
        if stripped.endswith("\\"):
            current += stripped[:-1] + " "
            continue
        lines.append(current + stripped)
        current = ""
    if current:
        lines.append(current)
    return lines


def _final_stage() -> list[str]:
    instructions = _instructions()
    last_from = max(i for i, line in enumerate(instructions) if line.upper().startswith("FROM "))
    return instructions[last_from:]


def _env_assignments(stage: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in stage:
        if not line.upper().startswith("ENV "):
            continue
        for key, value in re.findall(r'([A-Za-z_][A-Za-z0-9_]*)=("[^"]*"|\S+)', line[4:]):
            values[key] = value.strip('"')
    return values


def test_dockerfile_final_stage_sets_environment_production() -> None:
    assert _env_assignments(_final_stage()).get("ENVIRONMENT") == "production"


def test_dockerfile_final_stage_does_not_set_allow_private_provider_urls_true() -> None:
    value = _env_assignments(_final_stage()).get("ALLOW_PRIVATE_PROVIDER_URLS", "false")

    assert value.lower() not in {"1", "true", "yes", "on"}


def test_dockerfile_final_stage_does_not_enable_sdk_debug_logging() -> None:
    env = _env_assignments(_final_stage())

    assert "ANTHROPIC_LOG" not in env
    assert "OPENAI_LOG" not in env
