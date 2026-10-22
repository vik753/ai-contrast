"""S3-T6a items 5 and part of 7: ``fetch_google_doc`` (app/net/google_docs.py).

Public interface: ``fetch_google_doc(document_id, *, max_bytes, timeout_seconds,
client_factory) -> bytes``; ``GoogleDocError(code)``; ``is_valid_document_id``.
The flow is tested with ``StreamingTransport`` (a mock transport whose answers stream; no
network, no guard: the guard has its own tests). The factory builds a plain
``httpx.AsyncClient`` over the mock transport, with
``follow_redirects`` at its default (off), so the fetcher must follow redirects itself.
Must fail before the implementation exists (module ``app.net.google_docs`` is missing).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest

from app.net.google_docs import GoogleDocError, fetch_google_doc, is_valid_document_id
from app.net.guard import BlockedAddressError, BlockedHostError
from tests.helpers import new_canary
from tests.netfakes import StreamingTransport

DOC_ID = "a1B2c3D4e5F6g7H8i9J0k1L2m3"
DOCX_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
EXPORT_URL = f"https://docs.google.com/document/d/{DOC_ID}/export?format=docx"
DOCX_BYTES = b"PK\x03\x04" + b"synthetic docx body " * 10
GOOGLEUSERCONTENT = "https://doc-0k-0s-docs.googleusercontent.com/export/abc/def?id=1"

Handler = Callable[[httpx.Request], Any]


class Harness:
    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.requests: list[httpx.Request] = []
        self.clients: list[httpx.AsyncClient] = []

    def _handle(self, request: httpx.Request) -> Any:
        self.requests.append(request)
        return self.handler(request)

    def factory(self) -> httpx.AsyncClient:
        client = httpx.AsyncClient(transport=StreamingTransport(self._handle))
        self.clients.append(client)
        return client


def fetch(
    handler: Handler,
    *,
    document_id: str = DOC_ID,
    max_bytes: int = 1000,
    timeout: float = 5,
) -> tuple[bytes | GoogleDocError, Harness]:
    harness = Harness(handler)

    async def go() -> bytes | GoogleDocError:
        try:
            return await fetch_google_doc(
                document_id,
                max_bytes=max_bytes,
                timeout_seconds=timeout,
                client_factory=harness.factory,
            )
        except GoogleDocError as error:
            return error

    return asyncio.run(go()), harness


def ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, headers={"Content-Type": DOCX_CT}, content=DOCX_BYTES)


def redirect(location: str, status: int = 302, **headers: str) -> httpx.Response:
    return httpx.Response(status, headers={"Location": location, **headers})


def code_of(result: bytes | GoogleDocError) -> str:
    assert isinstance(result, GoogleDocError), result
    return result.code


# --- ID validation ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["a" * 25, "a" * 100, DOC_ID, "A-_" + "0" * 22, "1" * 44],
)
def test_is_valid_document_id_accepts(value: str) -> None:
    assert is_valid_document_id(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "",
        "a" * 24,
        "a" * 101,
        "a" * 25 + "\n",
        "\n" + "a" * 25,
        "a" * 24 + " ",
        "a" * 24 + "/",
        "a" * 24 + ".",
        "a" * 12 + "%2e" + "a" * 12,
        "a" * 24 + "\u0663",
        "a" * 24 + "\uff41",
        "../" + "a" * 25,
        "a" * 24 + "?",
        "a" * 24 + "\x00",
    ],
)
def test_is_valid_document_id_rejects(value: str) -> None:
    assert is_valid_document_id(value) is False


def test_google_doc_error_carries_code_attribute() -> None:
    assert GoogleDocError("google_doc_timeout").code == "google_doc_timeout"


@pytest.mark.parametrize("bad", ["short", "a" * 25 + "\n", "a" * 24 + "/x", "a" * 101])
def test_fetch_invalid_id_raises_before_any_request(bad: str) -> None:
    result, harness = fetch(ok, document_id=bad)

    assert code_of(result) == "invalid_google_doc_id"
    assert harness.requests == []


# --- request ----------------------------------------------------------------------------


def test_fetch_success_returns_raw_body_and_requests_the_exact_export_url() -> None:
    result, harness = fetch(ok)

    assert result == DOCX_BYTES
    assert [str(r.url) for r in harness.requests] == [EXPORT_URL]
    assert harness.requests[0].method == "GET"
    assert harness.requests[0].content == b""


def test_fetch_request_headers_are_exactly_the_fixed_set() -> None:
    _, harness = fetch(ok)

    headers = harness.requests[0].headers
    # httpx adds `host` and `connection`; nothing else may be present.
    assert set(headers) <= {"host", "connection", "user-agent", "accept", "accept-encoding"}
    assert headers["accept"] == DOCX_CT
    assert headers["accept-encoding"] == "identity"
    assert headers["user-agent"]
    assert not headers["user-agent"].startswith("python-httpx")


@pytest.mark.parametrize("name", ["cookie", "authorization", "referer", "x-provider-key"])
def test_fetch_request_never_carries_credential_headers(name: str) -> None:
    _, harness = fetch(ok)

    assert name not in harness.requests[0].headers


def test_fetch_request_never_sets_sni_hostname_extension() -> None:
    _, harness = fetch(
        lambda r: redirect(GOOGLEUSERCONTENT) if r.url.host == "docs.google.com" else ok(r)
    )

    assert len(harness.requests) == 2
    assert all("sni_hostname" not in r.extensions for r in harness.requests)


def test_fetch_headers_identical_on_every_hop() -> None:
    _, harness = fetch(
        lambda r: redirect(GOOGLEUSERCONTENT) if r.url.host == "docs.google.com" else ok(r)
    )

    first, second = harness.requests
    for name in ("user-agent", "accept", "accept-encoding"):
        assert first.headers[name] == second.headers[name]
    assert "cookie" not in second.headers
    assert "referer" not in second.headers


def test_fetch_client_is_closed_after_success_and_after_failure() -> None:
    _, harness_ok = fetch(ok)
    _, harness_bad = fetch(lambda r: httpx.Response(404))

    assert len(harness_ok.clients) == 1
    assert len(harness_bad.clients) == 1
    assert all(c.is_closed for c in harness_ok.clients + harness_bad.clients)


# --- redirects --------------------------------------------------------------------------


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_fetch_follows_redirect_statuses(status: int) -> None:
    result, harness = fetch(
        lambda r: redirect(GOOGLEUSERCONTENT, status) if r.url.host == "docs.google.com" else ok(r)
    )

    assert result == DOCX_BYTES
    assert [r.url.host for r in harness.requests] == [
        "docs.google.com",
        "doc-0k-0s-docs.googleusercontent.com",
    ]


def test_fetch_relative_location_is_resolved_against_current_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/redir2":
            return ok(request)
        return redirect("/redir2")

    result, harness = fetch(handler)

    assert result == DOCX_BYTES
    assert str(harness.requests[1].url) == "https://docs.google.com/redir2"


@pytest.mark.parametrize(
    "location",
    [
        "https://docs.google.com/document/d/x/export",
        "https://docs.google.com:443/document/d/x/export",
        "https://doc-0k-0s-docs.googleusercontent.com/export/a",
        "https://doc-a-docs.googleusercontent.com/export/a",
        "https://doc-" + "a" * 60 + "-docs.googleusercontent.com/x",
        "/relative/path",
    ],
)
def test_fetch_allowed_redirect_target_is_followed(location: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return redirect(location) if len(harness_requests) == 1 else ok(request)

    harness_requests: list[httpx.Request] = []

    def counting(request: httpx.Request) -> httpx.Response:
        harness_requests.append(request)
        return handler(request)

    result, _ = fetch(counting)

    assert result == DOCX_BYTES
    assert len(harness_requests) == 2


@pytest.mark.parametrize(
    "location",
    [
        "http://docs.google.com/document/d/x/export",
        "https://docs.google.com:8443/x",
        "https://docs.google.com:80/x",
        "https://user@docs.google.com/x",
        "https://user:pass@docs.google.com/x",
        "https://docs.google.com.evil.example/x",
        "https://evildocs.google.com/x",
        "https://evil.example/x",
        "//evil.example/x",
        "ftp://docs.google.com/x",
        "file:///etc/passwd",
        "https://127.0.0.1/x",
        "https://[::1]/x",
        "https://169.254.169.254/latest/meta-data",
        "https://localhost/x",
        "https://drive.google.com/x",
        "https://docs.googleusercontent.com/x",
        "https://lh3.googleusercontent.com/x",
        "https://doc-0k-0s-docs.googleusercontent.com.evil.example/x",
        "https://doc-0k-0s-docs.googleusercontent.com@evil.example/x",
        "https://doc--docs.googleusercontent.com/x",
        "https://doc-" + "a" * 61 + "-docs.googleusercontent.com/x",
        "https://doc-0k_0s-docs.googleusercontent.com/x",
        "https://xdoc-0k-docs.googleusercontent.com/x",
        "https://doc-0k-docs.googleusercontent.com.",
        "",
    ],
)
def test_fetch_disallowed_redirect_target_is_not_requested(location: str) -> None:
    result, harness = fetch(lambda r: redirect(location))

    assert code_of(result) == "google_doc_unavailable"
    assert len(harness.requests) == 1


@pytest.mark.parametrize(
    "location",
    [
        "https://accounts.google.com/ServiceLogin?continue=https%3A%2F%2Fdocs.google.com",
        "https://accounts.google.com/v3/signin/identifier",
    ],
)
def test_fetch_redirect_to_accounts_google_means_not_public(location: str) -> None:
    result, harness = fetch(lambda r: redirect(location))

    assert code_of(result) == "google_doc_not_public"
    assert len(harness.requests) == 1


def test_fetch_redirect_without_location_is_unavailable() -> None:
    result, _ = fetch(lambda r: httpx.Response(302))

    assert code_of(result) == "google_doc_unavailable"


def _chain(hops: int) -> Callable[[httpx.Request], httpx.Response]:
    count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        if count <= hops:
            return redirect(f"/hop{count}")
        return ok(request)

    return handler


def test_fetch_three_redirects_are_followed() -> None:
    result, harness = fetch(_chain(3))

    assert result == DOCX_BYTES
    assert len(harness.requests) == 4


def test_fetch_fourth_redirect_is_refused_and_not_followed() -> None:
    result, harness = fetch(_chain(4))

    assert code_of(result) == "google_doc_unavailable"
    assert len(harness.requests) == 4


def test_fetch_redirect_loop_is_bounded() -> None:
    result, harness = fetch(lambda r: redirect("/same"))

    assert code_of(result) == "google_doc_unavailable"
    assert len(harness.requests) == 4


def test_fetch_cookies_set_by_a_response_are_not_sent_on_the_next_hop() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/next":
            return ok(request)
        return redirect("/next", **{"Set-Cookie": "NID=secret-cookie; Path=/; Secure"})

    result, harness = fetch(handler)

    assert result == DOCX_BYTES
    assert len(harness.requests) == 2
    assert "cookie" not in harness.requests[1].headers
    assert "secret-cookie" not in str(harness.requests[1].headers)


def test_fetch_cookies_cleared_on_every_hop_of_a_chain() -> None:
    count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        if count <= 3:
            return redirect(f"/h{count}", **{"Set-Cookie": f"c{count}=v{count}; Path=/"})
        return ok(request)

    result, harness = fetch(handler)

    assert result == DOCX_BYTES
    assert all("cookie" not in r.headers for r in harness.requests)


# --- status and media type --------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "google_doc_not_public"),
        (403, "google_doc_not_public"),
        (404, "google_doc_not_found"),
        (400, "google_doc_unavailable"),
        (402, "google_doc_unavailable"),
        (405, "google_doc_unavailable"),
        (410, "google_doc_unavailable"),
        (429, "google_doc_unavailable"),
        (500, "google_doc_unavailable"),
        (502, "google_doc_unavailable"),
        (503, "google_doc_unavailable"),
        (504, "google_doc_unavailable"),
        (204, "google_doc_unavailable"),
        (206, "google_doc_unavailable"),
        (304, "google_doc_unavailable"),
    ],
)
def test_fetch_status_maps_to_error_code(status: int, code: str) -> None:
    result, harness = fetch(lambda r: httpx.Response(status, headers={"Content-Type": DOCX_CT}))

    assert code_of(result) == code
    assert len(harness.requests) == 1


@pytest.mark.parametrize("content_type", ["text/html", "text/html; charset=utf-8", "TEXT/HTML"])
def test_fetch_200_html_means_not_public(content_type: str) -> None:
    result, _ = fetch(
        lambda r: httpx.Response(200, headers={"Content-Type": content_type}, content=b"<html>")
    )

    assert code_of(result) == "google_doc_not_public"


@pytest.mark.parametrize(
    "content_type",
    ["application/octet-stream", "application/pdf", "application/json", "text/plain", "image/png"],
)
def test_fetch_200_other_media_type_is_unavailable(content_type: str) -> None:
    result, _ = fetch(
        lambda r: httpx.Response(200, headers={"Content-Type": content_type}, content=DOCX_BYTES)
    )

    assert code_of(result) == "google_doc_unavailable"


def test_fetch_200_without_content_type_is_unavailable() -> None:
    result, _ = fetch(lambda r: httpx.Response(200, content=DOCX_BYTES))

    assert code_of(result) == "google_doc_unavailable"


def test_fetch_200_docx_media_type_with_any_case_is_read() -> None:
    result, _ = fetch(
        lambda r: httpx.Response(200, headers={"Content-Type": DOCX_CT.upper()}, content=DOCX_BYTES)
    )

    assert result == DOCX_BYTES


def test_fetch_content_disposition_is_ignored() -> None:
    result, _ = fetch(
        lambda r: httpx.Response(
            200,
            headers={"Content-Type": DOCX_CT, "Content-Disposition": 'attachment; filename="x"'},
            content=DOCX_BYTES,
        )
    )

    assert result == DOCX_BYTES


# --- body: encoding and caps ------------------------------------------------------------


@pytest.mark.parametrize("encoding", ["gzip", "br", "deflate", "zstd", "gzip, identity", "x-foo"])
def test_fetch_content_encoding_other_than_identity_is_unavailable(encoding: str) -> None:
    result, _ = fetch(
        lambda r: httpx.Response(
            200, headers={"Content-Type": DOCX_CT, "Content-Encoding": encoding}, content=b"x" * 10
        )
    )

    assert code_of(result) == "google_doc_unavailable"


def test_fetch_content_encoding_identity_is_accepted_and_body_untouched() -> None:
    result, _ = fetch(
        lambda r: httpx.Response(
            200,
            headers={"Content-Type": DOCX_CT, "Content-Encoding": "identity"},
            content=DOCX_BYTES,
        )
    )

    assert result == DOCX_BYTES


class Chunks:
    """A response body of ``count`` chunks that records how many were pulled."""

    def __init__(self, count: int, size: int, delay: float = 0) -> None:
        self.count, self.size, self.delay = count, size, delay
        self.pulled = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for _ in range(self.count):
            self.pulled += 1
            yield b"x" * self.size
            if self.delay:
                await asyncio.sleep(self.delay)


def test_fetch_body_of_exactly_max_bytes_is_accepted() -> None:
    body = b"P" * 1000
    result, _ = fetch(
        lambda r: httpx.Response(200, headers={"Content-Type": DOCX_CT}, content=body),
        max_bytes=1000,
    )

    assert result == body


def test_fetch_body_one_byte_over_max_is_too_large() -> None:
    result, _ = fetch(
        lambda r: httpx.Response(200, headers={"Content-Type": DOCX_CT}, content=b"P" * 1001),
        max_bytes=1000,
    )

    assert code_of(result) == "google_doc_too_large"


def test_fetch_content_length_above_max_is_too_large_without_reading_the_body() -> None:
    chunks = Chunks(count=10, size=100)
    result, _ = fetch(
        lambda r: httpx.Response(
            200,
            headers={"Content-Type": DOCX_CT, "Content-Length": "5000"},
            content=chunks,
        ),
        max_bytes=1000,
    )

    assert code_of(result) == "google_doc_too_large"
    assert chunks.pulled == 0


def test_fetch_stream_without_length_stops_reading_at_the_cap() -> None:
    chunks = Chunks(count=1000, size=100)
    result, _ = fetch(
        lambda r: httpx.Response(200, headers={"Content-Type": DOCX_CT}, content=chunks),
        max_bytes=1000,
    )

    assert code_of(result) == "google_doc_too_large"
    assert chunks.pulled <= 12


def test_fetch_stream_longer_than_its_content_length_is_too_large() -> None:
    chunks = Chunks(count=100, size=100)
    result, _ = fetch(
        lambda r: httpx.Response(
            200, headers={"Content-Type": DOCX_CT, "Content-Length": "10"}, content=chunks
        ),
        max_bytes=1000,
    )

    assert code_of(result) == "google_doc_too_large"
    assert chunks.pulled <= 12


# --- deadline ---------------------------------------------------------------------------


def test_fetch_slow_response_headers_hit_the_total_deadline() -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(10)
        return ok(request)

    started = time.monotonic()
    result, _ = fetch(slow, timeout=0.2)

    assert code_of(result) == "google_doc_timeout"
    assert time.monotonic() - started < 3


def test_fetch_slow_trickling_body_hits_the_total_deadline() -> None:
    chunks = Chunks(count=1000, size=1, delay=0.05)
    started = time.monotonic()
    result, _ = fetch(
        lambda r: httpx.Response(200, headers={"Content-Type": DOCX_CT}, content=chunks),
        max_bytes=10_000,
        timeout=0.3,
    )

    assert code_of(result) == "google_doc_timeout"
    assert time.monotonic() - started < 3


def test_fetch_deadline_covers_the_whole_redirect_chain() -> None:
    async def slow_hops(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.15)
        return redirect("/again")

    started = time.monotonic()
    result, _ = fetch(slow_hops, timeout=0.4)

    assert code_of(result) == "google_doc_timeout"
    assert time.monotonic() - started < 3


# --- error mapping and error text -------------------------------------------------------


def _raiser(error: Exception) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error

    return handler


@pytest.mark.parametrize(
    "make_error",
    [
        httpx.ConnectError,
        httpx.RemoteProtocolError,
        BlockedAddressError,
        BlockedHostError,
    ],
    ids=["connect", "protocol", "blocked-address", "blocked-host"],
)
def test_fetch_transport_and_guard_errors_map_to_unavailable_without_leaking_text(
    make_error: Callable[[str], Exception],
) -> None:
    secret = f"{EXPORT_URL} 10.1.2.3 internal.example {new_canary()}"

    result, _ = fetch(_raiser(make_error(secret)))

    assert code_of(result) == "google_doc_unavailable"
    assert isinstance(result, GoogleDocError)
    for text in (str(result), repr(result), repr(result.args)):
        for part in (DOC_ID, "10.1.2.3", "internal.example", "docs.google.com", "CANARY"):
            assert part not in text
    assert result.__cause__ is None
    assert result.__suppress_context__ is True


def test_fetch_error_text_never_contains_the_id_for_any_code() -> None:
    results = [
        fetch(lambda r: httpx.Response(403))[0],
        fetch(lambda r: httpx.Response(404))[0],
        fetch(lambda r: httpx.Response(500))[0],
        fetch(lambda r: redirect("https://evil.example/x"))[0],
        fetch(
            lambda r: httpx.Response(200, headers={"Content-Type": DOCX_CT}, content=b"x" * 2000)
        )[0],
    ]

    for result in results:
        assert isinstance(result, GoogleDocError)
        assert DOC_ID not in str(result) + repr(result)
        assert "evil.example" not in str(result) + repr(result)
