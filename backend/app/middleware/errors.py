"""Catch unhandled exceptions (threat model T1, T3).

Why a pure ASGI middleware and not ``@app.exception_handler(Exception)``: Starlette's
``ServerErrorMiddleware`` re-raises the exception after it sends the 500 response.
The ASGI server (Uvicorn) then logs the full traceback, and exception messages can
hold secrets (an SDK error may echo the API key) or contract text.

This middleware catches the exception, logs only its class name and the request
path, sends ``{"error": "internal_error"}`` with status 500, and does not re-raise.
"""

from __future__ import annotations

import logging

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.middleware._safe import log_path

logger = logging.getLogger("ai_contrast.errors")

INTERNAL_ERROR_BODY = {"error": "internal_error"}


class ErrorCatcherMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_tracking(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_tracking)
        except Exception as exc:  # noqa: BLE001 - last-resort handler; must not re-raise
            # Class name and path only. No message, no traceback, no exc_info:
            # any of them may contain the provider key or contract text.
            logger.error(  # noqa: TRY400 - a traceback would leak the exception message
                "unhandled_exception type=%s path=%s",
                type(exc).__name__,
                log_path(scope),
            )
            if response_started:
                # Headers are already sent; a second response is not possible.
                # Returning ends the response early; the client sees a broken body.
                return
            response = JSONResponse(INTERNAL_ERROR_BODY, status_code=500)
            await response(scope, receive, send)
