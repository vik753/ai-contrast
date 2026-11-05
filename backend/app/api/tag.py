"""``POST /api/tag``: tag the clauses of one masked document with topics (S8-T2, ADR 0018).

Body (at most 4 MiB, no unknown field): the provider selection of ``/api/provider/check``
(``provider``, ``model`` = the cheap model, ``check_model`` = the strong model, ``base_url``,
``turnstile_token``; ``X-Provider-Key`` header), ``domain``, ``side``, the masked ``document``
exactly as ``/api/safety-check`` takes it and the topic ``topics`` selection. The reply holds
ids, enums, counts and offsets only: never clause text, topic text or model text.

Order: header and size checks, body, provider selection, topic resolution, size limits (nothing
counted so far), per-client rate limits, the free-mode pass checks, then the sandbox child
(safety pass, keyword tags, Layer 2) under the extraction slots, released before the AI slots
(per client and the pool shared with the checks and the topic calls), then for ``free`` Turnstile,
the free quota and the analysis pass, then the model steps under one overall deadline. The
worst case of all calls is reserved before the first call. Free mode: the first call sends a
Turnstile token and gets an ``analysis_pass`` in the reply; later calls send it in the
``X-Analysis-Pass`` header. Nothing here logs text; the log line holds counts only.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Final

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import SecretStr, ValidationError

from app.ai.port import AIProvider
from app.ai.presets import MODEL_PAIRS, ConnectionConfigError, PresetId, checked_model
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
    AI_STATUS,
    ANALYSIS_PASS_HEADER,
    BUSY_RETRY_AFTER_SECONDS,
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
from app.http_limits import TAG_PATH
from app.limits.client_ip import client_key, daily_key
from app.limits.free_pass import FreePassError
from app.limits.hits import Hits
from app.pseudo.untrusted import UntrustedMaskedDocument
from app.safety.child import digest_of
from app.safety.runner import SafetyRunError
from app.tagging.run import (
    JobPlan,
    JobRefusedError,
    Outcome,
    TagJob,
    plan_job,
    prepare_job,
    run_tagging,
)
from app.tagging.runner import KEYWORD_BUDGET_EXCEEDED
from app.topics.model import TopicDefinitionError
from app.topics.safety import TopicTextError
from app.topics.selection import TopicSelection, TopicSelectionError

router = APIRouter()

logger = logging.getLogger("ai_contrast.tagging")

_STATUS: Final = {"catalog_version_mismatch": 409}


class TagBody(CheckBody):
    check_model: str | None = None
    domain: str
    side: str
    document: UntrustedMaskedDocument
    topics: TopicSelection


@dataclass(frozen=True)
class Prepared:
    """Everything the AI stage needs."""

    plan: Plan
    check_plan: Plan
    pass_value: str | None
    hits: Hits
    job: TagJob


# --- request checks (nothing is counted) ----------------------------------------------------------


def _check_plan(plan: Plan, body: TagBody) -> Plan | Response:
    """The plan of the check calls: ``check_model``, else the strong model of the preset
    (``custom``: the model itself; ``free``: one model, no ``check_model``)."""
    if plan.preset is PresetId.FREE:
        if body.check_model is not None:
            return error_response("unexpected_model", 422)
        return plan
    if body.check_model is None:
        pair = MODEL_PAIRS.get(plan.preset)
        return plan if pair is None else plan.with_model(pair.strong)
    try:
        return plan.with_model(checked_model(body.check_model))
    except ConnectionConfigError as error:
        return error_response(error.code, 422)


def _select(  # noqa: PLR0911
    request: Request, state: CheckState, body: TagBody
) -> tuple[Plan, Plan, str | None] | Response:
    """Provider selection (both models), the pass header and free-mode availability."""
    plan = plan_connection(body, provider_key_header(request), state.settings)
    if isinstance(plan, Response):
        return plan
    check_plan = _check_plan(plan, body)
    if isinstance(check_plan, Response):
        return check_plan
    if plan.preset is PresetId.FREE and not state.free_available:
        return error_response("free_mode_unavailable", 503)
    values = request.headers.getlist(ANALYSIS_PASS_HEADER)
    if not values:
        return plan, check_plan, None
    if plan.preset is not PresetId.FREE:
        return error_response("unexpected_analysis_pass", 422)
    if body.turnstile_token is not None:
        return error_response("invalid_request", 422)
    if len(values) != 1:
        return error_response("analysis_pass_invalid", 403)
    return plan, check_plan, values[0]


def _plan(request: Request, state: CheckState, body: TagBody) -> JobPlan | Response:
    try:
        return plan_job(
            body.document, body.topics, catalog_of(request), state.settings, body.domain, body.side
        )
    except JobRefusedError as refusal:
        return error_response(refusal.code, refusal.status)
    except TopicSelectionError as error:
        return error_response(error.code, _STATUS.get(error.code, 422))
    except (TopicDefinitionError, TopicTextError) as error:
        return topic_error(error)


def _free_precheck(  # noqa: PLR0913, PLR0917, PLR0911
    state: CheckState,
    plan: Plan,
    pass_value: str | None,
    hits: Hits,
    calls: int,
    neurons: int,
    digest: str,
    chars: int,
) -> Response | None:
    """The free-mode checks that need no network and count nothing: the pass is valid or a
    Turnstile token is present and the table has room; the worst case fits the caps of the pass;
    the document fits the size rules. ``None`` for a keyed provider or when all is well."""
    if plan.preset is not PresetId.FREE:
        return None
    nonce: str | None = None
    if pass_value is not None:
        try:
            nonce = state.analysis.lookup(pass_value, hits.day_key)[0]
        except FreePassError as error:
            return error_response(error.code, 403)
    elif plan.token is None:
        return error_response("turnstile_failed", 403)
    elif not state.analysis.has_room(hits.day_key):
        hits.refund()
        return error_response("analysis_pass_unavailable", 503)
    size = state.analysis.size_error(nonce, digest, chars)
    if size is not None:
        return error_response(size, 422)
    if not state.analysis.fits(nonce, calls, neurons):
        return error_response("analysis_pass_exhausted", 403)
    return None


# --- the extraction stage ------------------------------------------------------------------------


async def _extraction(  # noqa: PLR0911
    request: Request, state: CheckState, declared: int
) -> Prepared | Response:
    """Everything that runs under the extraction slots: body, validation, count, sandbox."""
    settings = state.settings
    raw = await read_limited(request, declared, settings, settings.safety_max_body_bytes)
    if isinstance(raw, Response):
        return raw
    try:
        body = TagBody.model_validate_json(raw)
    except ValidationError:
        return error_response("invalid_request", 422)
    selected = _select(request, state, body)
    if isinstance(selected, Response):
        return selected
    plan, check_plan, pass_value = selected
    job_plan = _plan(request, state, body)
    if isinstance(job_plan, Response):
        return job_plan
    key = client_key(request.scope, settings)
    hits = Hits(state.tag_minute, state.tag_day, key, daily_key(key))
    refused = count_hits(hits)
    if refused is not None:
        return refused
    digest = digest_of(body.document.label, ((c.id, c.text) for c in body.document.clauses))
    precheck = _free_precheck(
        state, plan, pass_value, hits, job_plan.calls, job_plan.neurons, digest, job_plan.chars
    )
    if precheck is not None:
        return precheck
    try:
        job = await prepare_job(job_plan, body.document, settings, sandbox_limits(settings))
    except SafetyRunError as error:
        if error.code == KEYWORD_BUDGET_EXCEEDED:
            return error_response(KEYWORD_BUDGET_EXCEEDED, 422)
        return safety_error(error)
    except JobRefusedError as refusal:
        return error_response(refusal.code, refusal.status)
    return Prepared(plan, check_plan, pass_value, hits, job)


@router.post(TAG_PATH)
async def tag(request: Request) -> Response:
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
    retry = {"Retry-After": str(BUSY_RETRY_AFTER_SECONDS)}
    # The extraction slots cover the body read and the sandbox, never the AI calls.
    if not slots.try_acquire(key):
        return early_error("busy", 503, retry)
    try:
        if not pool.try_acquire():
            return early_error("busy", 503, retry)
        try:
            prepared = await _extraction(request, state, checked)
        finally:
            pool.release()
    finally:
        slots.release(key)
    if isinstance(prepared, Response):
        return prepared
    try:
        with ai_slots(state, prepared.hits.day_key):
            return await _run(state, prepared)
    except BusyError:
        prepared.hits.refund()
        return busy()


# --- the model steps ---------------------------------------------------------------------------


async def _tagging(
    state: CheckState, prepared: Prepared, key: SecretStr, free_account: str | None
) -> Outcome | Response:
    """Build the providers (one per distinct model) and run the job."""
    try:
        tag_provider = make_provider(state, prepared.plan, key, free_account=free_account)
        check_provider: AIProvider = tag_provider
        if prepared.check_plan.model != prepared.plan.model:
            check_provider = make_provider(
                state, prepared.check_plan, key, free_account=free_account
            )
    except ConnectionConfigError as error:
        return error_response(error.code, 422)
    return await run_tagging(
        prepared.job, tag_provider, check_provider, state.settings, state.signer
    )


def _finish(outcome: Outcome, issued: str | None) -> Response:
    if outcome.reply is None:
        code = outcome.hard
        if code is None:  # a hard error always carries its code
            return error_response("provider_bad_response", 502)
        return error_response(code.value, AI_STATUS[code])
    if issued is not None:
        return ok({**outcome.reply, "analysis_pass": issued})
    return ok(outcome.reply)


async def _run(state: CheckState, prepared: Prepared) -> Response:
    started = time.monotonic()
    plan = prepared.plan
    if plan.preset is not PresetId.FREE:
        if plan.key is None:  # cheap validation guarantees a key for every non-free preset
            return error_response("invalid_provider_key", 422)
        done = await _tagging(state, prepared, plan.key, None)
        response = done if isinstance(done, Response) else _finish(done, None)
    else:
        response = await _run_free(state, prepared)
    logger.info(
        "tag status=%d batches=%d clauses=%d duration_ms=%d",
        response.status_code,
        len(prepared.job.plan.batches),
        len(prepared.job.document.clauses),
        (time.monotonic() - started) * 1000,
    )
    return response


# --- free mode: admission, reservation and settlement ---------------------------------------------


def _reserve(state: CheckState, prepared: Prepared) -> tuple[str, str | None] | Response:
    """Reserve the worst case from the quota and the pass (or issue a new pass).

    Returns the pass nonce and the pass text when this call issued it. On a refusal nothing
    stays reserved and the request counts nothing."""
    plan = prepared.job.plan
    hits, pass_value = prepared.hits, prepared.pass_value
    start = pass_value is None
    decision = state.quota.reserve_analysis(hits.day_key, plan.neurons, start=start)
    if not decision.allowed:
        if decision.reason != "ip":
            # The shared state refused, not this client: the request counts nothing.
            hits.refund()
        return limited("free_quota_exhausted", 429, decision.retry_after)
    claim = _claim(state, prepared)
    if isinstance(claim, Response):
        state.quota.settle_analysis(plan.neurons, 0)
        if start:
            state.quota.refund_call(hits.day_key)
        hits.refund()
    return claim


def _claim(state: CheckState, prepared: Prepared) -> tuple[str, str | None] | Response:
    """Take the worst case from the pass, or issue a new pass (it replaces the client's old one)."""
    hits, pass_value, plan = prepared.hits, prepared.pass_value, prepared.job.plan
    issued: str | None = None
    if pass_value is not None:
        try:
            nonce = state.analysis.check(pass_value, hits.day_key)
        except FreePassError as error:
            return error_response(error.code, 403)
    else:
        made = state.analysis.issue(hits.day_key)
        if made is None:
            return error_response("analysis_pass_unavailable", 503)
        issued, nonce = made
    state.analysis.reserve(nonce, plan.calls, plan.neurons, prepared.job.child.digest, plan.chars)
    return nonce, issued


def _settle(  # noqa: PLR0913
    state: CheckState, prepared: Prepared, nonce: str, calls: int, spent: int, *, refund: bool
) -> None:
    plan = prepared.job.plan
    state.quota.settle_analysis(plan.neurons, spent)
    state.analysis.settle(nonce, (plan.calls, calls), (plan.neurons, spent))
    if refund:
        state.quota.refund_call(prepared.hits.day_key)  # the model did no work


async def _run_free(state: CheckState, prepared: Prepared) -> Response:
    settings = state.settings
    token, account = settings.cf_ai_token, settings.cf_account_id
    if token is None or account is None:  # checked before; keeps the types honest
        return error_response("free_mode_unavailable", 503)
    plan, hits, pass_value = prepared.job.plan, prepared.hits, prepared.pass_value
    if pass_value is None and not await verify_turnstile(state, prepared.plan.token):
        # Counted, not refunded: the rate limits bound a flood of bad tokens.
        return error_response("turnstile_failed", 403)
    # The pass table is checked again: the state may have changed while the sandbox ran.
    refused = _free_precheck(
        state,
        prepared.plan,
        pass_value,
        hits,
        plan.calls,
        plan.neurons,
        prepared.job.child.digest,
        plan.chars,
    )
    if refused is not None:
        return refused
    claim = _reserve(state, prepared)
    if isinstance(claim, Response):
        return claim
    nonce, issued = claim
    calls, spent = plan.calls, plan.neurons
    done: Outcome | Response | None = None
    try:
        done = await _tagging(state, prepared, token, account.get_secret_value())
        if isinstance(done, Response):  # the model did no work
            calls, spent = 0, 0
        else:
            calls, spent = done.calls, done.spent
    finally:
        # A cancelled or failed run keeps the reserved worst case.
        _settle(state, prepared, nonce, calls, spent, refund=pass_value is None and calls == 0)
    failed = isinstance(done, Response) or done.reply is None
    if failed and issued is not None:
        state.analysis.discard(nonce)  # a new pass is never given out with an error
    return done if isinstance(done, Response) else _finish(done, issued)
