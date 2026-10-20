"""S1-T1b AC3: FastAPI native telemetry is disabled explicitly (T1).

FastAPI 0.143 has no public accessor for the telemetry configuration. Two
kinds of checks are used:

* behavior: with a configured OpenTelemetry tracer provider, FastAPI marks
  the ASGI scope with ``"fastapi.telemetry"`` whenever its native telemetry
  wraps a request. Our app must never do that. A control test proves the
  probe detects telemetry on a plain ``FastAPI()``;
* setting: the private ``FastAPI._telemetry`` dict holds the resolved
  configuration. Accessing it is fragile across FastAPI upgrades; if it
  moves, update this test, do not drop the check.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from opentelemetry import trace

PROBE_PATH = "/api/test/telemetry-probe"
DISABLED_FLAGS = ("tracing", "metrics", "logs", "operation_spans", "auto_configure")


class _CountingTracerProvider(trace.TracerProvider):
    """A configured (non-proxy, non-NoOp) provider that hands out no-op tracers."""

    def __init__(self) -> None:
        self.tracer_requests = 0

    def get_tracer(self, *args: Any, **kwargs: Any) -> trace.Tracer:
        self.tracer_requests += 1
        return trace.NoOpTracer()


@pytest.fixture
def configured_otel_providers(monkeypatch: pytest.MonkeyPatch) -> _CountingTracerProvider:
    """Pretend that an OpenTelemetry SDK has configured a global tracer provider."""
    provider = _CountingTracerProvider()
    monkeypatch.setattr(trace, "get_tracer_provider", lambda: provider)
    return provider


def _add_probe(app: FastAPI) -> None:
    async def _probe(request: Request) -> dict[str, Any]:
        return {"telemetry": "fastapi.telemetry" in request.scope}

    app.add_api_route(PROBE_PATH, _probe, methods=["GET"])


def test_telemetry_probe_control_plain_fastapi_is_instrumented(
    configured_otel_providers: _CountingTracerProvider,
) -> None:
    app = FastAPI()
    _add_probe(app)

    response = TestClient(app).get(PROBE_PATH)

    assert response.json() == {"telemetry": True}
    assert configured_otel_providers.tracer_requests > 0


def test_telemetry_app_with_configured_providers_not_instrumented(
    make_app: Callable[..., FastAPI], configured_otel_providers: _CountingTracerProvider
) -> None:
    app = make_app()
    _add_probe(app)

    response = TestClient(app).get(PROBE_PATH)

    assert response.json() == {"telemetry": False}
    assert configured_otel_providers.tracer_requests == 0


def test_telemetry_production_app_with_configured_providers_not_instrumented(
    make_app: Callable[..., FastAPI], configured_otel_providers: _CountingTracerProvider
) -> None:
    app = make_app(environment="production")
    _add_probe(app)

    response = TestClient(app).get(PROBE_PATH)

    assert response.json() == {"telemetry": False}
    assert configured_otel_providers.tracer_requests == 0


@pytest.mark.parametrize("flag", DISABLED_FLAGS)
def test_telemetry_setting_flag_is_false(make_app: Callable[..., FastAPI], flag: str) -> None:
    config = make_app()._telemetry  # private: no public accessor in FastAPI 0.143

    assert config[flag] is False  # type: ignore[literal-required]


def test_telemetry_auto_configure_env_true_still_false(
    make_app: Callable[..., FastAPI], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FASTAPI_OTEL_AUTO_CONFIGURE", "true")

    config = make_app()._telemetry

    assert config["auto_configure"] is False
