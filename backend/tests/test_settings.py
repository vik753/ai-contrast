"""AC7: settings and OpenAPI docs per environment (T2, T6)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.settings import Settings


def test_settings_defaults_environment_is_development() -> None:
    assert Settings().environment == "development"


def test_settings_defaults_allowed_origins_is_local_frontend() -> None:
    assert Settings().allowed_origins == ["http://localhost:5173"]


def test_settings_defaults_allow_private_provider_urls_is_false() -> None:
    assert Settings().allow_private_provider_urls is False


def test_settings_env_allowed_origins_comma_separated_parsed_and_trimmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://a.example, https://b.example")

    assert Settings().allowed_origins == ["https://a.example", "https://b.example"]


def test_settings_env_allowed_origins_single_value_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://a.example")

    assert Settings().allowed_origins == ["https://a.example"]


def test_settings_env_allowed_origins_surrounding_whitespace_trimmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", "  https://a.example  ,https://b.example  ")

    assert Settings().allowed_origins == ["https://a.example", "https://b.example"]


def test_settings_env_environment_production_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://app.example")

    assert Settings().environment == "production"


def test_settings_env_environment_unknown_value_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "staging")

    with pytest.raises(ValidationError):
        Settings()


def test_settings_direct_environment_unknown_value_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="staging")  # type: ignore[arg-type]


def test_settings_env_allow_private_provider_urls_true_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOW_PRIVATE_PROVIDER_URLS", "true")

    assert Settings().allow_private_provider_urls is True


def test_settings_direct_allowed_origins_list_accepted() -> None:
    settings = Settings(allowed_origins=["https://a.example"])

    assert settings.allowed_origins == ["https://a.example"]


@pytest.mark.parametrize("path", ["/docs", "/openapi.json", "/redoc"])
def test_docs_in_production_return_404(make_client: Callable[..., TestClient], path: str) -> None:
    response = make_client(environment="production").get(path)

    assert response.status_code == 404


def test_docs_env_production_openapi_returns_404(
    make_client: Callable[..., TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://app.example")

    response = make_client().get("/openapi.json")

    assert response.status_code == 404


def test_docs_in_development_openapi_returns_200(
    make_client: Callable[..., TestClient],
) -> None:
    response = make_client(environment="development").get("/openapi.json")

    assert response.status_code == 200
    assert "openapi" in response.json()


def test_docs_in_development_swagger_ui_returns_200(
    make_client: Callable[..., TestClient],
) -> None:
    response = make_client(environment="development").get("/docs")

    assert response.status_code == 200
