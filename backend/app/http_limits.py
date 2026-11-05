"""HTTP request limits shared by `BodySizeLimitMiddleware` and the upload routers."""

from __future__ import annotations

from typing import Final

from starlette.datastructures import Headers

EXTRACT_PATH: Final = "/api/extract"
SEGMENT_PATH: Final = "/api/segment"
SAFETY_PATH: Final = "/api/safety-check"
CHECK_PATH: Final = "/api/provider/check"
SUGGEST_PATH: Final = "/api/topics/suggest"
PROPOSE_PATH: Final = "/api/topics/propose-attributes"
EXPAND_PATH: Final = "/api/topics/expand-synonyms"
# Body cap of the topic endpoints that carry a topic only (ADR 0017 point 6).
TOPIC_MAX_BODY_BYTES: Final = 16 * 1024
# Body cap of the connection check: a short JSON object (ADR 0016 point 6).
CHECK_MAX_BODY_BYTES: Final = 4096

# A `Content-Length` with more digits than this counts as too large; it is never
# passed to `int()` (no work proportional to a hostile header length).
MAX_CONTENT_LENGTH_DIGITS: Final = 18
# Greater than any 18-digit value, so greater than every configured limit.
HUGE_CONTENT_LENGTH: Final = 10**MAX_CONTENT_LENGTH_DIGITS

_OPTIONAL_WHITESPACE: Final = " \t"


def declared_length(headers: Headers) -> int | None:
    """The `Content-Length` as an integer, or `None` if it is absent or not a
    plain decimal number.

    More than 18 digits gives `HUGE_CONTENT_LENGTH` (above every limit).
    """
    value = headers.get("content-length")
    if value is None:
        return None
    value = value.strip(_OPTIONAL_WHITESPACE)
    if not value or not value.isascii() or not value.isdigit():
        return None
    if len(value) > MAX_CONTENT_LENGTH_DIGITS:
        return HUGE_CONTENT_LENGTH
    return int(value)
