"""AC1: health endpoint."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app as app_package
from app.main import app as module_app


def test_version_is_exported_as_non_empty_string() -> None:
    assert isinstance(app_package.__version__, str)
    assert app_package.__version__.strip() != ""


def test_module_level_app_is_fastapi_instance() -> None:
    assert isinstance(module_app, FastAPI)


def test_health_get_returns_200(make_client: Callable[..., TestClient]) -> None:
    response = make_client().get("/api/health")

    assert response.status_code == 200


def test_health_get_returns_status_ok_and_package_version(
    make_client: Callable[..., TestClient],
) -> None:
    response = make_client().get("/api/health")

    assert response.json() == {"status": "ok", "version": app_package.__version__}


def test_health_get_returns_json_content_type(
    make_client: Callable[..., TestClient],
) -> None:
    response = make_client().get("/api/health")

    assert response.headers["content-type"].startswith("application/json")


def test_health_in_production_returns_200(
    make_client: Callable[..., TestClient],
) -> None:
    response = make_client(environment="production").get("/api/health")

    assert response.status_code == 200
