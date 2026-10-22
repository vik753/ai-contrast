"""``POST /api/extract/google-doc``: a public Google Docs document by ID (S3-T6a).

Request: ``Content-Type: application/json``, body ``{"document_id": "<ID>"}`` and no other
field. The ID is a password for the document: it is never logged, echoed or put in an
error. Order of checks: media type (``415``), body and ID (``422``), extraction slot
(``503 busy``), fetch (``422``, ``502``, ``504``), detection by magic bytes (must be DOCX,
else ``502 google_doc_unavailable``), then the same extraction as ``POST /api/extract``.
The slot is held from before the fetch until the last byte of the response is sent.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Final

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.types import Receive, Scope, Send

from app.api.extract import _app_state, _media_type, _sandbox_limits, _send_in_chunks
from app.extraction.detect import DetectionError, FileKind, ZipLimits, detect_kind
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
RETRY_AFTER_SECONDS: Final = 5
_STATUS: Final = {
    INVALID_ID: 422,
    NOT_PUBLIC: 422,
    NOT_FOUND: 422,
    TOO_LARGE: 422,
    UNAVAILABLE: 502,
    TIMEOUT: 504,
}
_BAD_GATEWAY: Final = 502


def _error(code: str, status: int, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"error": code}, status_code=status, headers=headers)


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
    _app_state(request)
    if _media_type(request.headers.get("content-type")) != "application/json":
        return _error("unsupported_media_type", 415)
    document_id = _parse_id(await request.body())
    if document_id is None:
        return _error("invalid_request", 422)
    if not is_valid_document_id(document_id):
        return _error(INVALID_ID, 422)
    return _SlotResponse(request, document_id)


class _SlotResponse(Response):
    """Takes the slot, fetches, extracts and sends, all under one slot (like ``/api/extract``)."""

    def __init__(self, request: Request, document_id: str) -> None:
        super().__init__()
        self._request = request
        self._document_id = document_id

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        settings, limiter = _app_state(self._request)
        slot = limiter.try_slot()
        if slot is None:
            busy = _error("busy", 503, {"Retry-After": str(RETRY_AFTER_SECONDS)})
            await busy(scope, receive, send)
            return
        with slot:
            response = await self._fetch_and_extract(settings)
            try:
                async with asyncio.timeout(settings.extract_send_timeout_seconds):
                    await _send_in_chunks(response, send)
            except TimeoutError:
                logger.info("google_doc_send_timeout")

    async def _fetch_and_extract(self, settings: Settings) -> Response:
        try:
            data = await fetch_google_doc(
                self._document_id,
                max_bytes=settings.max_file_bytes,
                timeout_seconds=settings.google_fetch_timeout_seconds,
                client_factory=self._request.app.state.google_client_factory,
            )
        except GoogleDocError as error:
            return _error(error.code, _STATUS.get(error.code, _BAD_GATEWAY))
        limits = ZipLimits(
            max_entries=settings.max_zip_entries,
            max_uncompressed_bytes=settings.max_zip_uncompressed_bytes,
            max_ratio=settings.max_zip_ratio,
        )
        try:
            kind = detect_kind(data, limits=limits)
        except DetectionError:
            return _error(UNAVAILABLE, 502)
        if kind != FileKind.DOCX:
            return _error(UNAVAILABLE, 502)
        try:
            result = await run_extraction(data, kind, limits=_sandbox_limits(settings))
        except ExtractionError as error:
            return _error(error.code, 422)
        return Response(result.model_dump_json(), media_type="application/json")
