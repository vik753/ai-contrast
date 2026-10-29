"""S6-T2 AC6 / ADR 0016 point 10 / T11 control 10: the wire canary.

Both adapters, ``check()`` and ``complete_json()``, with a request built from a document that
passed the real safety pass (canary pipeline of ADR 0015 point 6) and with canary values in
every environment variable of ADR 0016 point 3. The wire capture of the canary harness
collects URL, headers and body; identifier canaries and the key canary must not be in it
(the key only in the auth header).
"""

from __future__ import annotations

import json

import pytest
from app.ai.port import AIRequest
from app.ai.presets import PresetId

from app.pseudo.gate import PseudonymizedDocument, safety_pass
from app.pseudo.untrusted import UntrustedMaskedDocument
from tests.ai.helpers import (
    AUTH_HEADERS,
    KEY,
    Verdict,
    first_template,
    make_provider,
    run,
    tap_logs,
)
from tests.ai.test_ai_env import ENV, C
from tests.canary.harness import CellRun, WireCapture, find_leaks, run_cell

CELLS = [("txt", "body"), ("docx", "body"), ("ocr", "wrapped")]
CASES = [
    (PresetId.ANTHROPIC, None),
    (PresetId.OPENAI, None),
    (PresetId.CUSTOM, "https://llm.example.com/v1"),
]
OPS = ["check", "complete_json"]


def _document(path: str, location: str) -> tuple[CellRun, PseudonymizedDocument]:
    cell = run_cell(path, location, "clean")
    assert cell.safety_status == 200, "the clean canary cell must pass the safety check"
    untrusted = UntrustedMaskedDocument.model_validate_json(json.dumps(cell.safety_payload))
    return cell, safety_pass(untrusted)


@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize(("preset", "base_url"), CASES, ids=str)
@pytest.mark.parametrize(("path", "location"), CELLS)
def test_wire_canary_no_identifier_and_no_key_outside_the_auth_header(  # noqa: PLR0913, PLR0917
    monkeypatch: pytest.MonkeyPatch,
    wire_capture: WireCapture,
    path: str,
    location: str,
    preset: PresetId,
    base_url: str | None,
    op: str,
) -> None:
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    cell, document = _document(path, location)
    needles = [n for c in cell.canaries for n in c.needles]
    provider, upstream = make_provider(preset, base_url=base_url)
    request = AIRequest(
        template=first_template(), document=document, schema=Verdict, max_tokens=256
    )

    with tap_logs() as tap:
        run(provider, op, request)
    seen = upstream.seen[0]
    wire_capture.record(seen.without_auth())
    auth = {k: v for k, v in seen.headers.items() if k in AUTH_HEADERS}

    assert needles
    assert wire_capture.leaks(needles) == []
    assert find_leaks(needles, tap.text) == []
    assert KEY not in seen.without_auth()
    assert KEY not in tap.text
    assert [v for v in auth.values() if KEY in v] == list(auth.values())
    assert C not in seen.everything.lower()


@pytest.mark.parametrize(("preset", "base_url"), CASES, ids=str)
@pytest.mark.parametrize(("path", "location"), CELLS)
def test_wire_canary_complete_json_sends_the_masked_text_of_one_document(
    preset: PresetId, base_url: str | None, path: str, location: str
) -> None:
    cell, document = _document(path, location)
    provider, upstream = make_provider(preset, base_url=base_url)
    request = AIRequest(
        template=first_template(), document=document, schema=Verdict, max_tokens=256
    )

    run(provider, "complete_json", request)
    body = upstream.seen[0].body.decode()
    sent = json.dumps(json.loads(body), ensure_ascii=False)

    assert len(upstream.seen) == 1
    assert all(json.dumps(c.text, ensure_ascii=False)[1:-1] in sent for c in document.clauses)
    assert cell.masked  # the placeholders (not the identifiers) are what travels
    assert "[A." in sent


@pytest.mark.parametrize(("preset", "base_url"), CASES, ids=str)
def test_wire_canary_check_sends_no_document_text(preset: PresetId, base_url: str | None) -> None:
    cell, _ = _document("txt", "body")
    provider, upstream = make_provider(preset, base_url=base_url)

    run(provider, "check")

    sent = upstream.seen[0].body.decode()
    assert all(c["text"][:20] not in sent for c in cell.masked)
