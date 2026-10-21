"""Pure ASGI middleware: security headers, access log, body limit and error catcher.

Order in the stack (outermost first), set in `app.main.create_app`:

1. `SecurityHeadersMiddleware` — every response gets the headers, including 500s.
2. `AccessLogMiddleware` — one line per request, including 500s.
3. Starlette `CORSMiddleware`.
4. `BodySizeLimitMiddleware` — 413 for oversized request bodies; inside CORS, so
   the 413 carries the CORS headers for an allowed origin.
5. `ErrorCatcherMiddleware` — turns unhandled exceptions into a generic 500.
"""

from app.middleware.access_log import AccessLogMiddleware
from app.middleware.body_limit import BodySizeLimitMiddleware
from app.middleware.errors import ErrorCatcherMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware

__all__ = [
    "AccessLogMiddleware",
    "BodySizeLimitMiddleware",
    "ErrorCatcherMiddleware",
    "SecurityHeadersMiddleware",
]
