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
    AIRequest,
)
from app.ai.presets import ConnectionConfigError, PresetId
from app.api.common import (
    BodyRejectedError,
    check_upload_headers,
    early_error,
    error_response,
    read_body,
    sandbox_limits,
)
from app.api.provider_check import (
    AI_NO_COST,
    AI_STATUS,
    BUSY_RETRY_AFTER_SECONDS,
    FREE_PASS_HEADER,
    CheckBody,
    CheckState,
    Plan,
    check_state,
    limited,
    make_provider,
    plan_connection,
    verify_turnstile,
)
from app.api.provider_key import provider_key_header
from app.http_limits import EXPAND_PATH, PROPOSE_PATH, SUGGEST_PATH, TOPIC_MAX_BODY_BYTES
from app.limits.client_ip import client_key, daily_key
from app.limits.free import TOPIC_NEURONS
from app.limits.free_pass import FreePassError
from app.pseudo.gate import (
    ConfirmedTopic,
    PseudonymizedDocument,
    SafetyError,
    confirm_topic,
    safety_pass,
)
from app.pseudo.untrusted import UntrustedMaskedDocument
from app.safety.runner import (
    MISMATCH,
    SAFETY_TIMEOUT,
    UNMASKED,
    SafetyRunError,
    run_safety_check,
)
from app.settings import Settings
from app.topics.catalog import Catalog
from app.topics.jobs import BadOutputError, Job, expand_job, propose_job, suggest_job
from app.topics.model import TopicDefinition, TopicDefinitionError
from app.topics.safety import TopicTextError

router = APIRouter()

NO_STORE: Final = {"Cache-Control": "no-store"}
INVALID_DEFINITION: Final = "invalid_topic_definition"
ACCEPTED_MEDIA_TYPE: Final = "application/json"
MAX_REPAIRS: Final = 1


class SuggestBody(CheckBody):
    domain: str
    side: str
    document: UntrustedMaskedDocument


class TopicBody(CheckBody):
    topic: TopicDefinition


@dataclass
class Hits:
    """The rate-limit hits that one request counted, so only they can be refunded."""

    state: CheckState
    minute_key: str
    day_key: str
    minute: bool = False
    day: bool = False

    def refund(self) -> None:
        if self.day:
            self.state.topic_day.refund(self.day_key)
            self.day = False
        if self.minute:
            self.state.topic_minute.refund(self.minute_key)
            self.minute = False


@dataclass
class Free:
    """The free pass of one free call: the nonce, and the pass text if this call issued it."""

    nonce: str
    issued: str | None


def _busy() -> JSONResponse:
    return limited("busy", 503, BUSY_RETRY_AFTER_SECONDS)


def _topic_error(error: TopicTextError | TopicDefinitionError) -> JSONResponse:
    body: dict[str, object] = {"error": error.code}
    if isinstance(error, TopicTextError):
        if error.field is not None:
            body["field"] = error.field
        if error.spans:
            body["spans"] = [list(span) for span in error.spans]
    return JSONResponse(body, status_code=422)


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
        return _topic_error(error)


def _free_header(request: Request, plan: Plan, body: CheckBody) -> Response | str | None:
    """The pass of the request, ``None`` if there is none, or a refusal."""
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
    hits = Hits(state, key, daily_key(key))
    decision = state.topic_minute.hit(hits.minute_key)
    if not decision.allowed:
        return limited("rate_limited", 429, decision.retry_after)
    hits.minute = True
    decision = state.topic_day.hit(hits.day_key)
    if not decision.allowed:
        hits.refund()
        return limited("rate_limited", 429, decision.retry_after)
    hits.day = True
    return hits


async def _read(request: Request, declared: int, settings: Settings, cap: int) -> bytes | Response:
    try:
        return await read_body(
            request, declared, settings, max_bytes=cap, too_large_code="request_too_large"
        )
    except BodyRejectedError as rejected:
        return early_error(rejected.code, rejected.status)


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
    raw = await _read(request, checked, state.settings, TOPIC_MAX_BODY_BYTES)
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
    topic = _confirm(body.topic, request.app.state.catalog, no_attributes=propose)
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


def _safety_error(error: SafetyRunError) -> JSONResponse:
    if error.code == UNMASKED:
        spans = [list(span) for span in error.spans]
        return JSONResponse({"error": error.code, "spans": spans}, status_code=422)
    status = 409 if error.code == MISMATCH else 504 if error.code == SAFETY_TIMEOUT else 422
    return error_response(error.code, status)


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
        return _safety_error(error)
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
    if not request.app.state.catalog.has_side(body.domain, body.side):
        return error_response(INVALID_DEFINITION, 422)
    if sum(len(clause.text) for clause in body.document.clauses) > state.settings.suggest_max_chars:
        return error_response("document_too_large_for_suggest", 422)
    return selected


