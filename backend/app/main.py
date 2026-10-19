"""FastAPI application factory.

Run with ``uvicorn app.main:app --no-access-log`` (see ``Dockerfile``).
"""

from __future__ import annotations

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app import __version__
from app.api import health
from app.middleware import AccessLogMiddleware, ErrorCatcherMiddleware, SecurityHeadersMiddleware
from app.settings import Settings

CORS_ALLOWED_METHODS = ["GET", "POST"]
CORS_ALLOWED_HEADERS = ["Content-Type", "X-Provider-Key"]


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
    )
    app.include_router(health.router)

    # `add_middleware` puts each new middleware outside the previous ones,
    # so they are added from the innermost to the outermost.
    app.add_middleware(ErrorCatcherMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=CORS_ALLOWED_METHODS,
        allow_headers=CORS_ALLOWED_HEADERS,
        allow_credentials=False,
    )
    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    return app


app = create_app()
