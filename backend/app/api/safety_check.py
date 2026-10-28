"""``POST /api/safety-check``: the masked document in, ``ok`` and a digest out (ADR 0015 point 4).

Transport rules are those of ``/api/segment``: 411, 413 (``SAFETY_MAX_BODY_BYTES``,
``request_too_large``), 415 before the extraction slot (503 ``busy``, shared with extraction);
the body is read under the slot with the same deadline and minimum rate. The parent never
parses the body: the sandbox child does. Errors are ``{"error": "<code>"}``:
``detector_version_mismatch`` gives ``409``; ``input_not_clean``, ``invalid_placeholder``,
``invalid_request``, ``too_much_text``, ``too_many_identifiers`` and ``safety_failed`` give
``422``; ``unmasked_identifier`` gives ``422`` with ``"spans": [[clause_id, start, end], ...]``
(offsets only); ``safety_timeout`` gives ``504``. Every response carries ``no-store``.
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
from app.http_limits import SAFETY_PATH
from app.safety.runner import (
    MISMATCH,
    SAFETY_TIMEOUT,
    UNMASKED,
    SafetyOk,
    SafetyRunError,
    run_safety_check,
)
from app.settings import Settings

router = APIRouter()

logger = logging.getLogger("ai_contrast.safety")
ACCEPTED_MEDIA_TYPE: Final = "application/json"


@router.post(
    SAFETY_PATH,
    response_model=SafetyOk,
    responses={
        400: {"description": "length_mismatch"},
        408: {"description": "upload_timeout"},
        409: {"description": "detector_version_mismatch"},
        411: {"description": "length_required"},
        413: {"description": "request_too_large"},
        415: {"description": "unsupported_media_type"},
        422: {
            "description": "input_not_clean, invalid_placeholder, unmasked_identifier, "
            "invalid_request, too_much_text, too_many_identifiers or safety_failed"
        },
        503: {"description": "busy"},
        504: {"description": "safety_timeout"},
    },
)
async def safety_check(request: Request) -> Response:
    settings, limiter = app_state(request)
    checked = check_upload_headers(
        request,
        max_bytes=settings.safety_max_body_bytes,
        too_large_code="request_too_large",
        accepted_media_type=ACCEPTED_MEDIA_TYPE,
    )
    if isinstance(checked, JSONResponse):
        return checked
    return SlotResponse(
        settings,
        limiter,
        lambda: _receive_and_check(request, checked, settings),
        logger=logger,
        send_timeout_event="safety_send_timeout",
    )


async def _receive_and_check(request: Request, declared: int, settings: Settings) -> Response:
    try:
        data = await read_body(
            request,
            declared,
            settings,
            max_bytes=settings.safety_max_body_bytes,
            too_large_code="request_too_large",
        )
    except BodyRejectedError as rejected:
        return early_error(rejected.code, rejected.status)
    if not data:
        return error_response("invalid_request", 422)
    try:
        result = await run_safety_check(
            data, limits=sandbox_limits(settings), max_clauses=settings.segment_max_clauses
        )
    except SafetyRunError as error:
        if error.code == UNMASKED:
            return JSONResponse(
                {"error": error.code, "spans": [list(span) for span in error.spans]},
                status_code=422,
            )
        status = 409 if error.code == MISMATCH else 504 if error.code == SAFETY_TIMEOUT else 422
        return error_response(error.code, status)
    return Response(result.model_dump_json(), media_type="application/json")