async def _suggest_extraction(
    request: Request, state: CheckState, declared: int
) -> Prepared | Response:
    """Everything that runs under the extraction slots: body, validation, count, safety pass."""
    settings = state.settings
    raw = await _read(request, declared, settings, settings.safety_max_body_bytes)
    if isinstance(raw, Response):
        return raw
    body = _parse(SuggestBody, raw)
    if isinstance(body, Response):
        return body
    selected = _suggest_input(request, state, body)
    if isinstance(selected, Response):
        return selected
    hits = _count(state, client_key(request.scope, settings))
    if isinstance(hits, Response):
        return hits
    document = await _document_pass(settings, body.document)
    if isinstance(document, Response):
        return document
    return Prepared(selected[0], selected[1], hits, suggest_job(document))


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
    slots = request.app.state.client_slots
    pool = request.app.state.extraction_limiter
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
    # One AI call per client first, then the pool shared with the check; both always released.
    if not state.client_slots.try_acquire(hits.day_key):
        hits.refund()
        return _busy()
    try:
        slot = state.slots.try_slot()
        if slot is None:
            hits.refund()
            return _busy()
        with slot:
            return await _run(state, prepared)
    finally:
        state.client_slots.release(hits.day_key)


async def _complete(provider: AIProvider, job: Job) -> BaseModel:
    """One call and at most one repair call (same inputs plus a fixed error code)."""
    repair = 0
    for _ in range(MAX_REPAIRS + 1):
        request = AIRequest(
            job.template,
            job.schema,
            job.max_tokens,
            document=job.document,
            topic=job.topic,
            repair=repair,
        )
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


async def _execute(
    state: CheckState, plan: Plan, key: SecretStr, free_account: str | None, job: Job
) -> tuple[dict[str, object] | JSONResponse, bool]:
    """The reply body or an error, and whether the model did no work (for the budget)."""
    try:
        provider = make_provider(state, plan, key, free_account=free_account)
        async with asyncio.timeout(state.settings.topic_ai_deadline_seconds):
            out = await _complete(provider, job)
        return job.finish(out), False
    except ConnectionConfigError as error:
        return error_response(error.code, 422), True
    except BadOutputError:
        return error_response("ai_bad_output", 502), False
    except AIError as error:
        return error_response(error.code.value, AI_STATUS[error.code]), error.code in AI_NO_COST
    except TimeoutError:
        return error_response(AIErrorCode.PROVIDER_UNAVAILABLE.value, 502), False


def _ok(body: dict[str, object]) -> JSONResponse:
    return JSONResponse(body, headers=NO_STORE)


async def _run(state: CheckState, prepared: Prepared) -> Response:
    plan = prepared.plan
    if plan.preset is not PresetId.FREE:
        if plan.key is None:  # cheap validation guarantees a key for every non-free preset
            return error_response("invalid_provider_key", 422)
        result, _ = await _execute(state, plan, plan.key, None, prepared.job)
        return result if isinstance(result, Response) else _ok(result)
    return await _run_free(state, prepared)


async def _free_claim(state: CheckState, prepared: Prepared) -> Free | Response:
    """Use the pass, or verify Turnstile and issue a new one."""
    client = prepared.hits.day_key
    if prepared.pass_value is not None:
        try:
            return Free(state.passes.use(prepared.pass_value, client), None)
        except FreePassError as error:
            return error_response(error.code, 403)
    if not state.passes.has_room():
        prepared.hits.refund()
        return error_response("free_pass_unavailable", 503)
    if not await verify_turnstile(state, prepared.plan.token):
        # Counted, not refunded: the rate limits bound a flood of bad tokens.
        return error_response("turnstile_failed", 403)
    issued = state.passes.issue(client)
    if issued is None:
        prepared.hits.refund()
        return error_response("free_pass_unavailable", 503)
    return Free(issued[1], issued[0])


def _undo(state: CheckState, free: Free) -> None:
    """Take back the pass call (or the whole new pass) of a call that did not happen."""
    if free.issued is None:
        state.passes.refund(free.nonce)
    else:
        state.passes.discard(free.nonce)


async def _run_free(state: CheckState, prepared: Prepared) -> Response:
    settings = state.settings
    token, account = settings.cf_ai_token, settings.cf_account_id
    if token is None or account is None:  # checked before; keeps the types honest
        return error_response("free_mode_unavailable", 503)
    claim = await _free_claim(state, prepared)
    if isinstance(claim, Response):
        return claim
    key = prepared.hits.day_key
    decision = state.quota.reserve_topic(key, TOPIC_NEURONS)
    if not decision.allowed:
        _undo(state, claim)
        if decision.reason != "ip":
            # The shared state refused, not this client: the request counts nothing.
            prepared.hits.refund()
        return limited("free_quota_exhausted", 429, decision.retry_after)
    spent = TOPIC_NEURONS
    try:
        result, no_cost = await _execute(
            state, prepared.plan, token, account.get_secret_value(), prepared.job
        )
        if no_cost:
            spent = 0
            state.quota.refund_topic_call(key)  # the model did no work
    finally:
        state.quota.settle_topic(TOPIC_NEURONS, spent)
    if isinstance(result, Response):
        _undo(state, claim)
        return result
    if claim.issued is not None:
        result = {**result, "free_pass": claim.issued}
    return _ok(result)
