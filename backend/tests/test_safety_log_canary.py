# ruff: noqa: RUF001
"""S5b-T2: a canary in the masked text never reaches logs, errors or other replies (T1, T3, T11)."""

from __future__ import annotations

import secrets
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from tests.helpers import all_log_text
from tests.safety_helpers import detector_version, doc, post_doc

Make = Callable[..., TestClient]


def _cases(tag: str) -> dict[str, str]:
    return {
        "clean": f"1. Payment of {tag} is due; [A.ORG_1] pays within 30 days.",
        "leftover-email": f"Write to {tag}@example.com about it.",
        "leftover-company": f"The seller is ТОВ «Каный{tag}» and pays.",
        "bad-placeholder": f"Pay [A.{tag.upper()}_1] now.",
        "not-clean": f"Pay \u200b{tag} now.",
        "gap": f"[A.ORG_1] and [A.ORG_4] meet {tag}.",
    }


@pytest.mark.parametrize("case", sorted(_cases("x")))
def test_safety_canary_absent_from_logs_and_response(
    make_client: Make, log_capture: pytest.LogCaptureFixture, case: str
) -> None:
    tag = "canary" + secrets.token_hex(10)
    client = make_client()
    version = detector_version(client)
    log_capture.clear()

    response = post_doc(client, doc(version, _cases(tag)[case]))

    assert response.status_code in (200, 422)
    for needle in (tag, tag.upper()):
        assert needle not in all_log_text(log_capture)
        assert needle not in response.text
        assert all(needle not in v for v in response.headers.values())


def test_safety_canary_absent_from_logs_when_version_mismatches(
    make_client: Make, log_capture: pytest.LogCaptureFixture
) -> None:
    tag = "canary" + secrets.token_hex(10)
    client = make_client()
    log_capture.clear()

    response = post_doc(client, doc("old-version", f"Pay {tag}@example.com."))

    assert response.status_code == 409
    assert tag not in all_log_text(log_capture)
    assert tag not in response.text


def test_safety_log_holds_method_path_status_but_no_clause_ids_or_spans(
    make_client: Make, log_capture: pytest.LogCaptureFixture
) -> None:
    tag = "canary" + secrets.token_hex(10)
    client = make_client()
    version = detector_version(client)
    log_capture.clear()

    response = post_doc(client, doc(version, "ok.", f"Write to {tag}@example.com."))

    text = all_log_text(log_capture)
    assert response.status_code == 422
    assert "/api/safety-check" in text
    assert tag not in text
    assert "example.com" not in text
