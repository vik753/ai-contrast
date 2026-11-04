"""S7-T1 AC1: ``GET /api/topics/catalog`` and the startup check."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from app.topics.catalog import load_catalog
from tests.topics.helpers import CATALOG_OK, copy_ok

URL = "/api/topics/catalog"


def _client(path: Path = CATALOG_OK) -> TestClient:
    app = create_app(Settings(environment="development", topics_catalog_dir=path))
    return TestClient(app)


def test_catalog_endpoint_returns_the_loaded_catalog() -> None:
    response = _client().get(URL)

    assert response.status_code == 200
    assert response.json() == load_catalog(CATALOG_OK).model_dump(mode="json")


def test_catalog_endpoint_reply_has_version_and_all_domains() -> None:
    body = _client().get(URL).json()

    assert sorted(body) == ["catalog_version", "domains"]
    assert [d["id"] for d in body["domains"]] == ["kasko", "lease"]


def test_catalog_endpoint_is_cacheable() -> None:
    response = _client().get(URL)

    assert "max-age" in response.headers["cache-control"]
    assert "no-store" not in response.headers["cache-control"]


def test_catalog_endpoint_needs_no_key_and_no_body() -> None:
    assert _client().get(URL).status_code == 200


@pytest.mark.parametrize("method", ["post", "put", "delete", "patch"])
def test_catalog_endpoint_refuses_other_methods(method: str) -> None:
    assert getattr(_client(), method)(URL).status_code == 405


def test_catalog_invalid_directory_fails_app_startup(tmp_path: Path) -> None:
    path = copy_ok(tmp_path / "cat")
    (path / "lease.json").write_text("[]", encoding="utf-8")

    with pytest.raises(Exception):  # noqa: B017, PT011
        create_app(Settings(environment="development", topics_catalog_dir=path))


def test_catalog_endpoint_reply_contains_no_server_path() -> None:
    assert str(CATALOG_OK) not in _client().get(URL).text
