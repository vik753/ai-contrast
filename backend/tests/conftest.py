"""Shared fixtures for the backend tests.

Tests are written against the public interface of task S1-T1
(see docs/agent/TASKS.md), not against the implementation.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from tests.helpers import ALLOWED_ORIGIN, LOG_NAMESPACE, SETTINGS_ENV_VARS

TEST_CLIENT_LOGGERS = ("httpx", "httpcore", "httpx2", "httpcore2")


@pytest.fixture(autouse=True)
def _clean_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make every test independent of the developer's shell environment."""
    for name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def log_capture(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """Capture all loggers (root and the ai_contrast namespace) at DEBUG.

    The test client itself (httpx/httpcore) logs the full request URL from
    the client side of the connection. Those loggers belong to the test
    harness, not to the server, so they are raised to WARNING here.
    """
    # caplog.set_level() also sets the capture handler level, so the
    # DEBUG calls must come last.
    for client_logger in TEST_CLIENT_LOGGERS:
        caplog.set_level(logging.WARNING, logger=client_logger)
    caplog.set_level(logging.DEBUG, logger=LOG_NAMESPACE)
    caplog.set_level(logging.DEBUG)
    yield caplog


@pytest.fixture
def make_app() -> Callable[..., FastAPI]:
    """Build a fresh app. Keyword arguments are passed to ``Settings``.

    Production requires ``allowed_origins`` to be set explicitly (S1-T1b AC6).
    When a test asks for production without origins, a valid https origin
    is supplied so that the test exercises its own behavior only.
    """

    def _make_app(**settings_overrides: Any) -> FastAPI:
        if settings_overrides.get("environment") == "production":
            settings_overrides.setdefault("allowed_origins", [ALLOWED_ORIGIN])
        return create_app(Settings(**settings_overrides))

    return _make_app


@pytest.fixture
def make_client(make_app: Callable[..., FastAPI]) -> Callable[..., TestClient]:
    """Build a TestClient for a fresh app.

    ``app`` may be passed to reuse an app that already has test routes.
    ``raise_server_exceptions`` defaults to False so that 500 responses
    can be inspected. Other keyword arguments go to ``Settings``.
    """

    def _make_client(
        app: FastAPI | None = None,
        *,
        raise_server_exceptions: bool = False,
        **settings_overrides: Any,
    ) -> TestClient:
        if app is None:
            app = make_app(**settings_overrides)
        return TestClient(app, raise_server_exceptions=raise_server_exceptions)

    return _make_client
