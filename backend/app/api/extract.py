"""``POST /api/extract``: one file as raw bytes (ADR 0010; threat model T3, T4, T6, T11).

Stage 2 checks the file and returns its kind; stage 3 adds the extracted text.

Request: the raw file bytes, ``Content-Type: application/octet-stream`` (media type
compared without parameters, case-insensitive) and ``Content-Length``. No file name
anywhere; any ``Content-Disposition`` or ``X-File-Name`` header is ignored and never
read.

Order of checks (each answers before the next step):

1. no valid ``Content-Length`` → ``411 length_required``;
2. ``Content-Length`` above ``MAX_FILE_BYTES`` → ``413 file_too_large``
   (``BodySizeLimitMiddleware`` normally answers this first, with the same body);
3. other ``Content-Type`` → ``415 unsupported_media_type``;
4. no free extraction slot → ``503 busy`` with ``Retry-After: 5``;
5. the body is read into memory and counted; above the limit → ``413``;
6. zero bytes → ``422 empty_file``;
7. detection → ``200 {"kind", "bytes"}`` or ``422`` with the detection code.

The slot from step 4 is released in ``finally``: on success, on every error, on a
client disconnect (Starlette raises ``ClientDisconnect``) and on cancellation.

The body is never written to disk, never logged and never echoed. Error bodies hold
fixed codes only.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.extraction.detect import DetectionError, FileKind, ZipLimits, detect_kind
from app.extraction.limiter import ExtractionLimiter
from app.middleware.body_limit import EXTRACT_PATH, declared_length
from app.settings import Settings

router = APIRouter()

ACCEPTED_MEDIA_TYPE = "application/octet-stream"
RETRY_AFTER_SECONDS = 5


class ExtractResponse(BaseModel):
    kind: FileKind
    bytes: int


def _error(code: str, status: int, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"error": code}, status_code=status, headers=headers)


def _media_type(content_type: str | None) -> str:
    if content_type is None:
        return ""
    return content_type.split(";", 1)[0].strip().lower()


def _app_state(request: Request) -> tuple[Settings, ExtractionLimiter]:
    settings = request.app.state.settings
    limiter = request.app.state.extraction_limiter
    if not isinstance(settings, Settings) or not isinstance(limiter, ExtractionLimiter):
        msg = "app state is not configured"
        raise TypeError(msg)
    return settings, limiter


def _check_headers(request: Request, settings: Settings) -> JSONResponse | None:
    """Steps 1 to 3: answer from the headers alone, before any body byte is read."""
    length = declared_length(request.headers)
    if length is None:
        return _error("length_required", 411)
    if length > settings.max_file_bytes:
        return _error("file_too_large", 413)
    if _media_type(request.headers.get("content-type")) != ACCEPTED_MEDIA_TYPE:
        return _error("unsupported_media_type", 415)
    return None


async def _read_body(request: Request, limit: int) -> bytes | None:
    """The whole body, or ``None`` as soon as it grows above ``limit``."""
    parts: list[bytes] = []
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > limit:
            return None
        parts.append(chunk)
    return b"".join(parts)


@router.post(
    EXTRACT_PATH,
    response_model=ExtractResponse,
    responses={
        411: {"description": "length_required"},
        413: {"description": "file_too_large"},
        415: {"description": "unsupported_media_type"},
        422: {
            "description": "empty_file, unsupported_type, legacy_office_unsupported, "
            "pages_unsupported or archive_rejected"
        },
        503: {"description": "busy"},
    },
)
async def extract(request: Request) -> ExtractResponse | JSONResponse:
    settings, limiter = _app_state(request)
    rejection = _check_headers(request, settings)
    if rejection is not None:
        return rejection
    if not limiter.try_acquire():
        return _error("busy", 503, {"Retry-After": str(RETRY_AFTER_SECONDS)})

    try:
        data = await _read_body(request, settings.max_file_bytes)
        if data is None:
            return _error("file_too_large", 413)
        if not data:
            return _error("empty_file", 422)
        limits = ZipLimits(
            max_entries=settings.max_zip_entries,
            max_uncompressed_bytes=settings.max_zip_uncompressed_bytes,
            max_ratio=settings.max_zip_ratio,
        )
        try:
            kind = detect_kind(data, limits=limits)
        except DetectionError as error:
            return _error(error.code, 422)
        return ExtractResponse(kind=kind, bytes=len(data))
    finally:
        limiter.release()
