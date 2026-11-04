"""S3-T6a item 6: ``POST /api/extract/google-doc`` (app/api/google_doc.py).

Override mechanism chosen for the client factory (the developer follows it): the endpoint
reads ``request.app.state.google_client_factory``, a ``Callable[[], httpx2.AsyncClient]``.
``create_app`` sets the production factory
(``outbound_client(connect_timeout=settings.google_connect_timeout_seconds,
read_timeout=10)``); these tests replace the attribute after ``create_app``.
The endpoint calls ``fetch_google_doc(..., max_bytes=settings.max_file_bytes,
timeout_seconds=settings.google_fetch_timeout_seconds, client_factory=...)``.
Must fail before the implementation exists (the route is missing).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import httpx2
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.docxbuild import CLAUSE, Package, body_docx, build_docx, document_xml, para
from tests.helpers import new_marker
from tests.netfakes import StreamingTransport

PATH = "/api/extract/google-doc"
DOC_ID = "a1B2c3D4e5F6g7H8i9J0k1L2m3"
DOCX_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOCX = body_docx(para(CLAUSE))
JSON_HEADERS = {"Content-Type": "application/json"}

Handler = Callable[[httpx2.Request], Any]


class Setup:
    def __init__(self, app: FastAPI, client: TestClient) -> None:
        self.app = app
        self.client = client
        self.requests: list[httpx2.Request] = []
        self.factory_calls = 0

    def use(self, handler: Handler) -> None:
        def handle(request: httpx2.Request) -> Any:
            self.requests.append(request)
            return handler(request)

        def factory() -> httpx2.AsyncClient:
            self.factory_calls += 1
            return httpx2.AsyncClient(transport=StreamingTransport(handle))

        self.app.state.google_client_factory = factory

    def post(self, body: Any, headers: dict[str, str] | None = None) -> httpx.Response:
        if isinstance(body, bytes):
            return self.client.post(PATH, content=body, headers=headers or JSON_HEADERS)
        return self.client.post(PATH, json=body, headers=headers)


@pytest.fixture
def setup(make_app: Callable[..., FastAPI]) -> Callable[..., Setup]:
    def build(**settings: Any) -> Setup:
        app = make_app(**settings)
        s = Setup(app, TestClient(app, raise_server_exceptions=False))
        s.use(lambda r: httpx2.Response(200, headers={"Content-Type": DOCX_CT}, content=DOCX))
        return s

    return build


def ok_docx(data: bytes) -> Handler:
    return lambda r: httpx2.Response(200, headers={"Content-Type": DOCX_CT}, content=data)


# --- success ----------------------------------------------------------------------------


def test_google_doc_success_returns_the_same_contract_as_extract(
    setup: Callable[..., Setup],
) -> None:
    s = setup()

    response = s.post({"document_id": DOC_ID})
    direct = s.client.post(
        "/api/extract", content=DOCX, headers={"Content-Type": "application/octet-stream"}
    )

    assert response.status_code == 200
    assert response.json() == direct.json()
    assert response.json()["kind"] == "docx"
    assert response.json()["blocks"][0]["text"] == CLAUSE
    assert "no-store" in response.headers["cache-control"]
    assert response.headers["content-type"].startswith("application/json")
    assert [str(r.url) for r in s.requests] == [
        f"https://docs.google.com/document/d/{DOC_ID}/export?format=docx"
    ]


@pytest.mark.parametrize(
    "content_type", ["application/json", "application/json; charset=utf-8", "APPLICATION/JSON"]
)
def test_google_doc_json_content_type_variants_accepted(
    setup: Callable[..., Setup], content_type: str
) -> None:
    s = setup()

    response = s.post(json.dumps({"document_id": DOC_ID}).encode(), {"Content-Type": content_type})

    assert response.status_code == 200


def test_google_doc_incoming_headers_never_reach_the_fetch(setup: Callable[..., Setup]) -> None:
    s = setup()
    canary = new_marker("hdr")

    response = s.post(
        {"document_id": DOC_ID},
        {
            "X-Provider-Key": canary,
            "Cookie": f"sid={canary}",
            "Authorization": f"Bearer {canary}",
            "Referer": f"https://app.example/{canary}",
            "Origin": "http://localhost:5173",
        },
    )

    assert response.status_code == 200
    forwarded = s.requests[0].headers
    assert canary not in str(dict(forwarded))
    for name in ("x-provider-key", "cookie", "authorization", "referer", "origin"):
        assert name not in forwarded


# --- request checks ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "content_type", ["text/plain", "application/octet-stream", "application/x-www-form-urlencoded"]
)
def test_google_doc_wrong_content_type_415(setup: Callable[..., Setup], content_type: str) -> None:
    s = setup()

    response = s.post(json.dumps({"document_id": DOC_ID}).encode(), {"Content-Type": content_type})

    assert response.status_code == 415
    assert response.json() == {"error": "unsupported_media_type"}
    assert s.factory_calls == 0


def test_google_doc_missing_content_type_415(setup: Callable[..., Setup]) -> None:
    s = setup()
    request = s.client.build_request("POST", PATH, content=b'{"document_id": "x"}')
    request.headers.pop("content-type", None)

    response = s.client.send(request)

    assert response.status_code == 415
    assert response.json() == {"error": "unsupported_media_type"}


def test_google_doc_body_over_json_limit_413_even_below_file_limit(
    setup: Callable[..., Setup],
) -> None:
    s = setup(max_json_body_bytes=200)
    body = json.dumps({"document_id": DOC_ID, "pad": "x" * 500}).encode()

    response = s.post(body)

    assert response.status_code == 413
    assert response.json() == {"error": "request_too_large"}
    assert s.factory_calls == 0


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"{",
        b"not json",
        b"[]",
        b'"just a string"',
        b"null",
        b"{}",
        b'{"document_id": 5}',
        b'{"document_id": null}',
        b'{"document_id": ["a"]}',
        b'{"document_id": {"a": 1}}',
        b'{"Document_Id": "a1B2c3D4e5F6g7H8i9J0k1L2m3"}',
        b'{"document_id": "a1B2c3D4e5F6g7H8i9J0k1L2m3", "extra": 1}',
        b'{"document_id": "a1B2c3D4e5F6g7H8i9J0k1L2m3", "url": "https://evil.example/"}',
        b'{"url": "https://docs.google.com/document/d/a1B2c3D4e5F6g7H8i9J0k1L2m3/edit"}',
        b"\xff\xfe\x00",
    ],
)
def test_google_doc_malformed_body_422_invalid_request(
    setup: Callable[..., Setup], body: bytes
) -> None:
    s = setup()

    response = s.post(body)

    assert response.status_code == 422
    assert response.json() == {"error": "invalid_request"}
    assert s.factory_calls == 0


def test_google_doc_invalid_request_never_echoes_the_input(setup: Callable[..., Setup]) -> None:
    s = setup()
    marker = new_marker("echo")

    responses = [
        s.post(f'{{"document_id": "{DOC_ID}", "{marker}": 1}}'.encode()),
        s.post(f'{{"document_id": {{"{marker}": 1}}}}'.encode()),
        s.post(f"{{{marker}".encode()),
        s.post(f'["{marker}"]'.encode()),
    ]

    for response in responses:
        assert response.status_code == 422
        assert response.json() == {"error": "invalid_request"}
        assert marker not in response.text


@pytest.mark.parametrize(
    "document_id",
    [
        "",
        "short",
        "a" * 24,
        "a" * 101,
        "a" * 25 + "\n",
        "\n" + "a" * 25,
        "a" * 24 + " ",
        "a" * 12 + "/" + "a" * 12,
        "a" * 24 + ".",
        "a" * 24 + "%",
        "../" + "a" * 25,
        "https://docs.google.com/document/d/" + "a" * 30 + "/edit",
        "a" * 24 + "٣",
        "a" * 24 + "\x00",
    ],
)
def test_google_doc_bad_id_422_invalid_google_doc_id_without_fetch(
    setup: Callable[..., Setup], document_id: str
) -> None:
    s = setup()

    response = s.post({"document_id": document_id})

    assert response.status_code == 422
    assert response.json() == {"error": "invalid_google_doc_id"}
    assert s.factory_calls == 0
    assert s.requests == []


def test_google_doc_bad_id_never_echoed(setup: Callable[..., Setup]) -> None:
    s = setup()
    marker = new_marker("id")

    response = s.post({"document_id": f"{marker}/../x"})

    assert response.status_code == 422
    assert marker not in response.text
    assert marker not in str(dict(response.headers))


def test_google_doc_id_with_trailing_newline_is_not_a_full_match(
    setup: Callable[..., Setup],
) -> None:
    s = setup()

    response = s.post(b'{"document_id": "a1B2c3D4e5F6g7H8i9J0k1L2m3\\n"}')

    assert response.status_code == 422
    assert response.json() == {"error": "invalid_google_doc_id"}
    assert s.requests == []


# --- slot -------------------------------------------------------------------------------


def test_google_doc_no_free_slot_503_busy_with_retry_after_and_no_fetch(
    setup: Callable[..., Setup],
) -> None:
    s = setup(max_concurrent_extractions=1)
    assert s.app.state.extraction_limiter.try_acquire()

    response = s.post({"document_id": DOC_ID})

    assert response.status_code == 503
    assert response.json() == {"error": "busy"}
    assert response.headers.get("retry-after") == "5"
    assert s.factory_calls == 0


def test_google_doc_slot_is_held_during_the_fetch_and_freed_after(
    setup: Callable[..., Setup],
) -> None:
    s = setup(max_concurrent_extractions=1)
    free_during_fetch: list[bool] = []

    def handler(request: httpx2.Request) -> httpx.Response:
        got = s.app.state.extraction_limiter.try_acquire()
        free_during_fetch.append(got)
        if got:
            s.app.state.extraction_limiter.release()
        return httpx2.Response(200, headers={"Content-Type": DOCX_CT}, content=DOCX)

    s.use(handler)

    response = s.post({"document_id": DOC_ID})

    assert response.status_code == 200
    assert free_during_fetch == [False]
    assert s.app.state.extraction_limiter.try_acquire()


@pytest.mark.parametrize("status", [403, 404, 500])
def test_google_doc_slot_is_freed_after_a_fetch_error(
    setup: Callable[..., Setup], status: int
) -> None:
    s = setup(max_concurrent_extractions=1)
    s.use(lambda r: httpx2.Response(status))

    s.post({"document_id": DOC_ID})

    assert s.app.state.extraction_limiter.try_acquire()


# --- fetch error mapping ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("handler", "status", "code"),
    [
        (lambda r: httpx2.Response(403), 422, "google_doc_not_public"),
        (lambda r: httpx2.Response(401), 422, "google_doc_not_public"),
        (
            lambda r: httpx2.Response(302, headers={"Location": "https://accounts.google.com/x"}),
            422,
            "google_doc_not_public",
        ),
        (
            lambda r: httpx2.Response(200, headers={"Content-Type": "text/html"}, content=b"<p>"),
            422,
            "google_doc_not_public",
        ),
        (lambda r: httpx2.Response(404), 422, "google_doc_not_found"),
        (lambda r: httpx2.Response(500), 502, "google_doc_unavailable"),
        (lambda r: httpx2.Response(429), 502, "google_doc_unavailable"),
        (
            lambda r: httpx2.Response(302, headers={"Location": "https://evil.example/"}),
            502,
            "google_doc_unavailable",
        ),
    ],
)
def test_google_doc_fetch_error_is_mapped_to_status_and_code(
    setup: Callable[..., Setup], handler: Handler, status: int, code: str
) -> None:
    s = setup()
    s.use(handler)

    response = s.post({"document_id": DOC_ID})

    assert response.status_code == status
    assert response.json() == {"error": code}
    assert DOC_ID not in response.text


def test_google_doc_too_large_422_with_the_file_limit(setup: Callable[..., Setup]) -> None:
    s = setup(max_file_bytes=len(DOCX) - 1)

    response = s.post({"document_id": DOC_ID})

    assert response.status_code == 422
    assert response.json() == {"error": "google_doc_too_large"}


def test_google_doc_file_at_the_limit_is_accepted(setup: Callable[..., Setup]) -> None:
    s = setup(max_file_bytes=len(DOCX))

    assert s.post({"document_id": DOC_ID}).status_code == 200


def test_google_doc_timeout_504(setup: Callable[..., Setup]) -> None:
    import asyncio  # noqa: PLC0415 - used by one test only

    s = setup(google_fetch_timeout_seconds=1)

    async def slow(request: httpx2.Request) -> httpx.Response:
        await asyncio.sleep(10)
        return httpx2.Response(200)

    s.use(slow)

    response = s.post({"document_id": DOC_ID})

    assert response.status_code == 504
    assert response.json() == {"error": "google_doc_timeout"}
    assert s.app.state.extraction_limiter.try_acquire()


# --- bytes that are not a DOCX / extraction errors --------------------------------------


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"plain text pretending to be a docx",
        b"%PDF-1.7\n%%EOF\n",
        b"<html><body>Sign in</body></html>",
        b"PK",
    ],
    ids=["empty", "text", "pdf", "html", "short-zip-magic"],
)
def test_google_doc_bytes_that_are_not_docx_502_unavailable(
    setup: Callable[..., Setup], data: bytes
) -> None:
    s = setup()
    s.use(ok_docx(data))

    response = s.post({"document_id": DOC_ID})

    assert response.status_code == 502
    assert response.json() == {"error": "google_doc_unavailable"}


def test_google_doc_extraction_error_is_exactly_as_for_extract(
    setup: Callable[..., Setup],
) -> None:
    prolog = '<?xml version="1.0"?>\n<!DOCTYPE x [<!ENTITY e "synthetic">]>\n'
    data = build_docx(Package(document=document_xml(para(CLAUSE), prolog=prolog)))
    s = setup()
    s.use(ok_docx(data))

    response = s.post({"document_id": DOC_ID})
    direct = s.client.post(
        "/api/extract", content=data, headers={"Content-Type": "application/octet-stream"}
    )

    assert direct.status_code == 422
    assert response.status_code == direct.status_code
    assert response.json() == direct.json() == {"error": "suspicious_package"}
