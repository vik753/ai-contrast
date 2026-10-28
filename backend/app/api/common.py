"""Helpers shared by the extraction endpoints (``/api/extract``, ``/api/extract/google-doc``).

Public module: no endpoint imports a private name of another endpoint. It holds the typed
accessors of ``app.state``, the error responses, the sandbox and archive limits taken from
the settings, and ``SlotResponse``, which runs the work of a request under one extraction
slot (threat model T6 control 9).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Final

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.requests import ClientDisconnect
from starlette.types import Receive, Scope, Send

from app.extraction.detect import ZipLimits
from app.extraction.limiter import ExtractionLimiter
from app.extraction.model import MIB
from app.extraction.sandbox import SandboxLimits
from app.http_limits import declared_length
from app.net.client import ClientFactory
from app.settings import Settings

RETRY_AFTER_SECONDS: Final = 5
CLOSE: Final = {"Connection": "close"}
SEND_CHUNK_BYTES: Final = 64 * 1024
# How late a stalled stream may be detected after its rate falls below the minimum.
RATE_TICK_SECONDS: Final = 1.0


def error_response(code: str, status: int, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"error": code}, status_code=status, headers=headers)


def early_error(code: str, status: int, headers: dict[str, str] | None = None) -> JSONResponse:
    """An answer sent before the whole body is read: the connection is closed."""
    return error_response(code, status, {**CLOSE, **(headers or {})})


def media_type(content_type: str | None) -> str:
    """The media type of a ``Content-Type`` value: no parameters, lower case."""
    if content_type is None:
        return ""
    return content_type.split(";", 1)[0].strip().lower()


def app_state(request: Request) -> tuple[Settings, ExtractionLimiter]:
    settings = getattr(request.app.state, "settings", None)
    limiter = getattr(request.app.state, "extraction_limiter", None)
    if not isinstance(settings, Settings) or not isinstance(limiter, ExtractionLimiter):
        msg = "app state is not configured"
        raise TypeError(msg)
    return settings, limiter


class BodyRejectedError(Exception):
    """The body read stopped early. ``status`` and ``code`` describe the answer."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


def check_upload_headers(
    request: Request, *, max_bytes: int, too_large_code: str, accepted_media_type: str
) -> JSONResponse | int:
    """Order of header checks of the upload endpoints, from the headers alone.

    Any ``Transfer-Encoding`` or no plain decimal ``Content-Length`` gives ``411``;
    a length above ``max_bytes`` gives ``413`` (``too_large_code``); another media type
    gives ``415``. Every answer is an early error. Returns the declared length otherwise.
    """
    if "transfer-encoding" in request.headers:
        return early_error("length_required", 411)
    length = declared_length(request.headers)
    if length is None:
        return early_error("length_required", 411)
    if length > max_bytes:
        return early_error(too_large_code, 413)
    if media_type(request.headers.get("content-type")) != accepted_media_type:
        return early_error("unsupported_media_type", 415)
    return length


