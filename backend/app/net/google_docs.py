"""Fetch a public Google Docs document as DOCX (S3-T6a, threat model T2, T7).

``fetch_google_doc`` builds the export URL from a validated ID only, sends a fixed set of
headers, follows at most three redirects itself (each target is checked), reads the body
raw with a size cap, and has one total deadline. Every ``httpx`` and guard error becomes a
``GoogleDocError`` with a fixed code (``raise ... from None``). The text of such an error
can hold the URL or an IP address, so it is never logged or returned. The ID is a
password for the document: it is in no log and no error.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from typing import Final

import httpx

from app.net.client import ClientFactory
from app.net.guard import BlockedAddressError, BlockedHostError

DOCS_HOST: Final = "docs.google.com"
LOGIN_HOST: Final = "accounts.google.com"
DOCX_MEDIA_TYPE: Final = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
USER_AGENT: Final = "AIContrast/0.1"
MAX_REDIRECTS: Final = 3

NOT_PUBLIC: Final = "google_doc_not_public"
NOT_FOUND: Final = "google_doc_not_found"
TOO_LARGE: Final = "google_doc_too_large"
UNAVAILABLE: Final = "google_doc_unavailable"
TIMEOUT: Final = "google_doc_timeout"
INVALID_ID: Final = "invalid_google_doc_id"

_ID_RE: Final = re.compile(r"[A-Za-z0-9_-]{25,100}", re.ASCII)
_USERCONTENT_RE: Final = re.compile(r"doc-[a-z0-9-]{1,60}-docs\.googleusercontent\.com", re.ASCII)
_REDIRECT_STATUSES: Final = frozenset({301, 302, 303, 307, 308})
_HTTPS_PORT: Final = 443
_OK: Final = 200
_UNAUTHORIZED: Final = 401
_FORBIDDEN: Final = 403
_NOT_FOUND_STATUS: Final = 404


class GoogleDocError(Exception):
    """A fetch failed. ``code`` is a fixed error code; the message is the code only."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def is_valid_document_id(value: str) -> bool:
    return _ID_RE.fullmatch(value) is not None


def _media_type(value: str | None) -> str:
    return "" if value is None else value.split(";", 1)[0].strip().lower()


def _next_url(response: httpx.Response) -> httpx.URL:
    location = response.headers.get("location")
    if not location:
        raise GoogleDocError(UNAVAILABLE)
    try:
        target = response.request.url.join(location)
    except httpx.InvalidURL:
        raise GoogleDocError(UNAVAILABLE) from None
    if target.scheme != "https" or target.userinfo or target.port not in (None, _HTTPS_PORT):
        raise GoogleDocError(UNAVAILABLE)
    if target.host == LOGIN_HOST:
        raise GoogleDocError(NOT_PUBLIC)
    if target.host != DOCS_HOST and _USERCONTENT_RE.fullmatch(target.host) is None:
        raise GoogleDocError(UNAVAILABLE)
    return target


def _check_status(response: httpx.Response) -> None:
    status = response.status_code
    if status != _OK:
        if status in (_UNAUTHORIZED, _FORBIDDEN):
            raise GoogleDocError(NOT_PUBLIC)
        if status == _NOT_FOUND_STATUS:
            raise GoogleDocError(NOT_FOUND)
        raise GoogleDocError(UNAVAILABLE)
    media_type = _media_type(response.headers.get("content-type"))
    if media_type == "text/html":
        raise GoogleDocError(NOT_PUBLIC)
    if media_type != DOCX_MEDIA_TYPE:
        raise GoogleDocError(UNAVAILABLE)
    encoding = response.headers.get("content-encoding")
    if encoding is not None and encoding.strip().lower() != "identity":
        raise GoogleDocError(UNAVAILABLE)


async def _raw_chunks(response: httpx.Response) -> AsyncIterator[bytes]:
    if response.is_stream_consumed:
        # A response built in memory (a test transport) holds its bytes already.
        yield response.content
        return
    async for chunk in response.aiter_raw():
        yield chunk


async def _read_body(response: httpx.Response, max_bytes: int) -> bytes:
    declared = response.headers.get("content-length", "").strip()
    if declared.isascii() and declared.isdigit() and int(declared) > max_bytes:
        raise GoogleDocError(TOO_LARGE)
    body = bytearray()
    async for chunk in _raw_chunks(response):
        body += chunk
        if len(body) > max_bytes:
            raise GoogleDocError(TOO_LARGE)
    return bytes(body)


async def _fetch(client: httpx.AsyncClient, document_id: str, max_bytes: int) -> bytes:
    url = httpx.URL(f"https://{DOCS_HOST}/document/d/{document_id}/export?format=docx")
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": DOCX_MEDIA_TYPE,
        "Accept-Encoding": "identity",
    }
    for hop in range(MAX_REDIRECTS + 1):
        client.cookies.clear()
        response = await client.send(client.build_request("GET", url, headers=headers), stream=True)
        try:
            if response.status_code in _REDIRECT_STATUSES:
                if hop == MAX_REDIRECTS:
                    raise GoogleDocError(UNAVAILABLE)
                url = _next_url(response)
                continue
            _check_status(response)
            return await _read_body(response, max_bytes)
        finally:
            await response.aclose()
    raise GoogleDocError(UNAVAILABLE)  # pragma: no cover - the loop always returns or raises


async def fetch_google_doc(
    document_id: str,
    *,
    max_bytes: int,
    timeout_seconds: float,
    client_factory: ClientFactory,
) -> bytes:
    """Return the raw DOCX bytes or raise ``GoogleDocError`` (fixed ``code``)."""
    if not is_valid_document_id(document_id):
        raise GoogleDocError(INVALID_ID)
    try:
        async with asyncio.timeout(timeout_seconds), client_factory() as client:
            return await _fetch(client, document_id, max_bytes)
    except TimeoutError:
        raise GoogleDocError(TIMEOUT) from None
    except httpx.TimeoutException:
        raise GoogleDocError(TIMEOUT) from None
    except (httpx.HTTPError, httpx.InvalidURL, BlockedHostError, BlockedAddressError):
        raise GoogleDocError(UNAVAILABLE) from None
