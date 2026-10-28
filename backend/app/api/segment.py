"""``POST /api/segment``: the blocks of one file in, the clauses out (ADR 0014; T3, T5, T6).

Request: ``Content-Type: application/json`` (media type compared without parameters,
case-insensitive), ``Content-Length`` and no ``Transfer-Encoding``. The body is
``{"blocks": [{"text", "part", "page"}]}`` (the ``/api/extract`` block shape).

The order of checks is the one of ``/api/extract``: 411, 413 (``SEGMENT_MAX_BODY_BYTES``,
``request_too_large``), 415 before the extraction slot (503 ``busy``, shared with
extraction); then the body is read under the slot with the same deadline and minimum
rate (400, 408). The parent never parses the body: the raw bytes go to the sandbox
child, which validates, cleans and segments (``app.segment.child``). Errors are
``{"error": "<code>"}`` and never echo input: ``invalid_request``, ``too_much_text``,
``no_text_extracted``, ``too_many_clauses``, ``clause_too_long`` and
``segment_failed`` give ``422``; ``segment_timeout`` gives ``504``. The 200 reply is
``SegmentResult``. Every response carries ``Cache-Control: no-store``.
"""

from __future__ import annotations

import logging
from typing import Final

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.api.common import (
    BodyRejectedError,
    SlotResponse,
    app_state,
    check_upload_headers,
    early_error,
    error_response,
    read_body,
    sandbox_limits,
)
from app.http_limits import SEGMENT_PATH
from app.segment.model import INVALID_REQUEST, SEGMENT_TIMEOUT, SegmentResult
from app.segment.runner import run_segmentation
from app.segment.segmenter import SegmentError, SegmentLimits
from app.settings import Settings

router = APIRouter()
logger = logging.getLogger("ai_contrast.segment")

ACCEPTED_MEDIA_TYPE: Final = "application/json"
GATEWAY_TIMEOUT: Final = 504


@router.post(
    SEGMENT_PATH,
    response_model=SegmentResult,
    responses={
        400: {"description": "length_mismatch"},
        408: {"description": "upload_timeout"},
        411: {"description": "length_required"},
        413: {"description": "request_too_large"},
        415: {"description": "unsupported_media_type"},
        422: {
            "description": "invalid_request, too_much_text, no_text_extracted, "
            "too_many_clauses, clause_too_long or segment_failed"
        },
        503: {"description": "busy"},
        504: {"description": "segment_timeout"},
    },
)
async def segment(request: Request) -> Response:
    settings, limiter = app_state(request)
    checked = check_upload_headers(
        request,
        max_bytes=settings.segment_max_body_bytes,
        too_large_code="request_too_large",
        accepted_media_type=ACCEPTED_MEDIA_TYPE,
    )
    if isinstance(checked, JSONResponse):
        return checked
    return SlotResponse(
        settings,
        limiter,
        lambda: _receive_and_segment(request, checked, settings),
        logger=logger,
        send_timeout_event="segment_send_timeout",
    )


async def _receive_and_segment(request: Request, declared: int, settings: Settings) -> Response:
    try:
        data = await read_body(
            request,
            declared,
            settings,
            max_bytes=settings.segment_max_body_bytes,
            too_large_code="request_too_large",
        )
    except BodyRejectedError as rejected:
        return early_error(rejected.code, rejected.status)
    if not data:
        return error_response(INVALID_REQUEST, 422)
    try:
        result = await run_segmentation(
            data,
            limits=sandbox_limits(settings),
            segment_limits=SegmentLimits(
                max_clauses=settings.segment_max_clauses,
                max_clause_chars=settings.segment_max_clause_chars,
            ),
        )
    except SegmentError as error:
        return error_response(error.code, GATEWAY_TIMEOUT if error.code == SEGMENT_TIMEOUT else 422)
    return Response(result.model_dump_json(), media_type="application/json")
