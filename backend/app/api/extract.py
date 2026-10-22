"""``POST /api/extract``: one file as raw bytes (ADR 0010, ADR 0011; threat model T3, T4,
T6, T11).

The file is checked, its kind detected, and its text extracted in the parsing
sandbox (one child process per file). The answer is the stage 3 contract
(``ExtractionResult``, docs/agent/TASKS.md, Stage 3).

Request: the raw file bytes, ``Content-Type: application/octet-stream`` (media type
compared without parameters, case-insensitive), ``Content-Length`` and no
``Transfer-Encoding``. No file name anywhere; any ``Content-Disposition`` or
``X-File-Name`` header is ignored and never read.

Order of checks (each answers before the next step):

1. any ``Transfer-Encoding``, or no plain decimal ``Content-Length`` →
   ``411 length_required``;
2. ``Content-Length`` above ``MAX_FILE_BYTES`` → ``413 file_too_large``
   (``BodySizeLimitMiddleware`` normally answers this first, with the same body);
3. other ``Content-Type`` → ``415 unsupported_media_type``;
4. no free extraction slot → ``503 busy`` with ``Retry-After: 5``;
5. the body is read into one buffer and counted:
   above the limit → ``413``; more bytes than ``Content-Length``, or fewer when the
   body ends → ``400 length_mismatch``; not complete within
   ``EXTRACT_BODY_TIMEOUT_SECONDS``, or an average rate below
   ``EXTRACT_MIN_RATE_BYTES_PER_SECOND`` after ``EXTRACT_RATE_GRACE_SECONDS`` →
   ``408 upload_timeout``;
6. zero bytes → ``422 empty_file``;
7. detection → ``422`` with the detection code;
8. extraction in the sandbox, with the slot still held → ``200`` with the stage 3
   contract, or ``422`` with the extraction code.

Every response sent before the whole body is read (400, 408, 411, 413, 415, 503)
carries ``Connection: close``: the server does not drain the rest of the body.

The slot from step 4 is held until the last byte of the response (success or
error) is sent, or until the send deadline ``EXTRACT_SEND_TIMEOUT_SECONDS`` cuts off
a client that does not read (``SlotResponse``). It is released exactly once when
the ``with`` block ends: on success, on every error, on a client disconnect
(``ClientDisconnect``, which the error catcher swallows), on the send deadline and
on cancellation.

The body is never written to disk, never logged and never echoed. Error bodies hold
fixed codes only.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Final

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.requests import ClientDisconnect

from app.api.common import (
    SlotResponse,
    app_state,
    early_error,
    error_response,
    media_type,
    sandbox_limits,
    zip_limits,
)
from app.extraction.detect import DetectionError, detect_kind
from app.extraction.model import ExtractionError, ExtractionResult
from app.extraction.sandbox import run_extraction
from app.http_limits import EXTRACT_PATH, declared_length
from app.settings import Settings

router = APIRouter()
logger = logging.getLogger("ai_contrast.extract")

ACCEPTED_MEDIA_TYPE: Final = "application/octet-stream"
# How late a stalled stream may be detected after its rate falls below the minimum.
RATE_TICK_SECONDS: Final = 1.0


class _BodyRejectedError(Exception):
    """The body read stopped early. ``status`` and ``code`` describe the answer."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


def _check_headers(request: Request, settings: Settings) -> JSONResponse | int:
    """Steps 1 to 3, from the headers alone. Return the declared length or an answer."""
    if "transfer-encoding" in request.headers:
        return early_error("length_required", 411)
    length = declared_length(request.headers)
    if length is None:
        return early_error("length_required", 411)
    if length > settings.max_file_bytes:
        return early_error("file_too_large", 413)
    if media_type(request.headers.get("content-type")) != ACCEPTED_MEDIA_TYPE:
        return early_error("unsupported_media_type", 415)
    return length


