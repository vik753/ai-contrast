"""Helpers shared by the adapters. Every function here is private: no content parameters."""

from __future__ import annotations

import json
import logging
from typing import Final, NoReturn

from app.ai.port import AIError, AIErrorCode, ModelJson
from app.net.ai_client import RedirectRefusedError, ResponseTooLargeError
from app.net.guard import BlockedAddressError, BlockedHostError

CONNECT_TIMEOUT_SECONDS: Final = 5.0
CHECK_TIMEOUT_SECONDS: Final = 20.0
COMPLETE_TIMEOUT_SECONDS: Final = 120.0

_SDK_LOGGERS: Final = ("anthropic", "openai", "httpx2", "httpcore2")
_CHAIN_DEPTH: Final = 8
_HTTP_UNAUTHORIZED: Final = frozenset({401, 403})
_HTTP_CLIENT_ERROR_MIN: Final = 400
_HTTP_TIMEOUT: Final = 408
_HTTP_NOT_FOUND: Final = 404
_HTTP_RATE_LIMITED: Final = 429
_HTTP_SERVER_ERROR: Final = 500


def _quiet_sdk_loggers() -> None:
    """The SDKs raise their log level when ``ANTHROPIC_LOG`` / ``OPENAI_LOG`` is set (T1)."""
    for name in _SDK_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def _causes(error: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and len(chain) < _CHAIN_DEPTH:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _status_code(status: int) -> AIErrorCode:
    if status in _HTTP_UNAUTHORIZED:
        return AIErrorCode.PROVIDER_AUTH_FAILED
    if status == _HTTP_NOT_FOUND:
        return AIErrorCode.PROVIDER_MODEL_NOT_FOUND
    if status == _HTTP_RATE_LIMITED:
        return AIErrorCode.PROVIDER_RATE_LIMITED
    if _HTTP_CLIENT_ERROR_MIN <= status < _HTTP_SERVER_ERROR and status != _HTTP_TIMEOUT:
        return AIErrorCode.PROVIDER_BAD_REQUEST
    return AIErrorCode.PROVIDER_UNAVAILABLE


def _map_error(error: BaseException) -> AIErrorCode:
    """Map any SDK or transport error to one of our codes. The error text is never used."""
    chain = _causes(error)
    if any(isinstance(e, BlockedHostError | BlockedAddressError) for e in chain):
        return AIErrorCode.PROVIDER_BLOCKED_HOST
    if any(
        isinstance(e, RedirectRefusedError | ResponseTooLargeError)
        or type(e).__name__ == "APIResponseValidationError"
        for e in chain
    ):
        return AIErrorCode.PROVIDER_BAD_RESPONSE
    status = next((s for e in chain if isinstance(s := getattr(e, "status_code", None), int)), 0)
    return _status_code(status)


def _error_for(error: BaseException) -> AIError:
    """The ``AIError`` to raise for ``error`` (raise it ``from None``)."""
    if isinstance(error, AIError):
        return error
    return AIError(_map_error(error))


def _bad_response() -> NoReturn:
    raise AIError(AIErrorCode.PROVIDER_BAD_RESPONSE) from None


def _reject_constant(name: str) -> NoReturn:
    raise ValueError(name)


def _load_object(data: bytes | str) -> dict[str, object]:
    """Parse a JSON object (strict: no NaN, no other top-level type)."""
    try:
        value = json.loads(data, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        _bad_response()
    if not isinstance(value, dict):
        _bad_response()
    return value


def _model_json(text: str) -> ModelJson:
    return _load_object(text)
