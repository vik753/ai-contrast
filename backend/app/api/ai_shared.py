"""Helpers shared by the AI endpoints (``topic_ai``, ``tag``): answers and small checks.

Public module: no endpoint imports a private name of another endpoint.
"""

from __future__ import annotations

from typing import Final

from fastapi import Request
from fastapi.responses import JSONResponse, Response

from app.ai.port import AIProvider
from app.api.common import BodyRejectedError, early_error, error_response, read_body
from app.api.provider_check import BUSY_RETRY_AFTER_SECONDS, limited
from app.limits.free import usage_neurons
from app.safety.runner import MISMATCH, SAFETY_TIMEOUT, UNMASKED, SafetyRunError
from app.settings import Settings
from app.topics.model import TopicDefinitionError
from app.topics.safety import TopicTextError

__all__ = [
    "ACCEPTED_MEDIA_TYPE",
    "NO_STORE",
    "busy",
    "ok",
    "read_limited",
    "reported_neurons",
    "safety_error",
    "topic_error",
]

NO_STORE: Final = {"Cache-Control": "no-store"}
ACCEPTED_MEDIA_TYPE: Final = "application/json"
_USAGE_FIELDS: Final = 2


def busy() -> JSONResponse:
    return limited("busy", 503, BUSY_RETRY_AFTER_SECONDS)


def ok(body: dict[str, object]) -> JSONResponse:
    return JSONResponse(body, headers=NO_STORE)


def topic_error(error: TopicTextError | TopicDefinitionError) -> JSONResponse:
    body: dict[str, object] = {"error": error.code}
    if isinstance(error, TopicTextError):
        if error.field is not None:
            body["field"] = error.field
        if error.spans:
            body["spans"] = [list(span) for span in error.spans]
    return JSONResponse(body, status_code=422)


def safety_error(error: SafetyRunError) -> JSONResponse:
    if error.code == UNMASKED:
        spans = [list(span) for span in error.spans]
        return JSONResponse({"error": error.code, "spans": spans}, status_code=422)
    status = 409 if error.code == MISMATCH else 504 if error.code == SAFETY_TIMEOUT else 422
    return error_response(error.code, status)


async def read_limited(
    request: Request, declared: int, settings: Settings, cap: int
) -> bytes | Response:
    try:
        return await read_body(
            request, declared, settings, max_bytes=cap, too_large_code="request_too_large"
        )
    except BodyRejectedError as rejected:
        return early_error(rejected.code, rejected.status)


def reported_neurons(provider: AIProvider) -> int | None:
    """The Neurons the provider reported so far, ``None`` when it reports no usage."""
    usage = getattr(provider, "usage", None)
    if not (isinstance(usage, tuple) and len(usage) == _USAGE_FIELDS):
        return None
    return usage_neurons(*usage)
