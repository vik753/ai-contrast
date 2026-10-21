"""Request body size limit for every route (threat model T6, T4, ADR 0010).

Pure ASGI middleware between CORS and the error catcher, so a ``413`` to an
allowed origin carries the CORS headers.

- ``POST /api/extract`` (exact path): ``max_file_bytes``, error ``file_too_large``.
- Every other path: ``max_json_body_bytes``, error ``request_too_large``.

Two checks:

1. A ``Content-Length`` above the limit is answered with ``413`` before any body
   byte is read. The app is not called.
2. ``http.request`` chunks are counted as the app reads them. When the count goes
   above the limit (a body longer than its ``Content-Length``, or a chunked body),
   the middleware sends the ``413`` itself, then tells the app that the client
   disconnected. The app stops reading (Starlette raises ``ClientDisconnect``,
   which the error catcher swallows) and any response it still tries to send is
   dropped. No more body is read from the client.

Nothing here logs; the access log records the status.
"""

from __future__ import annotations

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

EXTRACT_PATH = "/api/extract"
FILE_TOO_LARGE = "file_too_large"
REQUEST_TOO_LARGE = "request_too_large"

_DISCONNECT: Message = {"type": "http.disconnect"}


def declared_length(headers: Headers) -> int | None:
    """The ``Content-Length`` as an integer, or ``None`` if it is absent or invalid."""
    value = headers.get("content-length")
    if value is None:
        return None
    value = value.strip()
    if not value.isascii() or not value.isdigit():
        return None
    return int(value)


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, *, max_file_bytes: int, max_json_body_bytes: int) -> None:
        self.app = app
        self.max_file_bytes = max_file_bytes
        self.max_json_body_bytes = max_json_body_bytes

    def _limit(self, scope: Scope) -> tuple[int, str]:
        if scope.get("path") == EXTRACT_PATH:
            return self.max_file_bytes, FILE_TOO_LARGE
        return self.max_json_body_bytes, REQUEST_TOO_LARGE

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit, code = self._limit(scope)
        too_large = JSONResponse({"error": code}, status_code=413)

        length = declared_length(Headers(scope=scope))
        if length is not None and length > limit:
            await too_large(scope, receive, send)
            return

        received = 0
        rejected = False
        response_started = False

        async def receive_counting() -> Message:
            nonlocal received, rejected
            if rejected:
                return _DISCONNECT
            message = await receive()
            if message["type"] != "http.request":
                return message
            received += len(message.get("body", b""))
            if received <= limit:
                return message
            rejected = True
            if not response_started:
                await too_large(scope, _client_gone, send)
            return _DISCONNECT

        async def send_from_app(message: Message) -> None:
            nonlocal response_started
            if rejected:
                # The 413 (or an aborted response) owns the connection now.
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        await self.app(scope, receive_counting, send_from_app)


async def _client_gone() -> Message:
    return _DISCONNECT
