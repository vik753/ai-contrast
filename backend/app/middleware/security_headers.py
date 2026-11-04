"""Security headers on every HTTP response (threat model T1, T3, T9)."""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

HTTP_OK = 200
SECURITY_HEADERS: dict[str, str] = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


# The one static, public reply that may be cached (ADR 0017 point 2). Its route sets its own
# `Cache-Control`; every other response, and every other status of this path, gets `no-store`.
CACHEABLE_PATHS: frozenset[str] = frozenset({"/api/topics/catalog"})


class SecurityHeadersMiddleware:
    """Set the security headers on every HTTP response, replacing any existing value."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                keep_cache = (
                    scope["path"] in CACHEABLE_PATHS
                    and message["status"] == HTTP_OK
                    and "cache-control" in headers
                )
                for name, value in SECURITY_HEADERS.items():
                    if name == "Cache-Control" and keep_cache:
                        continue
                    headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)
