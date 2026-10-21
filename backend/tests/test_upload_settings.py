"""S2-T1 public interface: the six upload limit settings (T4, T6).

Environment variables, positive integers, validated. Defaults from the
limits table in docs/agent/TASKS.md (Stage 2).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.settings import Settings

DEFAULTS = {
    "max_file_bytes": 10_485_760,
    "max_json_body_bytes": 65_536,
    "max_concurrent_extractions": 2,
    "max_zip_entries": 2_000,
    "max_zip_uncompressed_bytes": 104_857_600,
    "max_zip_ratio": 200,
    # Review round 1 (PR #15): body deadline and minimum average rate.
    "extract_body_timeout_seconds": 60,
    "extract_min_rate_bytes_per_second": 32_768,
}
FIELDS = sorted(DEFAULTS)


@pytest.mark.parametrize("field", FIELDS)
def test_upload_setting_default(field: str) -> None:
    assert getattr(Settings(), field) == DEFAULTS[field]


@pytest.mark.parametrize("field", FIELDS)
def test_upload_setting_read_from_env(monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    monkeypatch.setenv(field.upper(), "1234")

    assert getattr(Settings(), field) == 1234


@pytest.mark.parametrize("field", FIELDS)
def test_upload_setting_direct_value_accepted(field: str) -> None:
    assert getattr(Settings(**{field: 7}), field) == 7


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("value", ["0", "-1"])
def test_upload_setting_env_non_positive_rejected(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    monkeypatch.setenv(field.upper(), value)

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("value", [0, -5])
def test_upload_setting_direct_non_positive_rejected(field: str, value: int) -> None:
    with pytest.raises(ValidationError) as info:
        Settings(**{field: value})

    # The field exists and its value is rejected (not "unknown field").
    errors = info.value.errors()
    assert [e["loc"] for e in errors] == [(field,)]
    assert errors[0]["type"] != "extra_forbidden"


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("value", ["ten", "1.5", ""])
def test_upload_setting_env_not_an_integer_rejected(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    monkeypatch.setenv(field.upper(), value)

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize("field", FIELDS)
def test_upload_setting_validation_error_hides_value(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    monkeypatch.setenv(field.upper(), "-987654321")

    with pytest.raises(ValidationError) as info:
        Settings()

    assert "987654321" not in str(info.value)


# --- EXTRACT_RATE_GRACE_SECONDS (round 2): a positive number, floats allowed ----------


def test_rate_grace_setting_default_is_five_seconds() -> None:
    assert Settings().extract_rate_grace_seconds == 5


@pytest.mark.parametrize(("raw", "expected"), [("0.5", 0.5), ("2", 2), ("12.25", 12.25)])
def test_rate_grace_setting_read_from_env(
    monkeypatch: pytest.MonkeyPatch, raw: str, expected: float
) -> None:
    monkeypatch.setenv("EXTRACT_RATE_GRACE_SECONDS", raw)

    assert Settings().extract_rate_grace_seconds == expected


@pytest.mark.parametrize("raw", ["0", "-1", "-0.5", "0.0", "abc", "nan", "inf", ""])
def test_rate_grace_setting_env_invalid_rejected(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("EXTRACT_RATE_GRACE_SECONDS", raw)

    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize("value", [0, -1, -0.5])
def test_rate_grace_setting_direct_non_positive_rejected(value: float) -> None:
    with pytest.raises(ValidationError) as info:
        Settings(extract_rate_grace_seconds=value)

    errors = info.value.errors()
    assert [e["loc"] for e in errors] == [("extract_rate_grace_seconds",)]
    assert errors[0]["type"] != "extra_forbidden"


def test_rate_grace_setting_direct_float_accepted() -> None:
    assert Settings(extract_rate_grace_seconds=0.25).extract_rate_grace_seconds == 0.25
