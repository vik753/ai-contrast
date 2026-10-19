"""backend-dev unit tests for hardening beyond the S1-T1 acceptance criteria."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.middleware._safe import MAX_LOGGED_PATH_LENGTH, log_path
from app.settings import Settings
from tests.helpers import ai_contrast_records


def test_log_path_replaces_control_characters() -> None:
    assert log_path({"path": "/api/a\nFAKE 200\r\x1b[31m"}) == "/api/a?FAKE 200??[31m"


def test_log_path_truncates_long_paths() -> None:
    logged = log_path({"path": "/" + "a" * 1000})

    assert len(logged) == MAX_LOGGED_PATH_LENGTH + len("...")


def test_access_log_encoded_newline_in_path_stays_one_line(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    client = make_client()
    log_capture.clear()

    client.get("/api/x%0Aforged%20line")

    (record,) = ai_contrast_records(log_capture)
    assert "\n" not in record.getMessage()


def test_settings_wildcard_origin_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(allowed_origins=["*"])


def test_settings_env_empty_origin_entries_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://a.example,, ,")

    assert Settings().allowed_origins == ["https://a.example"]


def test_settings_private_provider_urls_rejected_in_production() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production", allow_private_provider_urls=True)
