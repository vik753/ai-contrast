# ruff: noqa: RUF001
"""S5b-T1 AC7: an identifier canary never reaches the logs (T1, T3)."""

from __future__ import annotations

import secrets
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from tests.helpers import all_log_text
from tests.pseudo_helpers import detect
from tests.segment_helpers import block, post_blocks

Make = Callable[..., TestClient]


def _texts(tag: str) -> dict[str, str]:
    return {
        "email": f"Пишіть на {tag}@example.com щодо договору.",
        "org": f"Компанія ТОВ «Каный{tag}» надає послуги.",
        "person": f"в особі директора Тестов{tag} Іван Петрович, що діє на підставі Статуту",
        "url": f"Дивіться https://www.{tag}.example.com/x тут.",
        "address": f"Адреса: м. Одеса, вул. {tag}, 12. Страховик платить.",
        "doc-no": f"Договір № {tag.upper()}-77/2024 діє.",
        "lookalike": f"Платіж на [ORG_2] і {tag} сплачується.",
    }


@pytest.mark.parametrize("case", sorted(_texts("x")))
def test_log_identifier_canary_absent_from_logs(
    make_client: Make, log_capture: pytest.LogCaptureFixture, case: str
) -> None:
    tag = "canary" + secrets.token_hex(10)
    client = make_client()
    log_capture.clear()

    data = detect(client, _texts(tag)[case])

    assert data["blocks"]
    assert tag not in all_log_text(log_capture)
    assert tag.upper() not in all_log_text(log_capture)


def test_log_identifier_canary_absent_from_logs_and_error_when_cap_is_hit(
    make_client: Make, log_capture: pytest.LogCaptureFixture
) -> None:
    tag = "canary" + secrets.token_hex(10)
    client = make_client()
    log_capture.clear()
    items = [f"{tag}{i}@example.com" for i in range(5_001)]
    blocks = [
        block(f"{k + 1}. " + " ".join(items[i : i + 40])) for k, i in enumerate(range(0, 5_001, 40))
    ]

    response = post_blocks(client, blocks)

    assert response.status_code == 422
    assert tag not in response.text
    assert tag not in all_log_text(log_capture)
    assert set(response.json()) == {"error"}
