"""S1-T1b AC5 and AC6: settings errors hide input; strict origin rules (T1, T6)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.settings import Settings
from tests.helpers import new_marker

# --------------------------------------------------------------------------
# AC5: hide_input_in_errors
# --------------------------------------------------------------------------


def test_settings_error_direct_invalid_environment_hides_input() -> None:
    marker = new_marker("envvalue")

    with pytest.raises(ValidationError) as excinfo:
        Settings(environment=marker)  # type: ignore[arg-type]

    assert marker not in str(excinfo.value)


def test_settings_error_env_invalid_environment_hides_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = new_marker("envvalue")
    monkeypatch.setenv("ENVIRONMENT", marker)

    with pytest.raises(ValidationError) as excinfo:
        Settings()

    assert marker not in str(excinfo.value)


def test_settings_error_env_invalid_bool_hides_input(monkeypatch: pytest.MonkeyPatch) -> None:
    marker = new_marker("boolvalue")
    monkeypatch.setenv("ALLOW_PRIVATE_PROVIDER_URLS", marker)

    with pytest.raises(ValidationError) as excinfo:
        Settings()

    assert marker not in str(excinfo.value)


def test_settings_error_env_invalid_origin_hides_input(monkeypatch: pytest.MonkeyPatch) -> None:
    marker = new_marker("originvalue")
    monkeypatch.setenv("ALLOWED_ORIGINS", f"https://{marker}.example/path?token={marker}")

    with pytest.raises(ValidationError) as excinfo:
        Settings()

    assert marker not in str(excinfo.value)


# --------------------------------------------------------------------------
# AC6: origin format
# --------------------------------------------------------------------------

VALID_ORIGINS = [
    "https://a.example",
    "https://a.example:8443",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

INVALID_ORIGINS = {
    "path": "https://a.example/path",
    "query": "https://a.example?x=1",
    "fragment": "https://a.example#frag",
    "userinfo": "https://user@a.example",
    "userinfo-password": "https://user:pw@a.example",
    "wildcard": "*",
    "wildcard-host": "https://*.a.example",
    "null": "null",
    "no-scheme": "a.example",
    "scheme-only": "https://",
    "empty-port": "https://a.example:",
}


@pytest.mark.parametrize("origin", VALID_ORIGINS)
def test_settings_development_valid_origin_accepted(origin: str) -> None:
    assert Settings(allowed_origins=[origin]).allowed_origins == [origin]


@pytest.mark.parametrize("origin", list(INVALID_ORIGINS.values()), ids=list(INVALID_ORIGINS))
def test_settings_invalid_origin_rejected(origin: str) -> None:
    with pytest.raises(ValidationError):
        Settings(allowed_origins=[origin])


@pytest.mark.parametrize("origin", list(INVALID_ORIGINS.values()), ids=list(INVALID_ORIGINS))
def test_settings_env_invalid_origin_rejected(monkeypatch: pytest.MonkeyPatch, origin: str) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", f"https://ok.example, {origin}")

    with pytest.raises(ValidationError):
        Settings()


def test_settings_production_https_origin_accepted() -> None:
    settings = Settings(environment="production", allowed_origins=["https://a.example"])

    assert settings.allowed_origins == ["https://a.example"]


@pytest.mark.parametrize("origin", ["http://a.example", "http://localhost:5173"])
def test_settings_production_http_origin_rejected(origin: str) -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production", allowed_origins=[origin])


def test_settings_production_without_explicit_origins_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production")


def test_settings_env_production_without_allowed_origins_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")

    with pytest.raises(ValidationError):
        Settings()


def test_settings_env_production_with_allowed_origins_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://a.example,https://b.example")

    assert Settings().allowed_origins == ["https://a.example", "https://b.example"]


def test_settings_development_default_origin_still_localhost() -> None:
    assert Settings(environment="development").allowed_origins == ["http://localhost:5173"]
