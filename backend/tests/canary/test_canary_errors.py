"""S5b-T4 AC 1: a canary in a rejected request never comes back in an error body, header or log.

Extraction errors (415, 422), Google upstream errors, segment validation errors and every
safety-check error (409 version, 422 grammar, 422 unmasked identifier, 422 not clean).
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from typing import Any

import pytest

from tests.canary.harness import (
    DOC_ID,
    JSON_HEADERS,
    OCTET,
    client,
    find_leaks,
    google_export,
    tap_logs,
)
from tests.docxbuild import Package, build_docx, para
from tests.zipbuild import PNG_SAMPLE

Call = Callable[[str], Any]


def _token() -> str:
    return "canary" + secrets.token_hex(10)


def _json(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode()


def _safety(**overrides: Any) -> Callable[[str], Any]:
    def call(token: str) -> Any:
        version = (
            client()
            .post(
                "/api/segment",
                content=_json(
                    {"blocks": [{"text": "1. Payment is due.", "part": "body", "page": None}]}
                ),
                headers=JSON_HEADERS,
            )
            .json()["detector_version"]
        )
        payload: dict[str, Any] = {
            "label": "A",
            "detector_version": version,
            "clauses": [{"id": "c1", "text": "1. Payment is due."}],
            "acknowledged_unmasked": [],
        }
        for name, value in overrides.items():
            payload[name] = value(token) if callable(value) else value
        return client().post("/api/safety-check", content=_json(payload), headers=JSON_HEADERS)

    return call


CASES: dict[str, tuple[Call, set[int]]] = {
    "extract-unknown-binary": (
        lambda t: client().post("/api/extract", content=PNG_SAMPLE + t.encode(), headers=OCTET),
        {415, 422},
    ),
    "extract-truncated-docx": (
        lambda t: client().post(
            "/api/extract",
            content=build_docx(Package(body=para(f"Pay {t}@example.com now.")))[:-60],
            headers=OCTET,
        ),
        {415, 422},
    ),
    "extract-broken-pdf": (
        lambda t: client().post(
            "/api/extract", content=b"%PDF-1.7\n" + t.encode() + b"\n%%EOF", headers=OCTET
        ),
        {415, 422},
    ),
    "google-invalid-id": (
        lambda t: client().post("/api/extract/google-doc", json={"document_id": f"{t}/../x"}),
        {422},
    ),
    "google-upstream-404": (
        lambda t: google_export(f"not found {t}@example.com".encode(), status=404).post(
            "/api/extract/google-doc", json={"document_id": DOC_ID}
        ),
        {404, 422, 502},
    ),
    "google-upstream-html": (
        lambda t: google_export(
            f"<html>{t}</html>".encode(), headers={"Content-Type": "text/html"}
        ).post("/api/extract/google-doc", json={"document_id": DOC_ID}),
        {415, 422, 502},
    ),
    "google-upstream-500": (
        lambda t: google_export(f"error {t}".encode(), status=500).post(
            "/api/extract/google-doc", json={"document_id": DOC_ID}
        ),
        {404, 422, 502, 503},
    ),
    "segment-bad-part": (
        lambda t: client().post(
            "/api/segment",
            content=_json({"blocks": [{"text": "x", "part": t, "page": None}]}),
            headers=JSON_HEADERS,
        ),
        {422},
    ),
    "segment-bad-page": (
        lambda t: client().post(
            "/api/segment",
            content=_json({"blocks": [{"text": f"y {t}", "part": "body", "page": t}]}),
            headers=JSON_HEADERS,
        ),
        {422},
    ),
    "segment-not-json": (
        lambda t: client().post(
            "/api/segment", content=f'{{"blocks": [{t}'.encode(), headers=JSON_HEADERS
        ),
        {400, 422},
    ),
    "safety-label": (_safety(label=lambda t: t), {422}),
    "safety-clause-id": (_safety(clauses=lambda t: [{"id": t, "text": "ok"}]), {422}),
    "safety-version-mismatch": (_safety(detector_version=lambda t: t), {409}),
    "safety-bad-placeholder": (
        _safety(clauses=lambda t: [{"id": "c1", "text": f"Pay [A.{t.upper()}_1] now."}]),
        {422},
    ),
    "safety-not-clean": (
        _safety(clauses=lambda t: [{"id": "c1", "text": f"Pay \u200b{t} now."}]),
        {422},
    ),
    "safety-unmasked-identifier": (
        _safety(clauses=lambda t: [{"id": "c1", "text": f"Write to {t}@example.com about it."}]),
        {422},
    ),
    "safety-bad-acknowledged": (
        _safety(acknowledged_unmasked=lambda t: [[t, 1, 2]]),
        {422},
    ),
    "safety-extra-field": (_safety(secret_field=lambda t: t), {422}),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_canary_absent_from_error_reply_and_logs(name: str) -> None:
    call, statuses = CASES[name]
    token = _token()

    with tap_logs() as tap:
        reply = call(token)

    assert reply.status_code in statuses, (reply.status_code, reply.text[:120])
    headers = "\n".join(f"{k}: {v}" for k, v in reply.headers.items())
    assert find_leaks([token], reply.text, headers) == []
    assert find_leaks([token], tap.text) == []
    assert tap.text, "the log tap saw nothing: the harness is broken"


def test_unmasked_identifier_reply_holds_offsets_only() -> None:
    token = _token()
    reply = CASES["safety-unmasked-identifier"][0](token)
    body = reply.json()
    assert body["error"] == "unmasked_identifier"
    assert set(body) == {"error", "spans"}
    assert all(isinstance(x, int) for span in body["spans"] for x in span[1:])


def test_error_cases_cover_extract_google_segment_and_safety() -> None:
    prefixes = {name.split("-")[0] for name in CASES}
    assert prefixes == {"extract", "google", "segment", "safety"}
