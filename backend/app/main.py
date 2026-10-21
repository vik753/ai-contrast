"""FastAPI application factory.

Run (from ``backend/``, as in the ``Dockerfile``)::

    uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log \
        --no-proxy-headers --no-server-header --log-config log_config.json
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.telemetry import TelemetryConfig
from starlette.middleware.cors import CORSMiddleware

from app import __version__
from app.api import extract, health
from app.api.validation_errors import validation_error_handler
from app.extraction.limiter import ExtractionLimiter
from app.middleware import (
    AccessLogMiddleware,
    BodySizeLimitMiddleware,
    ErrorCatcherMiddleware,
    SecurityHeadersMiddleware,
)
from app.settings import Settings

CORS_ALLOWED_METHODS = ["GET", "POST"]
CORS_ALLOWED_HEADERS = ["Content-Type", "X-Provider-Key"]
# Production is cross-origin: the browser may read `Retry-After` only if it is exposed.
CORS_EXPOSED_HEADERS = ["Retry-After"]

# FastAPI native OpenTelemetry is off: no spans, metrics or logs leave the process,
# whatever the environment says (`FASTAPI_OTEL_AUTO_CONFIGURE` included).
TELEMETRY_DISABLED: TelemetryConfig = {
    "tracing": False,
    "metrics": False,
    "logs": False,
    "operation_spans": False,
    "auto_configure": False,
}


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Does not configure logging: the server entry point does that."""
    if settings is None:
        settings = Settings()

    docs_enabled = settings.environment != "production"
    app = FastAPI(
        title="AI Contrast",
        version=__version__,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
        telemetry=TELEMETRY_DISABLED,
    )
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(health.router)
    app.include_router(extract.router)
    app.state.settings = settings
    # One limiter per app: extractions in progress on this server (T6, ADR 0010).
    app.state.extraction_limiter = ExtractionLimiter(settings.max_concurrent_extractions)

    # `add_middleware` puts each new middleware outside the previous ones,
    # so they are added from the innermost to the outermost.
    app.add_middleware(ErrorCatcherMiddleware)
    app.add_middleware(
        BodySizeLimitMiddleware,
        max_file_bytes=settings.max_file_bytes,
        max_json_body_bytes=settings.max_json_body_bytes,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=CORS_ALLOWED_METHODS,
        allow_headers=CORS_ALLOWED_HEADERS,
        expose_headers=CORS_EXPOSED_HEADERS,
        allow_credentials=False,
    )
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    return app


app = create_app()