async def read_body(
    request: Request, declared: int, settings: Settings, *, max_bytes: int, too_large_code: str
) -> bytes:
    """Read exactly ``declared`` bytes into one pre-allocated buffer.

    ``declared`` is at most ``max_bytes`` (checked by the caller). Raises
    ``BodyRejectedError`` for 413 (``too_large_code``), 400 and 408, ``ClientDisconnect``
    if the client leaves.

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
                if end > max_bytes:
                    raise BodyRejectedError(413, too_large_code)
                if end > declared:
                    raise BodyRejectedError(400, "length_mismatch")
                buffer[received:end] = chunk
                received = end
                if not more_body:
                    break
                now = loop.time()
                if now > grace_end and received < min_rate * (now - start):
                    raise BodyRejectedError(408, "upload_timeout")
                fail_at = max(grace_end, start + received / min_rate)
                wake = timer.when()
                if wake is not None and fail_at > wake and wake < deadline:
                    timer.reschedule(min(deadline, fail_at + RATE_TICK_SECONDS))
    except TimeoutError:
        raise BodyRejectedError(408, "upload_timeout") from None
    if received != declared:
        raise BodyRejectedError(400, "length_mismatch")
    return bytes(buffer)


def google_client_factory(request: Request) -> ClientFactory:
    """The outbound client factory of the app (tests replace it), validated."""
    factory = getattr(request.app.state, "google_client_factory", None)
    if not callable(factory):
        msg = "app state is not configured"
        raise TypeError(msg)
    return factory  # type: ignore[no-any-return]


def zip_limits(settings: Settings) -> ZipLimits:
    return ZipLimits(
        max_entries=settings.max_zip_entries,
        max_uncompressed_bytes=settings.max_zip_uncompressed_bytes,
        max_ratio=settings.max_zip_ratio,
    )


def sandbox_limits(settings: Settings) -> SandboxLimits:
    return SandboxLimits(
        memory_bytes=settings.extract_worker_memory_mb * MIB,
        cpu_seconds=settings.extract_worker_cpu_seconds,
        wall_seconds=settings.extract_worker_wall_seconds,
        max_result_bytes=settings.extract_max_result_bytes,
        max_text_chars=settings.extract_max_text_chars,
        max_blocks=settings.extract_max_blocks,
        docx_max_part_bytes=settings.max_docx_part_bytes,
        docx_max_total_bytes=settings.max_zip_uncompressed_bytes,
        docx_max_xml_depth=settings.max_docx_xml_depth,
        docx_max_elements=settings.max_docx_elements,
        pdf_max_pages=settings.max_pdf_pages,
        pdf_max_prev_chain=settings.max_pdf_prev_chain,
    )


async def send_in_chunks(response: Response, send: Send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": response.status_code,
            "headers": response.raw_headers,
        }
    )
    body = memoryview(response.body)
    for offset in range(0, len(body), SEND_CHUNK_BYTES):
        end = offset + SEND_CHUNK_BYTES
        await send(
            {
                "type": "http.response.body",
                "body": bytes(body[offset:end]),
                "more_body": end < len(body),
            }
        )
    if not body:
        await send({"type": "http.response.body", "body": b"", "more_body": False})


class SlotResponse(Response):
    """Takes the extraction slot, runs ``work`` and sends its response, all under one slot.

    The work runs when the response is called, not in the handler, so the slot is taken
    and released inside one ``with`` block and covers sending the last byte (threat model
    T6 control 9). ``work`` reads the request body, if there is one, so the body read is
    under the slot too. Without a free slot the answer is ``503 busy`` with
    ``Retry-After`` and ``Connection: close``, and no body byte is read. Sending has a
    deadline (``EXTRACT_SEND_TIMEOUT_SECONDS``); a client that does not read is cut off:
    the app returns before the response is complete, and the server closes the
    connection. The body goes out in chunks of ``SEND_CHUNK_BYTES``, so a stalled
    connection keeps at most about one chunk in the server's write buffer.
    """

    def __init__(
        self,
        settings: Settings,
        limiter: ExtractionLimiter,
        work: Callable[[], Awaitable[Response]],
        *,
        logger: logging.Logger,
        send_timeout_event: str,
    ) -> None:
        super().__init__()
        self._settings = settings
        self._limiter = limiter
        self._work = work
        self._logger = logger
        self._send_timeout_event = send_timeout_event

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        slot = self._limiter.try_slot()
        if slot is None:
            busy = early_error("busy", 503, {"Retry-After": str(RETRY_AFTER_SECONDS)})
            await busy(scope, receive, send)
            return
        with slot:
            response = await self._work()
            try:
                async with asyncio.timeout(self._settings.extract_send_timeout_seconds):
                    await send_in_chunks(response, send)
            except TimeoutError:
                self._logger.info(self._send_timeout_event)
