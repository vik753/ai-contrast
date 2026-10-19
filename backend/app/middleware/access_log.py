"""Access log: one line per request (threat model T1, T3).

The line holds only the method, the path (without the query string), the status
and the duration in milliseconds. Never headers, never bodies.
"""

from __future__ import annotations

import logging
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.middleware._safe import log_method, log_path

logger = logging.getLogger("ai_contrast.access")

# Status logged when the app fails before it starts a response.
NO_RESPONSE_STATUS = 500


class AccessLogMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        status = NO_RESPONSE_STATUS
        start = time.perf_counter()

        async def send_with_status(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_with_status)
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000)
            logger.info(
                "%s %s %d duration_ms=%d",
                log_method(scope),
                log_path(scope),
                status,
                duration_ms,
            )
