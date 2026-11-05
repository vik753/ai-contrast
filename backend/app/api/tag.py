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

import asyncio
import logging
import time
from dataclasses import dataclass, replace
from typing import Final, get_args

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import SecretStr, ValidationError

from app.ai.port import AIError, AIProvider
from app.ai.presets import ConnectionConfigError, PresetId, checked_model
from app.api.ai_shared import (
    ACCEPTED_MEDIA_TYPE,
    busy,
    ok,
    read_limited,
    reported_neurons,
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
from app.pseudo.gate import ConfirmedTopic, PseudonymizedDocument, SafetyError, safety_pass
from app.pseudo.untrusted import UntrustedMaskedDocument
from app.safety.child import digest_of
from app.safety.runner import SafetyRunError
from app.settings import Settings
from app.tagging.ai_steps import ModelState, run_model_steps
from app.tagging.batches import MAX_BATCHES, plan_batches, worst_case
from app.tagging.child import ChildTopic
from app.tagging.clauses import clauses_of
from app.tagging.merge import Failure, TaggingResult, merge_tags
from app.tagging.runner import KEYWORD_BUDGET_EXCEEDED, TagChildOk, run_tag_child
from app.tagging.version import tagging_version
from app.topics.catalog import Catalog
from app.topics.model import TopicDefinitionError
from app.topics.safety import TopicTextError
from app.topics.selection import TopicSelection, TopicSelectionError, resolve_topics

router = APIRouter()

logger = logging.getLogger("ai_contrast.tagging")

INVALID_DEFINITION: Final = "invalid_topic_definition"
_FAILURES: Final = frozenset(get_args(Failure))
_STATUS: Final = {"catalog_version_mismatch": 409}


class TagBody(CheckBody):
    check_model: str | None = None
    domain: str
    side: str
    document: UntrustedMaskedDocument
    topics: TopicSelection


@dataclass(frozen=True)
class Prepared:
    """Everything the AI stage needs. ``calls`` and ``neurons`` are the worst case."""

    plan: Plan
    check_plan: Plan
    pass_value: str | None
    hits: Hits
    document: PseudonymizedDocument
    topics: tuple[ConfirmedTopic, ...]
    child: TagChildOk
    batches: tuple[tuple[str, ...], ...]
    calls: int
    neurons: int
    chars: int


@dataclass(frozen=True)
class Outcome:
    """The reply or an error; the AI calls made; the Neurons spent (``None``: no model work)."""

    result: dict[str, object] | JSONResponse
    calls: int = 0
    spent: int = 0
    no_cost: bool = False


# --- request checks (nothing is counted) ----------------------------------------------------------


def _select(  # noqa: PLR0911
    request: Request, state: CheckState, body: TagBody
) -> tuple[Plan, Plan, str | None] | Response:
    """Provider selection (both models), the pass header and free-mode availability."""
    plan = plan_connection(body, provider_key_header(request), state.settings)
    if isinstance(plan, Response):
        return plan
    check_plan = plan
    if plan.preset is PresetId.FREE:
        if body.check_model is not None:
            return error_response("unexpected_model", 422)
        if not state.free_available:
            return error_response("free_mode_unavailable", 503)
    elif body.check_model is not None:
        try:
            check_plan = replace(plan, model=checked_model(body.check_model))
        except ConnectionConfigError as error:
            return error_response(error.code, 422)
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


def _resolve(request: Request, body: TagBody) -> tuple[ConfirmedTopic, ...] | Response:
    catalog: Catalog = catalog_of(request)
    if not catalog.has_side(body.domain, body.side):
        return error_response(INVALID_DEFINITION, 422)
    try:
        topics = resolve_topics(body.topics, catalog)
    except TopicSelectionError as error:
        return error_response(error.code, _STATUS.get(error.code, 422))
    except (TopicDefinitionError, TopicTextError) as error:
        return topic_error(error)
    if not topics:
        return error_response("no_topics", 422)
    if len({topic.topic_id for topic in topics}) != len(topics):
        return error_response("duplicate_topic", 422)
    return topics


def _limits(
    settings: Settings, body: TagBody, topics: tuple[ConfirmedTopic, ...]
) -> tuple[tuple[tuple[str, ...], ...], int, int, int] | Response:
    """Batches, the worst case ``(calls, Neurons)`` and the characters of clause text."""
    lengths = [len(clause.text) for clause in body.document.clauses]
    chars = sum(lengths)
    ranges = plan_batches(lengths)
    if chars > settings.tag_max_document_chars or len(ranges) > MAX_BATCHES:
        return error_response("document_too_large_for_tagging", 422)
    ids = [clause.id for clause in body.document.clauses]
    batches = tuple(tuple(ids[start:end]) for start, end in ranges)
    calls, neurons = worst_case(ranges, lengths, topics)
    return batches, calls, neurons, chars


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


# --- sandbox -------------------------------------------------------------------------------------


async def _document_pass(
    settings: Settings, body: TagBody, topics: tuple[ConfirmedTopic, ...]
) -> tuple[PseudonymizedDocument, TagChildOk] | Response:
    """Run the sandbox child, then make the gate object (it can only be made in this process,
    so the same pass runs here, in a thread, on the same already accepted input)."""
    child_topics = [
        ChildTopic(
            topic_id=topic.topic_id,
            synonyms_en=list(topic.synonyms_en),
            synonyms_uk=list(topic.synonyms_uk),
            synonyms_ru=list(topic.synonyms_ru),
        )
        for topic in topics
    ]
    try:
        child = await run_tag_child(
            body.document,
            child_topics,
            keyword_budget=settings.keyword_step_budget,
            limits=sandbox_limits(settings),
            max_clauses=settings.segment_max_clauses,
        )
    except SafetyRunError as error:
        if error.code == KEYWORD_BUDGET_EXCEEDED:
            return error_response(KEYWORD_BUDGET_EXCEEDED, 422)
        return safety_error(error)
    try:
        document = await asyncio.to_thread(
            safety_pass, body.document, max_clauses=settings.segment_max_clauses
        )
    except SafetyError:
        return error_response("safety_failed", 422)
    return document, child


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
    topics = _resolve(request, body)
    if isinstance(topics, Response):
        return topics
    limits = _limits(settings, body, topics)
    if isinstance(limits, Response):
        return limits
    batches, calls, neurons, chars = limits
    key = client_key(request.scope, settings)
    hits = Hits(state.tag_minute, state.tag_day, key, daily_key(key))
    refused = count_hits(hits)
    if refused is not None:
        return refused
    digest = digest_of(body.document.label, ((c.id, c.text) for c in body.document.clauses))
    precheck = _free_precheck(state, plan, pass_value, hits, calls, neurons, digest, chars)
    if precheck is not None:
        return precheck
    passed = await _document_pass(settings, body, topics)
    if isinstance(passed, Response):
        return passed
    document, child = passed
    return Prepared(
        plan, check_plan, pass_value, hits, document, topics, child, batches, calls, neurons, chars
    )


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


# --- the model steps and the reply ------------------------------------------------------------


def _merge_failures(failures: set[str]) -> list[Failure]:
    """The failures that ``merge_tags`` knows; a failed check is handled by the caller."""
    return [f for f in sorted(failures) if f in _FAILURES and f != "check_failed"]  # type: ignore[misc]


def _reply(
    state: CheckState, prepared: Prepared, result: TaggingResult, model: ModelState
) -> dict[str, object]:
    reasons = set(result.incomplete_reasons)
    if "check_failed" in model.failures:
        reasons.add("check_failed")
    version = tagging_version()
    digest = prepared.child.digest
    signature = state.signer.sign(
        digest=digest,
        tagging_version=version,
        tags={clause_id: dict(by_topic) for clause_id, by_topic in result.tags.items()},
    )
    return {
        "digest": digest,
        "tagging_version": version,
        "signature": signature,
        "tags": {
            clause_id: [{"topic_id": topic, "source": source} for topic, source in by_topic.items()]
            for clause_id, by_topic in result.tags.items()
        },
        "other": result.other,
        "risk": {
            clause_id: [list(span) for span in spans] for clause_id, spans in result.risk.items()
        },
        "topics": {
            topic_id: {
                "keyword_clauses": status.keyword_clauses,
                "model_clauses": status.model_clauses,
                "model_asserted": status.model_asserted,
                "model_tags_dropped": status.model_tags_dropped,
                "not_analyzed": status.not_analyzed,
            }
            for topic_id, status in result.topics.items()
        },
        "missing_topics": [] if reasons else list(result.missing_topics),
        "layer2": {
            clause_id: {
                "text": [list(hit) for hit in hits.text],
                "heading": [list(hit) for hit in hits.heading],
            }
            for clause_id, hits in prepared.child.layer2.items()
        },
        "model_tagging_incomplete": bool(reasons),
        "incomplete_reasons": sorted(reasons),
    }


def _spent(providers: list[AIProvider], worst: int) -> int:
    """Neurons spent: the reported usage; the worst case when a provider reports none."""
    total = 0
    for provider in providers:
        reported = reported_neurons(provider)
        if reported is None:
            return worst
        total += reported
    return total


def _hard(error: AIError, model: ModelState, spent: int) -> Outcome:
    no_cost = error.code in AI_NO_COST
    return Outcome(
        error_response(error.code.value, AI_STATUS[error.code]),
        calls=model.calls,
        spent=spent,
        no_cost=no_cost,
    )


async def _tagging(
    state: CheckState, prepared: Prepared, key: SecretStr, free_account: str | None
) -> Outcome:
    """The model steps under the overall deadline, the merge and the reply."""
    settings = state.settings
    try:
        tag_provider = make_provider(state, prepared.plan, key, free_account=free_account)
        same = prepared.check_plan.model == prepared.plan.model
        check_provider = (
            tag_provider
            if same
            else make_provider(state, prepared.check_plan, key, free_account=free_account)
        )
    except ConnectionConfigError as error:
        return Outcome(error_response(error.code, 422), no_cost=True)
    providers = [tag_provider] if same else [tag_provider, check_provider]
    model = ModelState()
    try:
        async with asyncio.timeout(settings.tag_deadline_seconds):
            await run_model_steps(
                prepared.document,
                prepared.topics,
                prepared.batches,
                tag_provider,
                check_provider,
                model,
                settings.tag_call_deadline_seconds,
            )
    except TimeoutError:
        model.failures.add("timeout")
    except AIError as error:
        return _hard(error, model, _spent(providers, 0) if model.calls else 0)
    spent = _spent(providers, prepared.neurons)
    result = await asyncio.to_thread(
        merge_tags,
        clauses=clauses_of(prepared.document),
        topics=prepared.topics,
        keyword=prepared.child.keyword_sets(),
        model_high=model.high,
        model_low=model.low,
        check_yes=model.check_yes,
        failures=_merge_failures(model.failures),
    )
    return Outcome(_reply(state, prepared, result, model), calls=model.calls, spent=spent)


async def _run(state: CheckState, prepared: Prepared) -> Response:
    started = time.monotonic()
    plan = prepared.plan
    if plan.preset is not PresetId.FREE:
        if plan.key is None:  # cheap validation guarantees a key for every non-free preset
            return error_response("invalid_provider_key", 422)
        outcome = await _tagging(state, prepared, plan.key, None)
        response = _finish(outcome, None)
    else:
        response = await _run_free(state, prepared)
    logger.info(
        "tag status=%d batches=%d clauses=%d duration_ms=%d",
        response.status_code,
        len(prepared.batches),
        len(prepared.document.clauses),
        (time.monotonic() - started) * 1000,
    )
    return response


def _finish(outcome: Outcome, issued: str | None) -> Response:
    if isinstance(outcome.result, Response):
        return outcome.result
    if issued is not None:
        return ok({**outcome.result, "analysis_pass": issued})
    return ok(outcome.result)


async def _run_free(  # noqa: PLR0911
    state: CheckState, prepared: Prepared
) -> Response:
    settings = state.settings
    token, account = settings.cf_ai_token, settings.cf_account_id
    if token is None or account is None:  # checked before; keeps the types honest
        return error_response("free_mode_unavailable", 503)
    hits, pass_value = prepared.hits, prepared.pass_value
    if pass_value is None and not await verify_turnstile(state, prepared.plan.token):
        # Counted, not refunded: the rate limits bound a flood of bad tokens.
        return error_response("turnstile_failed", 403)
    # The worst case is reserved before the first call (the pass table is checked again, the
    # state may have changed while the sandbox ran).
    refused = _free_precheck(
        state,
        prepared.plan,
        pass_value,
        hits,
        prepared.calls,
        prepared.neurons,
        prepared.child.digest,
        prepared.chars,
    )
    if refused is not None:
        return refused
    start = pass_value is None
    decision = state.quota.reserve_analysis(hits.day_key, prepared.neurons, start=start)
    if not decision.allowed:
        if decision.reason != "ip":
            # The shared state refused, not this client: the request counts nothing.
            hits.refund()
        return limited("free_quota_exhausted", 429, decision.retry_after)
    claim = _claim(state, prepared)
    if isinstance(claim, Response):
        state.quota.settle_analysis(prepared.neurons, 0)
        if start:
            state.quota.refund_call(hits.day_key)
        hits.refund()
        return claim
    nonce, issued = claim
    spent = prepared.neurons
    calls = prepared.calls
    try:
        outcome = await _tagging(state, prepared, token, account.get_secret_value())
        calls, spent = outcome.calls, outcome.spent
        if outcome.no_cost:
            spent = 0 if not outcome.calls else outcome.spent
            if start and not outcome.calls:
                state.quota.refund_call(hits.day_key)  # the model did no work
    finally:
        state.quota.settle_analysis(prepared.neurons, spent)
        state.analysis.settle(nonce, (prepared.calls, calls), (prepared.neurons, spent))
    if isinstance(outcome.result, Response) and issued is not None:
        state.analysis.discard(nonce)  # a new pass is never given out with an error
        return outcome.result
    return _finish(outcome, issued)


def _claim(state: CheckState, prepared: Prepared) -> tuple[str, str | None] | Response:
    """Take the worst case from the pass, or issue a new pass (it replaces the client's old one).

    Returns the nonce and the pass text when this call issued it."""
    hits, pass_value = prepared.hits, prepared.pass_value
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
    state.analysis.reserve(
        nonce, prepared.calls, prepared.neurons, prepared.child.digest, prepared.chars
    )
    return nonce, issued