async def _read_body(request: Request, declared: int, settings: Settings) -> bytes:
    """Read exactly ``declared`` bytes into one pre-allocated buffer.

    ``declared`` is at most ``max_file_bytes`` (checked by the caller). Raises
    ``_BodyRejectedError`` for 413, 400 and 408, ``ClientDisconnect`` if the
    client leaves.

    Deadline and minimum rate use one ``asyncio.timeout_at``. The average rate falls
    below the minimum at ``fail_at = max(grace_end, start + received / min_rate)``.
    The timeout is kept between ``fail_at`` and ``fail_at + RATE_TICK_SECONDS``
    (never after the deadline), so it never fires early and a stalled stream is
    caught within one tick. It is moved only when ``fail_at`` passes it, and each move
    sets it at least one tick later, before the deadline: so there are at most
    ``extract_body_timeout_seconds / RATE_TICK_SECONDS`` reschedules (60 by default),
    not one timer per chunk. The rate is also checked when a chunk arrives.
    """
    loop = asyncio.get_running_loop()
    start = loop.time()
    deadline = start + settings.extract_body_timeout_seconds
    grace_end = start + settings.extract_rate_grace_seconds
    min_rate = settings.extract_min_rate_bytes_per_second
    buffer = bytearray(declared)
    received = 0
    more_body = True
    try:
        async with asyncio.timeout_at(min(deadline, grace_end + RATE_TICK_SECONDS)) as timer:
            while more_body:
                message = await request.receive()
                if message["type"] != "http.request":
                    raise ClientDisconnect
                chunk: bytes = message.get("body", b"")
                more_body = bool(message.get("more_body", False))
                end = received + len(chunk)
                if end > settings.max_file_bytes:
                    raise _BodyRejectedError(413, "file_too_large")
                if end > declared:
                    raise _BodyRejectedError(400, "length_mismatch")
                buffer[received:end] = chunk
                received = end
                if not more_body:
                    break
                now = loop.time()
                if now > grace_end and received < min_rate * (now - start):
                    raise _BodyRejectedError(408, "upload_timeout")
                fail_at = max(grace_end, start + received / min_rate)
                wake = timer.when()
                if wake is not None and fail_at > wake and wake < deadline:
                    timer.reschedule(min(deadline, fail_at + RATE_TICK_SECONDS))
    except TimeoutError:
        raise _BodyRejectedError(408, "upload_timeout") from None
    if received != declared:
        raise _BodyRejectedError(400, "length_mismatch")
    return bytes(buffer)


@router.post(
    EXTRACT_PATH,
    response_model=ExtractionResult,
    responses={
        400: {"description": "length_mismatch"},
        408: {"description": "upload_timeout"},
        411: {"description": "length_required"},
        413: {"description": "file_too_large"},
        415: {"description": "unsupported_media_type"},
        422: {
            "description": "empty_file, unsupported_type, legacy_office_unsupported, "
            "pages_unsupported, archive_rejected, extraction_failed, extraction_timeout, "
            "too_many_pages, too_much_text, encrypted_unsupported, no_text_extracted, "
            "text_decoding_failed, suspicious_package, docx_strict_unsupported or pdf_damaged"
        },
        503: {"description": "busy"},
    },
)
async def extract(request: Request) -> Response:
    settings, limiter = app_state(request)
    checked = _check_headers(request, settings)
    if isinstance(checked, JSONResponse):
        return checked
    return SlotResponse(
        settings,
        limiter,
        lambda: _receive_and_extract(request, checked, settings),
        logger=logger,
        send_timeout_event="extract_send_timeout",
    )


async def _receive_and_extract(request: Request, declared: int, settings: Settings) -> Response:
    try:
        data = await _read_body(request, declared, settings)
    except _BodyRejectedError as rejected:
        return early_error(rejected.code, rejected.status)
    if not data:
        return error_response("empty_file", 422)
    try:
        kind = detect_kind(data, limits=zip_limits(settings))
    except DetectionError as error:
        return error_response(error.code, 422)
    try:
        result = await run_extraction(data, kind, limits=sandbox_limits(settings))
    except ExtractionError as error:
        return error_response(error.code, 422)
    return Response(result.model_dump_json(), media_type="application/json")
