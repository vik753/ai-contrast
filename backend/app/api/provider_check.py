"""``POST /api/provider/check``: test a provider connection (S6-T4, ADR 0016 points 5 to 7).

Body (at most 4096 bytes, no unknown field): ``provider``, ``model`` (not for ``free``),
``base_url`` (``custom`` only), ``turnstile_token`` (``free`` only). The client key is the
``X-Provider-Key`` header (not for ``free``). The answer is ``{"ok": true}`` or
``{"error": "<code>"}``: never model text, headers or provider error bodies.

Order: size (middleware), JSON and schema, cheap validation, free-mode availability,
check rate limit, in-flight slot, then for ``free`` Turnstile, the free quota and the Neuron
budget, then the provider call. Only a request that passed cheap validation is counted. A hit
is refunded only when the same request counted it. Nothing here logs: the access log has the
path, status and duration, and the client key, tokens and secrets are never in a message.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Final

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from app.ai.factory import provider_for
from app.ai.port import AIError, AIErrorCode
from app.ai.presets import (
    PRESETS,
    ConnectionConfigError,
    PresetId,
    checked_base_url,
    checked_model,
    is_ip_literal_url,
)
from app.api.common import early_error, error_response
from app.api.provider_key import ProviderKeyHeader, provider_key_header
from app.extraction.limiter import ExtractionLimiter
from app.http_limits import CHECK_PATH
from app.limits.client_ip import client_key, daily_key
from app.limits.free import CHECK_NEURONS, DAY_SECONDS, FreeQuota
from app.limits.replay import ReplayTable
from app.limits.slots import ClientSlots
from app.limits.window import FixedWindowLimiter
from app.net.ai_client import AITransport, private_ai_transport
from app.net.turnstile import TurnstileError, TurnstileVerdict, verify
from app.settings import Settings

router = APIRouter()

Clock = Callable[[], float]

BUSY_RETRY_AFTER_SECONDS: Final = 5
BODY_TIMEOUT_SECONDS: Final = 5.0
MAX_TOKEN_CHARS: Final = 2048
CHALLENGE_MAX_AGE_SECONDS: Final = 300.0
CHALLENGE_FUTURE_SKEW_SECONDS: Final = 5.0
MINUTE_SECONDS: Final = 60

_STATUS: Final = {
    AIErrorCode.PROVIDER_AUTH_FAILED: 401,
    AIErrorCode.PROVIDER_MODEL_NOT_FOUND: 404,
    AIErrorCode.PROVIDER_RATE_LIMITED: 429,
    AIErrorCode.PROVIDER_BAD_REQUEST: 400,
    AIErrorCode.PROVIDER_BLOCKED_HOST: 422,
    AIErrorCode.PROVIDER_UNAVAILABLE: 502,
    AIErrorCode.PROVIDER_BAD_RESPONSE: 502,
}
# Errors that mean the model did no work: the reserved Neurons go back to the budget.
_NO_COST: Final = frozenset(
    {
        AIErrorCode.PROVIDER_AUTH_FAILED,
        AIErrorCode.PROVIDER_MODEL_NOT_FOUND,
        AIErrorCode.PROVIDER_BAD_REQUEST,
        AIErrorCode.PROVIDER_BLOCKED_HOST,
    }
)


class CheckBody(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    provider: str
    model: str | None = None
    base_url: str | None = None
    turnstile_token: Annotated[str, Field(max_length=MAX_TOKEN_CHARS)] | None = None


class CheckState:
    """Per-app limits for the check endpoint. Holds no client data except counters by key.

    The three test hooks (``provider_transport``, ``turnstile_transport``, ``clock``) are typed
    arguments of ``install()``. The existing tests also set the same names on ``app.state``
    after the app is built, so a missing hook is read from there, type-checked (a value of
    another type is ignored). Production leaves them unset.
    """

    def __init__(
        self,
        app: FastAPI,
        settings: Settings,
        *,
        provider_transport: AITransport | None = None,
        turnstile_transport: AITransport | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._app = app
        self.settings = settings
        self.provider_hook = provider_transport
        self.turnstile_hook = turnstile_transport
        self.clock_hook = clock
        keys = settings.check_table_max_keys

        # The minute window is rolling and needs a monotonic clock; day windows need wall time.
        def mono() -> float:
            return self._clock(time.monotonic)

        def wall() -> float:
            return self._clock(time.time)

        self.minute = FixedWindowLimiter(settings.check_per_minute, MINUTE_SECONDS, keys, mono)
        self.day = FixedWindowLimiter(settings.check_per_day, DAY_SECONDS, keys, wall, aligned=True)
        self.quota = FreeQuota(
            settings.free_calls_per_ip_per_day, settings.free_neuron_budget, keys, wall
        )
        self.replay = ReplayTable(
            settings.turnstile_replay_max_entries, settings.turnstile_replay_seconds, wall
        )
        self.slots = ExtractionLimiter(settings.max_concurrent_checks)
        self.client_slots = ClientSlots(1)
        self._private: AITransport | None = None

    def _clock(self, default: Clock) -> float:
        hook = self.clock_hook
        if hook is None:
            late = getattr(self._app.state, "clock", None)
            hook = late if callable(late) else None
        return float(hook()) if hook is not None else default()

    def _transport(self, fixed: AITransport | None, name: str) -> AITransport | None:
        if fixed is not None:
            return fixed
        late = getattr(self._app.state, name, None)
        return late if isinstance(late, AITransport) else None

    def now(self) -> float:
        return self._clock(time.time)

    def provider_transport(self, *, private: bool) -> AITransport | None:
        """The test hook, else (development switch, ``custom`` only) the unguarded transport."""
        hook = self._transport(self.provider_hook, "provider_transport")
        if hook is not None:
            return hook
        if private:
            if self._private is None:
                self._private = private_ai_transport()
            return self._private
        return None

    def turnstile_transport(self) -> AITransport | None:
        return self._transport(self.turnstile_hook, "turnstile_transport")

    @property
    def free_available(self) -> bool:
        s = self.settings
        return (
            s.cf_account_id is not None
            and s.cf_ai_token is not None
            and s.turnstile_secret_key is not None
        )


def install(
    app: FastAPI,
    settings: Settings,
    *,
    provider_transport: AITransport | None = None,
    turnstile_transport: AITransport | None = None,
    clock: Clock | None = None,
) -> None:
    """Register the route and build the state (the keyword arguments are test hooks)."""
    app.include_router(router)
    app.state.check_state = CheckState(
        app,
        settings,
        provider_transport=provider_transport,
        turnstile_transport=turnstile_transport,
        clock=clock,
    )


def _state(request: Request) -> CheckState:
    state = getattr(request.app.state, "check_state", None)
    if not isinstance(state, CheckState):
        msg = "app state is not configured"
        raise TypeError(msg)
    return state


@dataclass(frozen=True)
class Plan:
    preset: PresetId
    model: str
    base_url: str | None
    key: SecretStr | None
    token: str | None


def _refusal(code: str) -> JSONResponse:
    return error_response(code, 422)


def _plan(body: CheckBody, header: ProviderKeyHeader, settings: Settings) -> Plan | Response:
    """Cheap validation only: no network, no counter."""
    try:
        preset = PresetId(body.provider)
    except ValueError:
        return _refusal("invalid_provider")
    if preset is PresetId.FREE:
        return _free_plan(body, header)
    return _keyed_plan(preset, body, header, settings)


def _free_plan(body: CheckBody, header: ProviderKeyHeader) -> Plan | Response:
    if header.present:
        return _refusal("unexpected_provider_key")
    if body.base_url is not None:
        return _refusal("unexpected_base_url")
    if body.model is not None:
        return _refusal("unexpected_model")
    # The model of the free preset is fixed.
    return Plan(PresetId.FREE, PRESETS[PresetId.FREE].models[0], None, None, body.turnstile_token)


def _keyed_plan(
    preset: PresetId, body: CheckBody, header: ProviderKeyHeader, settings: Settings
) -> Plan | Response:
    if body.turnstile_token is not None:
        return _refusal("unexpected_turnstile_token")
    if body.base_url is not None and preset is not PresetId.CUSTOM:
        return _refusal("unexpected_base_url")
    try:
        model = checked_model(body.model or "")
        if preset is PresetId.CUSTOM:
            _check_custom_url(body.base_url, settings)
    except AIError as error:
        return error_response(error.code.value, _STATUS[error.code])
    except ConnectionConfigError as error:
        return _refusal(error.code)
    if header.key is None:
        return _refusal("invalid_provider_key")
    return Plan(preset, model, body.base_url, header.key, None)


def _check_custom_url(url: str | None, settings: Settings) -> None:
    private = settings.allow_private_provider_urls
    if url is not None and not private and is_ip_literal_url(url):
        # Refused by syntax, before any DNS or network call.
        raise AIError(AIErrorCode.PROVIDER_BLOCKED_HOST) from None
    checked_base_url(url, allow_private=private)


def _limited(code: str, status: int, retry_after: int) -> JSONResponse:
    return error_response(code, status, {"Retry-After": str(max(1, retry_after))})


@dataclass
class Hits:
    """The check hits that one request counted, so only they can be refunded."""

    state: CheckState
    minute_key: str
    day_key: str
    minute: bool = False
    day: bool = False

    def refund(self) -> None:
        if self.day:
            self.state.day.refund(self.day_key)
            self.day = False
        if self.minute:
            self.state.minute.refund(self.minute_key)
            self.minute = False


def _count(hits: Hits) -> JSONResponse | None:
    decision = hits.state.minute.hit(hits.minute_key)
    if not decision.allowed:
        return _limited("rate_limited", 429, decision.retry_after)
    hits.minute = True
    decision = hits.state.day.hit(hits.day_key)
    if not decision.allowed:
        hits.refund()
        return _limited("rate_limited", 429, decision.retry_after)
    hits.day = True
    return None


def _turnstile_ok(verdict: TurnstileVerdict, settings: Settings, now: float) -> bool:
    expected_host = settings.turnstile_expected_hostname
    if not verdict.success or verdict.challenge_ts is None:
        return False
    if expected_host is not None and verdict.hostname != expected_host:
        return False
    if verdict.action != settings.turnstile_action:
        return False
    age = now - verdict.challenge_ts
    return -CHALLENGE_FUTURE_SKEW_SECONDS <= age <= CHALLENGE_MAX_AGE_SECONDS


async def _turnstile(state: CheckState, token: str | None) -> bool:
    """Verify and remember the token. ``False`` for every refusal and every error."""
    secret = state.settings.turnstile_secret_key
    if not token or secret is None or not state.replay.would_accept(token):
        return False
    try:
        verdict = await verify(token, secret, transport=state.turnstile_transport())
    except TurnstileError:
        return False
    if not _turnstile_ok(verdict, state.settings, state.now()):
        return False
    return state.replay.add(token)


async def _read_body(request: Request) -> bytes | None:
    try:
        async with asyncio.timeout(BODY_TIMEOUT_SECONDS):
            return await request.body()
    except TimeoutError:
        return None


@router.post(
    CHECK_PATH,
    responses={
        403: {"description": "turnstile_failed"},
        408: {"description": "upload_timeout"},
        413: {"description": "request_too_large"},
        422: {"description": "invalid_request and the validation codes"},
        429: {"description": "rate_limited, free_quota_exhausted, provider_rate_limited"},
        503: {"description": "busy, free_mode_unavailable"},
    },
)
async def check_connection(
    request: Request, header: Annotated[ProviderKeyHeader, Depends(provider_key_header)]
) -> Response:
    state = _state(request)
    plan = await _parse(request, header, state)
    if isinstance(plan, Response):
        return plan
    key = client_key(request.scope, state.settings)
    hits = Hits(state, key, daily_key(key))
    refused = _count(hits)
    if refused is not None:
        return refused
    # One check per client key first, then the shared pool; both are released on every path.
    if not state.client_slots.try_acquire(key):
        hits.refund()
        return _limited("busy", 503, BUSY_RETRY_AFTER_SECONDS)
    try:
        slot = state.slots.try_slot()
        if slot is None:
            hits.refund()
            return _limited("busy", 503, BUSY_RETRY_AFTER_SECONDS)
        with slot:
            return await _run(state, plan, hits)
    finally:
        state.client_slots.release(key)


async def _parse(request: Request, header: ProviderKeyHeader, state: CheckState) -> Plan | Response:
    """Body, cheap validation and free-mode availability. Counts nothing."""
    raw = await _read_body(request)
    if raw is None:
        return early_error("upload_timeout", 408)
    try:
        body = CheckBody.model_validate_json(raw)
    except ValidationError:
        return _refusal("invalid_request")
    plan = _plan(body, header, state.settings)
    if isinstance(plan, Response):
        return plan
    if plan.preset is PresetId.FREE and not state.free_available:
        return error_response("free_mode_unavailable", 503)
    return plan


async def _run(state: CheckState, plan: Plan, hits: Hits) -> Response:
    if plan.preset is not PresetId.FREE:
        return (await _call(state, plan, plan.key, free_account=None))[0]
    if not await _turnstile(state, plan.token):
        # Counted, not refunded: the check limits bound a flood of bad tokens.
        return error_response("turnstile_failed", 403)
    token, account = state.settings.cf_ai_token, state.settings.cf_account_id
    if token is None or account is None:  # checked before; keeps the types honest
        return error_response("free_mode_unavailable", 503)
    decision = state.quota.reserve(hits.day_key, CHECK_NEURONS)
    if not decision.allowed:
        if decision.reason != "ip":
            # The shared state refused, not this client: the request counts nothing.
            hits.refund()
        return _limited("free_quota_exhausted", 429, decision.retry_after)
    spent = CHECK_NEURONS
    try:
        response, no_cost = await _call(state, plan, token, free_account=account.get_secret_value())
        if no_cost:
            spent = 0
            state.quota.refund_call(hits.day_key)  # the model did no work
        return response
    finally:
        state.quota.settle(CHECK_NEURONS, spent)


async def _call(
    state: CheckState, plan: Plan, key: SecretStr | None, *, free_account: str | None
) -> tuple[Response, bool]:
    """Run the probe. Returns the answer and whether the model did no work (for the budget)."""
    if key is None:  # cheap validation guarantees a key for every non-free preset
        return error_response("invalid_provider_key", 422), True
    private = state.settings.allow_private_provider_urls and plan.preset is PresetId.CUSTOM
    try:
        provider = provider_for(
            plan.preset,
            plan.model,
            key,
            plan.base_url,
            transport=state.provider_transport(private=private),
            free_account_id=free_account,
            allow_private=private,
        )
        result = await provider.check()
    except ConnectionConfigError as error:
        return _refusal(error.code), True
    except AIError as error:
        return error_response(error.code.value, _STATUS[error.code]), error.code in _NO_COST
    if not result.ok:
        return error_response(AIErrorCode.PROVIDER_BAD_RESPONSE.value, 502), False
    return JSONResponse({"ok": True}), False
