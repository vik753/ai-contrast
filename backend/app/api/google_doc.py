"""``POST /api/extract/google-doc``: a public Google Docs document by ID (S3-T6a).

Request: ``Content-Type: application/json``, body ``{"document_id": "<ID>"}`` and no other
field. The ID is a password for the document: it is never logged, echoed or put in an
error. Order of checks: media type (``415``, from the header alone), extraction slot
(``503 busy``, before any body byte is read), body read under the slot within
``GOOGLE_BODY_TIMEOUT_SECONDS`` (``408 upload_timeout``), body and ID (``422``), fetch
(``422``, ``502``, ``504``), detection by magic bytes (must be DOCX, else
``502 google_doc_unavailable``), then the same extraction as ``POST /api/extract``.
The slot is held from before the body read until the last byte of the response is sent
(``SlotResponse``), so a slow upload occupies a slot like an upload to ``/api/extract``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Final

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.api.common import (
    SlotResponse,
    app_state,
    early_error,
    error_response,
    google_client_factory,
    media_type,
    sandbox_limits,
    zip_limits,
)
from app.extraction.detect import DetectionError, FileKind, detect_kind
from app.extraction.model import ExtractionError
from app.extraction.sandbox import run_extraction
from app.net.google_docs import (
    INVALID_ID,
    NOT_FOUND,
    NOT_PUBLIC,
    TIMEOUT,
    TOO_LARGE,
    UNAVAILABLE,
    GoogleDocError,
    fetch_google_doc,
    is_valid_document_id,
)
from app.settings import Settings

router = APIRouter()
logger = logging.getLogger("ai_contrast.google_doc")

GOOGLE_DOC_PATH: Final = "/api/extract/google-doc"
_STATUS: Final = {
    INVALID_ID: 422,
    NOT_PUBLIC: 422,
    NOT_FOUND: 422,
    TOO_LARGE: 422,
    UNAVAILABLE: 502,
    TIMEOUT: 504,
}
_BAD_GATEWAY: Final = 502


def _parse_id(body: bytes) -> str | None:
    """The ``document_id`` string of a body with exactly that one field, else ``None``."""
    try:
        data: Any = json.loads(body)
    except (ValueError, RecursionError):
        return None
    if not isinstance(data, dict) or set(data) != {"document_id"}:
        return None
    value = data["document_id"]
    return value if isinstance(value, str) else None


@router.post(
    GOOGLE_DOC_PATH,
    responses={
        415: {"description": "unsupported_media_type"},
        422: {
            "description": "invalid_request, invalid_google_doc_id, google_doc_not_public, "
            "google_doc_not_found, google_doc_too_large or an extraction code"
        },
        502: {"description": "google_doc_unavailable"},
        503: {"description": "busy"},
        504: {"description": "google_doc_timeout"},
    },
)
async def extract_google_doc(request: Request) -> Response:
    settings, limiter = app_state(request)
    if media_type(request.headers.get("content-type")) != "application/json":
        return early_error("unsupported_media_type", 415)
    return SlotResponse(
        settings,
        limiter,
        lambda: _read_fetch_and_extract(request, settings),
        logger=logger,
        send_timeout_event="google_doc_send_timeout",
    )


async def _read_body(request: Request, settings: Settings) -> bytes | None:
    """The whole body, or ``None`` if it is not complete within the body deadline."""
    try:
        async with asyncio.timeout(settings.google_body_timeout_seconds):
            return await request.body()
    except TimeoutError:
        return None


async def _read_fetch_and_extract(request: Request, settings: Settings) -> Response:
    body = await _read_body(request, settings)
    if body is None:
        return early_error("upload_timeout", 408)
    document_id = _parse_id(body)
    if document_id is None:
        return error_response("invalid_request", 422)
    if not is_valid_document_id(document_id):
        return error_response(INVALID_ID, 422)
    try:
        data = await fetch_google_doc(
            document_id,
            max_bytes=settings.max_file_bytes,
            timeout_seconds=settings.google_fetch_timeout_seconds,
            client_factory=google_client_factory(request),
        )
    except GoogleDocError as error:
        return error_response(error.code, _STATUS.get(error.code, _BAD_GATEWAY))
    return await _extract_docx(data, settings)


async def _extract_docx(data: bytes, settings: Settings) -> Response:
    try:
        kind = detect_kind(data, limits=zip_limits(settings))
    except DetectionError:
        return error_response(UNAVAILABLE, 502)
    if kind != FileKind.DOCX:
        return error_response(UNAVAILABLE, 502)
    try:
        result = await run_extraction(data, kind, limits=sandbox_limits(settings))
    except ExtractionError as error:
        return error_response(error.code, 422)
    return Response(result.model_dump_json(), media_type="application/json")
