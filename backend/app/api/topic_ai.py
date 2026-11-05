"""Topic AI endpoints (S7-T2, ADR 0017 points 5 and 6; threat model T1, T5, T6, T10, T11).

``POST /api/topics/suggest``, ``/propose-attributes`` and ``/expand-synonyms``. Each takes the
provider selection of ``/api/provider/check`` (``provider``, ``model``, ``base_url``,
``turnstile_token``; ``X-Provider-Key`` header) plus its own input, runs the server-side safety
pass on that input, calls the model once (twice after a bad answer) and returns only JSON that
passed the topic safety pass. Errors are ``{"error": "<code>"}``; a refused topic text adds
``field`` and, for an identifier, ``spans`` (offsets only). Nothing here logs.

Order: header and size checks, body, provider selection, input validation (nothing counted so
far), per-client rate limits, then for ``suggest`` the sandbox safety pass under the extraction
slots (released before the AI call), then the AI slots (per client and the pool shared with
``/api/provider/check``), then for ``free`` the free pass or Turnstile and the free quotas, then
the call under one deadline. Free mode: the first call sends a Turnstile token and gets a
``free_pass`` in the reply; later calls send it in the ``X-Free-Pass`` header.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Final

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, SecretStr, ValidationError

from app.ai.port import (
    REPAIR_CAP,
    REPAIR_NOT_JSON,
    REPAIR_SCHEMA,
    AIError,
    AIErrorCode,
    AIProvider,
)
from app.ai.presets import ConnectionConfigError, PresetId
from app.api.ai_shared import (
    ACCEPTED_MEDIA_TYPE,
    busy,
    ok,
    read_limited,
    safety_error,
    topic_error,
)
from app.api.common import (
    check_upload_headers,
    early_error,
    error_response,
    extraction_slots,
    sandbox_limits,
)
from app.api.provider_check import (
    AI_NO_COST,
    AI_STATUS,
    ANALYSIS_PASS_HEADER,
    BUSY_RETRY_AFTER_SECONDS,
    FREE_PASS_HEADER,
    BusyError,
    CheckBody,
    CheckState,
    Plan,
    ai_slots,
    check_state,
    count_hits,
    limited,
    make_provider,
    plan_connection,
    verify_turnstile,
)
from app.api.provider_key import provider_key_header
from app.api.topics import catalog_of
from app.http_limits import EXPAND_PATH, PROPOSE_PATH, SUGGEST_PATH, TOPIC_MAX_BODY_BYTES
from app.limits.client_ip import client_key, daily_key
from app.limits.free import reported_neurons
from app.limits.free_pass import FreePassError
from app.limits.hits import Hits
from app.pseudo.gate import (
    ConfirmedTopic,
    PseudonymizedDocument,
    SafetyError,
    confirm_topic,
    safety_pass,
)
from app.pseudo.untrusted import UntrustedMaskedDocument
from app.safety.runner import (
    SafetyRunError,
    run_safety_check,
)
from app.settings import Settings
from app.topics.catalog import Catalog
from app.topics.jobs import BadOutputError, Job, expand_job, propose_job, suggest_job
from app.topics.model import TopicDefinition, TopicDefinitionError
from app.topics.safety import TopicTextError

router = APIRouter()

INVALID_DEFINITION: Final = "invalid_topic_definition"
MAX_REPAIRS: Final = 1


class SuggestBody(CheckBody):
    domain: str
    side: str
    document: UntrustedMaskedDocument


class TopicBody(CheckBody):
    topic: TopicDefinition


@dataclass
class Free:
    """The free pass of one free call: the nonce, and the pass text if this call issued it."""

    nonce: str
    issued: str | None


def _confirm(
    definition: TopicDefinition, catalog: Catalog, *, no_attributes: bool
) -> ConfirmedTopic | Response:
    """The topic safety pass. v1 needs a catalog domain and side; no origin ``catalog`` here."""
    if (
        definition.origin == "catalog"
        or definition.domain is None
        or (no_attributes and definition.attributes)
    ):
        return error_response(INVALID_DEFINITION, 422)
    try:
        return confirm_topic(definition, catalog=catalog)
    except (TopicDefinitionError, TopicTextError) as error:
        return topic_error(error)


def _free_header(request: Request, plan: Plan, body: CheckBody) -> Response | str | None:
    """The pass of the request, ``None`` if there is none, or a refusal."""
    if ANALYSIS_PASS_HEADER in request.headers:
        return error_response("unexpected_analysis_pass", 422)  # audience ``analysis``
    values = request.headers.getlist(FREE_PASS_HEADER)
    if not values:
        return None
    if plan.preset is not PresetId.FREE:
        return error_response("unexpected_free_pass", 422)
    if body.turnstile_token is not None:
        return error_response("invalid_request", 422)
    if len(values) != 1:
        return error_response("free_pass_invalid", 403)
    return values[0]


def _count(state: CheckState, key: str) -> Hits | JSONResponse:
    hits = Hits(state.topic_minute, state.topic_day, key, daily_key(key))
    return count_hits(hits) or hits


def _parse[BodyT: CheckBody](model: type[BodyT], data: bytes) -> BodyT | Response:
    try:
        return model.model_validate_json(data)
    except ValidationError:
        return error_response("invalid_request", 422)


@dataclass(frozen=True)
class Prepared:
    plan: Plan
    pass_value: str | None
    hits: Hits
    job: Job


# --- propose-attributes and expand-synonyms ---------------------------------------------------


async def _topic_body(request: Request, state: CheckState) -> TopicBody | Response:
    checked = check_upload_headers(
        request,
        max_bytes=TOPIC_MAX_BODY_BYTES,
        too_large_code="request_too_large",
        accepted_media_type=ACCEPTED_MEDIA_TYPE,
    )
    if isinstance(checked, JSONResponse):
        return checked
    raw = await read_limited(request, checked, state.settings, TOPIC_MAX_BODY_BYTES)
    if isinstance(raw, Response):
        return raw
    return _parse(TopicBody, raw)


async def _topic_endpoint(request: Request, *, propose: bool) -> Response:
    state = check_state(request)
    body = await _topic_body(request, state)
    if isinstance(body, Response):
        return body
    selected = _select(request, state, body)
    if isinstance(selected, Response):
        return selected
    plan, pass_value = selected
    topic = _confirm(body.topic, catalog_of(request), no_attributes=propose)
    if isinstance(topic, Response):
        return topic
    hits = _count(state, client_key(request.scope, state.settings))
    if isinstance(hits, Response):
        return hits
    job = propose_job(topic, body.topic) if propose else expand_job(topic)
    return await _ai_stage(state, Prepared(plan, pass_value, hits, job))


@router.post(PROPOSE_PATH)
async def propose_attributes(request: Request) -> Response:
    return await _topic_endpoint(request, propose=True)


@router.post(EXPAND_PATH)
async def expand_synonyms(request: Request) -> Response:
    return await _topic_endpoint(request, propose=False)


def _select(
    request: Request, state: CheckState, body: CheckBody
) -> tuple[Plan, str | None] | Response:
    """Provider selection, the free pass header and free-mode availability. Counts nothing."""
    plan = plan_connection(body, provider_key_header(request), state.settings)
    if isinstance(plan, Response):
        return plan
    pass_value = _free_header(request, plan, body)
    if isinstance(pass_value, Response):
        return pass_value
    if plan.preset is PresetId.FREE and not state.free_available:
        return error_response("free_mode_unavailable", 503)
    return plan, pass_value


# --- suggest ------------------------------------------------------------------------------------


async def _document_pass(
    settings: Settings, untrusted: UntrustedMaskedDocument
) -> PseudonymizedDocument | Response:
    """Check the masked document in the sandbox child, then make the gate object.

    The child bounds time and memory of the detector and proves that the pass ends. The gate
    object can only be made in this process, so the same pass runs here (in a thread) on the
    same, already accepted, input."""
    data = untrusted.model_dump_json().encode("utf-8")
    try:
        await run_safety_check(
            data, limits=sandbox_limits(settings), max_clauses=settings.segment_max_clauses
        )
    except SafetyRunError as error:
        return safety_error(error)
    try:
        return await asyncio.to_thread(
            safety_pass, untrusted, max_clauses=settings.segment_max_clauses
        )
    except SafetyError:
        return error_response("safety_failed", 422)


def _suggest_input(
    request: Request, state: CheckState, body: SuggestBody
) -> tuple[Plan, str | None] | Response:
    """Provider selection, domain and side, and the input cap. Counts nothing."""
    selected = _select(request, state, body)
    if isinstance(selected, Response):
        return selected
    if not catalog_of(request).has_side(body.domain, body.side):
        return error_response(INVALID_DEFINITION, 422)
    if sum(len(clause.text) for clause in body.document.clauses) > state.settings.suggest_max_chars:
        return error_response("document_too_large_for_suggest", 422)
    return selected


async def _suggest_parse(
    request: Request, state: CheckState, declared: int
) -> tuple[SuggestBody, Plan, str | None] | Response:
    settings = state.settings
    raw = await read_limited(request, declared, settings, settings.safety_max_body_bytes)
    if isinstance(raw, Response):
        return raw
    body = _parse(SuggestBody, raw)
    if isinstance(body, Response):
        return body
    selected = _suggest_input(request, state, body)
    if isinstance(selected, Response):
        return selected
    return body, selected[0], selected[1]


async def _suggest_extraction(
    request: Request, state: CheckState, declared: int
) -> Prepared | Response:
    """Everything that runs under the extraction slots: body, validation, count, safety pass."""
    parsed = await _suggest_parse(request, state, declared)
    if isinstance(parsed, Response):
        return parsed
    body, plan, pass_value = parsed
    hits = _count(state, client_key(request.scope, state.settings))
    if isinstance(hits, Response):
        return hits
    # Cheap free-mode checks before the expensive sandbox pass.
    refused = _pass_precheck(state, plan, pass_value, hits)
    if refused is not None:
        return refused
    document = await _document_pass(state.settings, body.document)
    if isinstance(document, Response):
        return document
    return Prepared(plan, pass_value, hits, suggest_job(document))


@router.post(SUGGEST_PATH)
async def suggest(request: Request) -> Response:
    state = check_state(request)
    settings = state.settings
    checked = check_upload_headers(
        request,
        max_bytes=settings.safety_max_body_bytes,
        too_large_code="request_too_large",
        accepted_media_type=ACCEPTED_MEDIA_TYPE,
    )
    if isinstance(checked, JSONResponse):
        return checked
    slots, pool = extraction_slots(request)
    key = client_key(request.scope, settings)
    # The extraction slots cover the body read and the sandbox, never the AI call.
    if not slots.try_acquire(key):
        return early_error("busy", 503, {"Retry-After": str(BUSY_RETRY_AFTER_SECONDS)})
    try:
        if not pool.try_acquire():
            return early_error("busy", 503, {"Retry-After": str(BUSY_RETRY_AFTER_SECONDS)})
        try:
            prepared = await _suggest_extraction(request, state, checked)
        finally:
            pool.release()
    finally:
        slots.release(key)
    if isinstance(prepared, Response):
        return prepared
    return await _ai_stage(state, prepared)


# --- the AI call --------------------------------------------------------------------------------


async def _ai_stage(state: CheckState, prepared: Prepared) -> Response:
    hits = prepared.hits
    try:
        with ai_slots(state, hits.day_key):
            return await _run(state, prepared)
    except BusyError:
        hits.refund()
        return busy()


async def _complete(provider: AIProvider, job: Job) -> BaseModel:
    """One call and at most one repair call (same inputs plus a fixed error code)."""
    repair = 0
    for _ in range(MAX_REPAIRS + 1):
        request = job.request(repair)
        try:
            raw = await provider.complete_json(request)
        except AIError as error:
            if error.code is not AIErrorCode.PROVIDER_BAD_RESPONSE:
                raise
            repair = REPAIR_NOT_JSON
            continue
        try:
            return job.schema.model_validate(raw)
        except ValidationError as error:
            too_long = any(item["type"] == "too_long" for item in error.errors())
            repair = REPAIR_CAP if too_long else REPAIR_SCHEMA
    raise BadOutputError


@dataclass(frozen=True)
class Outcome:
    """The reply body or an error; whether the model did no work; the Neurons the provider
    reported for the call (``None`` when unknown: the reservation then stands)."""

    result: dict[str, object] | JSONResponse
    no_cost: bool = False
    actual: int | None = None


async def _execute(
    state: CheckState, plan: Plan, key: SecretStr, free_account: str | None, job: Job
) -> Outcome:
    try:
        provider = make_provider(state, plan, key, free_account=free_account)
    except ConnectionConfigError as error:
        return Outcome(error_response(error.code, 422), no_cost=True)
    try:
        async with asyncio.timeout(state.settings.topic_ai_deadline_seconds):
            out = await _complete(provider, job)
        return Outcome(job.finish(out), actual=reported_neurons(provider))
    except BadOutputError:
        return Outcome(error_response("ai_bad_output", 502), actual=reported_neurons(provider))
    except AIError as error:
        return Outcome(
            error_response(error.code.value, AI_STATUS[error.code]),
            no_cost=error.code in AI_NO_COST,
        )
    except TimeoutError:
        return Outcome(error_response(AIErrorCode.PROVIDER_UNAVAILABLE.value, 502))


async def _run(state: CheckState, prepared: Prepared) -> Response:
    plan = prepared.plan
    if plan.preset is not PresetId.FREE:
        if plan.key is None:  # cheap validation guarantees a key for every non-free preset
            return error_response("invalid_provider_key", 422)
        outcome = await _execute(state, plan, plan.key, None, prepared.job)
        return outcome.result if isinstance(outcome.result, Response) else ok(outcome.result)
    return await _run_free(state, prepared)


def _pass_precheck(
    state: CheckState, plan: Plan, pass_value: str | None, hits: Hits
) -> Response | None:
    """The free-mode checks that need no network and count nothing: the pass is valid, or a
    Turnstile token is present and the table has room. ``None`` for a keyed provider."""
    if plan.preset is not PresetId.FREE:
        return None
    if pass_value is not None:
        try:
            state.passes.check(pass_value, hits.day_key)
        except FreePassError as error:
            return error_response(error.code, 403)
        return None
    if plan.token is None:
        return error_response("turnstile_failed", 403)
    if not state.passes.has_room(hits.day_key):
        hits.refund()
        return error_response("free_pass_unavailable", 503)
    return None


async def _free_admit(state: CheckState, prepared: Prepared) -> Response | None:
    """Pass or Turnstile checks of a free call. ``None`` when the call may go on."""
    refused = _pass_precheck(state, prepared.plan, prepared.pass_value, prepared.hits)
    if refused is not None:
        return refused
    if prepared.pass_value is None and not await verify_turnstile(state, prepared.plan.token):
        # Counted, not refunded: the rate limits bound a flood of bad tokens.
        return error_response("turnstile_failed", 403)
    return None


async def _run_free(state: CheckState, prepared: Prepared) -> Response:
    settings = state.settings
    token, account = settings.cf_ai_token, settings.cf_account_id
    if token is None or account is None:  # checked before; keeps the types honest
        return error_response("free_mode_unavailable", 503)
    refused = await _free_admit(state, prepared)
    if refused is not None:
        return refused
    # The worst case is reserved before the call; a pass call is consumed only after that.
    hits, neurons = prepared.hits, prepared.job.neurons()
    decision = state.quota.reserve_topic(hits.day_key, neurons)
    if not decision.allowed:
        if decision.reason != "ip":
            # The shared state refused, not this client: the request counts nothing.
            hits.refund()
        return limited("free_quota_exhausted", 429, decision.retry_after)
    claim = _claim(state, prepared.pass_value, hits.day_key)
    if isinstance(claim, Response):
        state.quota.settle_topic(neurons, 0)
        state.quota.refund_topic_call(hits.day_key)
        hits.refund()
        return claim
    spent = neurons
    try:
        outcome = await _execute(
            state, prepared.plan, token, account.get_secret_value(), prepared.job
        )
        if outcome.no_cost:
            spent = 0
            state.quota.refund_topic_call(hits.day_key)  # the model did no work
        elif outcome.actual is not None:
            # The reservation only admits the call; the reported cost is charged in full.
            spent = outcome.actual
    finally:
        state.quota.settle_topic(neurons, spent)
    return _free_reply(state, claim, outcome)


def _free_reply(state: CheckState, claim: Free, outcome: Outcome) -> Response:
    if isinstance(outcome.result, Response):
        # A pass call comes back only when the model did no work; a new pass is never given out.
        if claim.issued is not None:
            state.passes.discard(claim.nonce)
        elif outcome.no_cost:
            state.passes.refund(claim.nonce)
        return outcome.result
    if claim.issued is not None:
        return ok({**outcome.result, "free_pass": claim.issued})
    return ok(outcome.result)


def _claim(state: CheckState, pass_value: str | None, day_key: str) -> Free | Response:
    """Count the call against the pass, or issue a new pass (it replaces the client's old one)."""
    if pass_value is not None:
        try:
            return Free(state.passes.use(pass_value, day_key), None)
        except FreePassError as error:
            return error_response(error.code, 403)
    issued = state.passes.issue(day_key)
    if issued is None:
        return error_response("free_pass_unavailable", 503)
    return Free(issued[1], issued[0])
