"""S5-T1 AC5, AC7: segmentation settings (environment variables, positive integers)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.settings import Settings

DEFAULTS = {
    "segment_max_body_bytes": 4 * 1024 * 1024,
    "segment_max_clauses": 2000,
    "segment_max_clause_chars": 20_000,
}
FIELDS = sorted(DEFAULTS)


@pytest.mark.parametrize("field", FIELDS)
def test_segment_setting_default(field: str) -> None:
    assert getattr(Settings(), field) == DEFAULTS[field]


@pytest.mark.parametrize("field", FIELDS)
def test_segment_setting_read_from_env(monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    monkeypatch.setenv(field.upper(), "1234")

    assert getattr(Settings(), field) == 1234


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("value", ["0", "-1", "ten", "1.5", ""])
def test_segment_setting_env_invalid_rejected(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    monkeypatch.setenv(field.upper(), value)

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("value", [0, -5])
def test_segment_setting_direct_non_positive_rejected(field: str, value: int) -> None:
    with pytest.raises(ValidationError) as info:
        Settings(**{field: value})

    errors = info.value.errors()
    assert [e["loc"] for e in errors] == [(field,)]
    assert errors[0]["type"] != "extra_forbidden"
