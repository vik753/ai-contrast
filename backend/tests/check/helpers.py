"""Helpers of the S6-T4 tests. No network: every outbound call goes to a fake transport."""

from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx2
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings
from tests.ai.helpers import FakeUpstream, model_reply

CHECK = "/api/provider/check"
NOW = datetime(2026, 11, 4, 12, 0, 0, tzinfo=UTC).timestamp()  # 12:00 UTC, 12 h before reset
DAY = 86400
ACCOUNT = "0123456789abcdef0123456789abcdef"
CF_TOKEN = "CANARY-CF-TOKEN-" + secrets.token_hex(8)
TS_SECRET = "CANARY-TS-SECRET-" + secrets.token_hex(8)
CLIENT_KEY = "sk-CANARY-" + secrets.token_hex(8)
HOSTNAME = "turnstile.example"
ACTION = "check"
FREE_MODEL = "@cf/openai/gpt-oss-120b"
PUBLIC_IP = "198.51.100.7"
FREE_ENV: dict[str, Any] = {
    "cf_account_id": ACCOUNT,
    "cf_ai_token": CF_TOKEN,
    "turnstile_secret_key": TS_SECRET,
    "turnstile_expected_hostname": HOSTNAME,
    "turnstile_action": ACTION,
}
DEFAULT_TOKEN = "tok-1"  # noqa: S105
KEY_HEADER = {"X-Provider-Key": CLIENT_KEY}


class Clock:
    def __init__(self, now: float = NOW) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def siteverify_reply(
    *,
    success: bool = True,
    hostname: str = HOSTNAME,
    action: str = ACTION,
    age: float = 5.0,
    clock: Clock | None = None,
) -> Callable[[httpx2.Request], httpx2.Response]:
    """A siteverify answer. ``age`` is the age of the challenge in seconds."""
    now = (clock or Clock()).now

    def reply(request: httpx2.Request) -> httpx2.Response:
        ts = datetime.fromtimestamp(now - age, UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        body: dict[str, Any] = {"success": success, "hostname": hostname, "action": action}
        if success:
            body["challenge_ts"] = ts
        else:
            body["error-codes"] = ["invalid-input-response"]
        return httpx2.Response(200, json=body)

    return reply


class Rig:
    """An app with fake provider and Turnstile transports and a fixed clock."""

    def __init__(self, *, provider_transport: Any = None, **settings: Any) -> None:
        settings.setdefault("environment", "development")
        self.clock = Clock()
        self.upstream = provider_transport or FakeUpstream(model_reply())
        self.turnstile = FakeUpstream(siteverify_reply(clock=self.clock))
        self.app: FastAPI = create_app(
            Settings(**settings),
            provider_transport=self.upstream,
            turnstile_transport=self.turnstile,
            clock=self.clock,
        )

    def client(self, ip: str = PUBLIC_IP) -> TestClient:
        return TestClient(self.app, raise_server_exceptions=False, client=(ip, 50000))

    def check(
        self,
        body: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
        ip: str = PUBLIC_IP,
    ) -> httpx2.Response:
        if body is None:
            body = {"provider": "openai", "model": "gpt-test-1"}
            headers = KEY_HEADER if headers is None else headers
        return self.client(ip).post(CHECK, json=body, headers=headers or {})  # type: ignore[return-value]

    def free(self, token: str | None = DEFAULT_TOKEN, *, ip: str = PUBLIC_IP) -> httpx2.Response:
        body: dict[str, Any] = {"provider": "free"}
        if token is not None:
            body["turnstile_token"] = token
        return self.check(body, headers={}, ip=ip)


def free_rig(**settings: Any) -> Rig:
    return Rig(**{**FREE_ENV, **settings})


def valid_body() -> dict[str, Any]:
    return {"provider": "openai", "model": "gpt-test-1"}


def error_of(response: Any) -> str:
    return str(json.loads(response.content)["error"])


class GateTransport(httpx2.AsyncBaseTransport):
    """A provider transport that waits until the test lets it answer."""

    def __init__(self) -> None:
        self.started = 0
        self.release = asyncio.Event()
        self.entered = asyncio.Event()

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        self.started += 1
        self.entered.set()
        await self.release.wait()
        return model_reply()(request)
