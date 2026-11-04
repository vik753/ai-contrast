"""S6-T4 review findings: production free config, replay window, per-client slot, URL forms."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from pydantic import ValidationError

from app.settings import Settings
from tests.asgi_stream import AsgiRun, chunks, drive, post_scope
from tests.check.helpers import (
    ACCOUNT,
    CF_TOKEN,
    CHECK,
    FREE_ENV,
    HOSTNAME,
    KEY_HEADER,
    TS_SECRET,
    GateTransport,
    Rig,
    valid_body,
)

PROD: dict[str, Any] = {"environment": "production", "allowed_origins": ["https://app.example"]}
FREE_KEYS = ("cf_account_id", "cf_ai_token", "turnstile_secret_key", "turnstile_expected_hostname")
CF_TEST_SECRETS = (
    "1x0000000000000000000000000000000AA",
    "2x0000000000000000000000000000000AA",
    "3x0000000000000000000000000000000AA",
)
CUSTOM = {"provider": "custom", "model": "m1"}


def test_production_with_all_free_settings_starts() -> None:
    Settings(**PROD, **{k: FREE_ENV[k] for k in FREE_KEYS})


def test_production_without_any_free_setting_starts() -> None:
    Settings(**PROD)


@pytest.mark.parametrize("missing", FREE_KEYS)
def test_production_partial_free_config_refuses_startup(missing: str) -> None:
    env = {k: FREE_ENV[k] for k in FREE_KEYS if k != missing}
    with pytest.raises(ValidationError):
        Settings(**PROD, **env)


@pytest.mark.parametrize("only", FREE_KEYS)
def test_production_a_single_free_setting_refuses_startup(only: str) -> None:
    with pytest.raises(ValidationError):
        Settings(**PROD, **{only: FREE_ENV[only]})


@pytest.mark.parametrize("secret", CF_TEST_SECRETS)
def test_production_cloudflare_test_turnstile_secret_is_refused(secret: str) -> None:
    env = {k: FREE_ENV[k] for k in FREE_KEYS} | {"turnstile_secret_key": secret}
    with pytest.raises(ValidationError):
        Settings(**PROD, **env)


@pytest.mark.parametrize("secret", CF_TEST_SECRETS)
def test_development_cloudflare_test_turnstile_secret_is_allowed(secret: str) -> None:
    Settings(**{k: FREE_ENV[k] for k in FREE_KEYS} | {"turnstile_secret_key": secret})


def test_production_refusal_does_not_echo_the_secrets() -> None:
    env = {k: FREE_ENV[k] for k in FREE_KEYS if k != "turnstile_expected_hostname"}
    with pytest.raises(ValidationError) as info:
        Settings(**PROD, **env)
    text = str(info.value) + repr(info.value)
    assert CF_TOKEN not in text
    assert TS_SECRET not in text
    assert ACCOUNT not in text


def test_replay_seconds_below_305_is_refused() -> None:
    with pytest.raises(ValidationError):
        Settings(turnstile_replay_seconds=304)


def test_replay_seconds_of_305_is_accepted() -> None:
    assert Settings(turnstile_replay_seconds=305).turnstile_replay_seconds == 305


def test_replay_seconds_default_is_at_least_305() -> None:
    assert Settings().turnstile_replay_seconds >= 305


def _scope(ip: str, length: int) -> dict[str, Any]:
    s = post_scope(
        CHECK,
        content_type="application/json",
        content_length=length,
        extra_headers=list(KEY_HEADER.items()),
    )
    s["client"] = (ip, 50000)
    return s


def test_check_second_concurrent_check_from_one_ip_returns_503_busy() -> None:
    rig = Rig(check_per_minute=1000)
    gate = GateTransport()
    rig.app.state.provider_transport = gate
    body = json.dumps(valid_body()).encode()

    async def wait_started(n: int) -> None:
        for _ in range(500):
            if gate.started >= n:
                return
            await asyncio.sleep(0.01)

    async def scenario() -> tuple[AsgiRun, AsgiRun, AsgiRun]:
        first = asyncio.create_task(drive(rig.app, _scope("198.51.100.1", len(body)), chunks(body)))
        await wait_started(1)
        same_ip = await drive(rig.app, _scope("198.51.100.1", len(body)), chunks(body))
        assert gate.started == 1
        other = asyncio.create_task(drive(rig.app, _scope("198.51.100.2", len(body)), chunks(body)))
        await wait_started(2)
        assert gate.started == 2
        third_ip = await drive(rig.app, _scope("198.51.100.3", len(body)), chunks(body))
        gate.release.set()
        assert (await first).status == 200
        assert (await other).status == 200
        return (
            same_ip,
            third_ip,
            await drive(rig.app, _scope("198.51.100.1", len(body)), chunks(body)),
        )

    same_ip, third_ip, after = asyncio.run(scenario())
    assert same_ip.status == 503
    assert json.loads(same_ip.body) == {"error": "busy"}
    assert int(same_ip.headers["retry-after"]) >= 1
    assert third_ip.status == 503  # the shared pool of 2 is full
    assert after.status == 200  # the slot is free again


@pytest.mark.parametrize("url", ["https://2130706433/v1", "https://127.0.0.1./v1"])
def test_custom_alternative_loopback_forms_are_refused_without_network(url: str) -> None:
    rig = Rig()
    response = rig.check({**CUSTOM, "base_url": url}, headers=KEY_HEADER)
    assert response.status_code == 422
    assert response.json()["error"].startswith("provider_")
    assert rig.upstream.seen == []
    assert HOSTNAME not in response.text
