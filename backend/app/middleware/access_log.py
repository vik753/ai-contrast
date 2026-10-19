"""Access log: one line per request (threat model T1, T3).

Format: ``<METHOD> <path> <status> duration_ms=<int>[ aborted=1][ disconnected=1]``.

- The path never includes the query string. Never headers, never bodies.
- ``status`` is the status sent to the client, or ``-`` when no response started
  (cancellation, client disconnect).
- ``aborted=1``: the response started but did not finish (the app failed or was
  cancelled mid-response).
- ``disconnected=1``: the client disconnected before the response finished.
"""

from __future__ import annotations

import logging
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.middleware._safe import log_method, log_path

logger = logging.getLogger("ai_contrast.access")

NO_STATUS = "-"


class AccessLogMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        status: int | None = None
        response_complete = False
        disconnected = False
        start = time.perf_counter()

        async def receive_tracking() -> Message:
            nonlocal disconnected
            message = await receive()
            if message["type"] == "http.disconnect" and not response_complete:
                disconnected = True
            return message

        async def send_tracking(message: Message) -> None:
            nonlocal status, response_complete
            if message["type"] == "http.response.start":
                status = int(message["status"])
            elif message["type"] == "http.response.body" and not message.get("more_body"):
                response_complete = True
            await send(message)

        try:
            await self.app(scope, receive_tracking, send_tracking)
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000)
            flags = ""
            if status is not None and not response_complete:
                flags += " aborted=1"
            if disconnected:
                flags += " disconnected=1"
            logger.info(
                "%s %s %s duration_ms=%d%s",
                log_method(scope),
                log_path(scope),
                NO_STATUS if status is None else str(status),
                duration_ms,
                flags,
            )
