# ruff: noqa: PT018
"""S5-T1 AC5: privacy of ``POST /api/segment`` (T1, T3, ADR 0014 point 9).

A canary inside a block, a field name, a header or a number never appears in
any captured log record or in any response. The access line carries method,
path, status and duration (and counts) only.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from tests.helpers import access_lines, all_log_text, new_canary
from tests.segment_helpers import JSON_HEADERS, SEGMENT, block, post_blocks, post_raw


def _headers(canary: str) -> dict[str, str]:
    return {**JSON_HEADERS, "X-Provider-Key": canary, "X-File-Name": f"{canary}.docx"}


def _bodies(canary: str) -> dict[str, bytes]:
    def enc(obj: object) -> bytes:
        return json.dumps(obj).encode()

    return {
        "text": enc({"blocks": [block(f"1. Party {canary} pays within 30 days.")]}),
        "heading": enc({"blocks": [block(f"1. {canary} TERMS"), block("1.1. Pay.")]}),
        "number": enc({"blocks": [block(f"{canary}. Odd start."), block("Second.")]}),
        "header-part": enc({"blocks": [block(canary, part="header"), block("1. Text.")]}),
        "extra-field": enc({"blocks": [block("1. Text.")], canary: 1}),
        "extra-block-field": enc({"blocks": [{**block("1. Text."), canary: 1}]}),
        "bad-part": enc({"blocks": [block("1. Text.", part=canary)]}),
        "bad-page": enc({"blocks": [block("1. Text.", page=canary)]}),  # type: ignore[arg-type]
        "duplicate-key": (
            b'{"blocks":[{"text":"' + canary.encode() + b'","text":"x","part":"body","page":null}]}'
        ),
        "invalid-json": b"{" + canary.encode(),
        "whitespace-only": enc({"blocks": [block(" ")], canary: 1}),
        "zero-width": enc({"blocks": [block(f"1. {canary[:6]}\u200b{canary[6:]} clause.")]}),
    }


CASES = sorted(_bodies("x"))


@pytest.mark.parametrize("case", CASES)
def test_segment_canary_absent_from_logs_and_response(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture, case: str
) -> None:
    canary = new_canary()
    client = make_client()
    log_capture.clear()

    response = client.post(SEGMENT, content=_bodies(canary)[case], headers=_headers(canary))

    assert response.status_code in (200, 422)
    assert canary not in all_log_text(log_capture)
    for name, value in response.headers.items():
        assert canary not in name and canary not in value
    if response.status_code == 422:
        assert canary not in response.text
        assert set(response.json()) == {"error"}


def test_segment_canary_in_block_not_logged_when_reply_is_200(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    canary = new_canary()
    client = make_client()
    log_capture.clear()

    response = post_blocks(client, [block(f"1. {canary} clause."), block("2. Second clause.")])

    assert response.status_code == 200
    assert canary in response.text  # the reply itself carries the cleaned text
    assert canary not in all_log_text(log_capture)


def test_segment_canary_absent_from_logs_for_early_errors(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    canary = new_canary()
    client = make_client(segment_max_body_bytes=200)
    log_capture.clear()

    too_big = client.post(SEGMENT, content=canary.encode() * 50, headers=_headers(canary))
    wrong_type = client.post(
        SEGMENT, content=canary.encode(), headers={**_headers(canary), "Content-Type": "text/plain"}
    )

    assert (too_big.status_code, wrong_type.status_code) == (413, 415)
    assert canary not in all_log_text(log_capture)
    assert canary not in too_big.text + wrong_type.text


def test_segment_canary_absent_from_logs_when_child_fails(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    canary = new_canary()
    client = make_client(extract_max_result_bytes=300)
    log_capture.clear()

    response = post_blocks(
        client, [block(f"{n}. {canary} synthetic clause text.") for n in range(1, 30)]
    )

    assert response.json() == {"error": "segment_failed"}
    assert canary not in all_log_text(log_capture)
    assert canary not in response.text


ACCESS_LINE = re.compile(r"^POST /api/segment (?P<status>\d{3}) duration_ms=\d+( [a-z_]+=\d+)*$")


@pytest.mark.parametrize(
    ("body", "status"),
    [
        (json.dumps({"blocks": [block("1. Clause.")]}).encode(), 200),
        (b"not json", 422),
        (json.dumps({"blocks": []}).encode(), 422),
    ],
)
def test_segment_access_line_has_only_method_path_status_duration_and_counts(
    make_client: Callable[..., TestClient],
    log_capture: pytest.LogCaptureFixture,
    body: bytes,
    status: int,
) -> None:
    client = make_client()
    log_capture.clear()

    response = post_raw(client, body)

    assert response.status_code == status
    lines = access_lines(log_capture, "POST", SEGMENT)
    assert len(lines) == 1
    match = ACCESS_LINE.match(lines[0])
    assert match, lines[0]
    assert int(match["status"]) == status


def test_segment_logs_contain_no_clause_text_number_or_heading(
    make_client: Callable[..., TestClient], log_capture: pytest.LogCaptureFixture
) -> None:
    heading = "UNIQUEHEADINGWORDQX"
    text = "uniqueclausewordzq"
    client = make_client()
    log_capture.clear()

    # Clause numbers that cannot collide with durations or sizes in the access log.
    response = post_blocks(
        client, [block(f"8641.9273 {heading}"), block(f"8641.9274 {text} applies.")]
    )

    assert response.status_code == 200
    logs = all_log_text(log_capture)
    assert heading not in logs and text not in logs
    assert "8641.9273" not in logs and "8641.9274" not in logs
