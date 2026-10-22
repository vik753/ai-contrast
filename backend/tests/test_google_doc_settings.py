"""S3-T6a item 7: settings ``GOOGLE_FETCH_TIMEOUT_SECONDS`` (20) and
``GOOGLE_CONNECT_TIMEOUT_SECONDS`` (5), bounds validated like the existing settings
(positive; zero, negative and non-numeric values are refused; no value in the error).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.settings import Settings

DEFAULTS = {"google_fetch_timeout_seconds": 20, "google_connect_timeout_seconds": 5}


@pytest.mark.parametrize("field", sorted(DEFAULTS))
def test_google_setting_default(field: str) -> None:
    assert getattr(Settings(), field) == DEFAULTS[field]


@pytest.mark.parametrize("field", sorted(DEFAULTS))
def test_google_setting_read_from_env(monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    monkeypatch.setenv(field.upper(), "7")

    assert getattr(Settings(), field) == 7


@pytest.mark.parametrize("field", sorted(DEFAULTS))
@pytest.mark.parametrize("value", ["0", "-1", "abc", "", "nan", "inf"])
def test_google_setting_invalid_value_refused_without_echo(
    monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    monkeypatch.setenv(field.upper(), value)

    with pytest.raises(ValidationError) as info:
        Settings()

    if value:
        assert f"'{value}'" not in str(info.value)
