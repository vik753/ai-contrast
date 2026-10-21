"""S3-T1 public interface: the six parsing sandbox and text cap settings (T4, T6).

Environment variables, positive integers, validated. Defaults from S3-T1 in
docs/agent/TASKS.md (Stage 3).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.settings import Settings

DEFAULTS = {
    "extract_worker_memory_mb": 192,
    "extract_worker_cpu_seconds": 20,
    "extract_worker_wall_seconds": 30,
    "extract_max_result_bytes": 8 * 1024 * 1024,
    "extract_max_text_chars": 2_000_000,
    "extract_max_blocks": 20_000,
}
FIELDS = sorted(DEFAULTS)


@pytest.mark.parametrize("field", FIELDS)
def test_extract_setting_default(field: str) -> None:
    assert getattr(Settings(), field) == DEFAULTS[field]


@pytest.mark.parametrize("field", FIELDS)
def test_extract_setting_read_from_env(monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    monkeypatch.setenv(field.upper(), "1234")

    assert getattr(Settings(), field) == 1234


@pytest.mark.parametrize("field", FIELDS)
def test_extract_setting_direct_value_accepted(field: str) -> None:
    assert getattr(Settings(**{field: 7}), field) == 7


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("value", ["0", "-1"])
def test_extract_setting_env_non_positive_rejected(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    monkeypatch.setenv(field.upper(), value)

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("value", [0, -5])
def test_extract_setting_direct_non_positive_rejected(field: str, value: int) -> None:
    with pytest.raises(ValidationError) as info:
        Settings(**{field: value})

    errors = info.value.errors()
    assert [e["loc"] for e in errors] == [(field,)]
    assert errors[0]["type"] != "extra_forbidden"


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("value", ["ten", "1.5", ""])
def test_extract_setting_env_not_an_integer_rejected(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    monkeypatch.setenv(field.upper(), value)

    with pytest.raises(ValidationError):
        Settings()
