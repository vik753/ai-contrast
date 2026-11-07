"""``POST /api/analyze``: rate one masked document, streamed as Server-Sent Events (S9-T3,
ADR 0019 points 1, 3, 6, 7 and 8).

Body (at most 2 MiB, no unknown field): the provider selection of ``/api/tag`` (``provider``,
``model`` = the rating model, ``base_url``; ``X-Provider-Key`` header; no ``check_model``, no
``turnstile_token``), ``domain``, ``side``, the masked ``document``, the ``topics`` selection, the
UI ``language``, the ``tagging`` result of ``/api/tag`` with its signature plus add-only
``client_tags``, the browser ``flags`` and the ``annex_links`` the client made. Free mode sends the
``X-Analysis-Pass`` header only.

Every refusal is a normal JSON reply before the first stream byte. Order: size and JSON,
provider selection, topic selection, rate limit, the pass, the sandbox (safety, keyword tags,
Layer 2), the tag signature, client tags, the size and call limits, the pass documents and caps,
the AI slots, the quota. The worst case of all calls is reserved before the first call and
settled after the stream (cancelled or unfinished calls at the worst case). This module only
routes; the analysis lives in ``app.analysis``. Nothing here logs text: the log line holds counts.
"""

from __future__ import annotations

import logging
import time
from contextlib import ExitStack
from dataclasses import dataclass
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from app.ai.port import AIProvider, OutputLanguage
from app.ai.presets import MODEL_PAIRS, REASONING_EFFORT, ConnectionConfigError, PresetId
from app.analysis.execute import CountingProvider
from app.analysis.plan import (
    AnalysisPlan,
    AnalysisRequest,
    DocFacts,
    SignedStatus,
    make_facts,
    plan_analysis,
    recompute_tags,
    verify_tagging,
)
from app.analysis.run import Emit, stream_analysis
from app.analysis.verify import DocFlag
from app.api.ai_shared import (
    ACCEPTED_MEDIA_TYPE,
    busy,
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
)
from app.api.provider_key import provider_key_header
from app.api.sse import SseResponse
from app.api.topics import catalog_of
from app.http_limits import ANALYZE_MAX_BODY_BYTES, ANALYZE_PATH
from app.limits.client_ip import client_key, daily_key
from app.limits.free import reported_neurons
from app.limits.free_pass import FreePassError
from app.limits.hits import Hits
from app.pseudo.untrusted import UntrustedMaskedDocument
from app.safety.runner import SafetyRunError
from app.tagging.run import JobPlan, JobRefusedError, TagJob, plan_job, prepare_job
from app.tagging.runner import KEYWORD_BUDGET_EXCEEDED
from app.topics.model import TopicDefinitionError
from app.topics.safety import TopicTextError
from app.topics.selection import TopicSelection, TopicSelectionError

router = APIRouter()

logger = logging.getLogger("ai_contrast.analysis")

_STATUS: Final = {"catalog_version_mismatch": 409}
MAX_CLAUSES: Final = 10_000


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class TagEntryIn(_Strict):
    topic_id: Annotated[str, Field(max_length=64)]
    source: Literal["keyword", "model", "check", "client"]


class TopicStatusIn(_Strict):
    keyword_clauses: int = 0
    model_clauses: int = 0
    model_asserted: int = 0
    model_tags_dropped: bool
    not_analyzed: Annotated[str, Field(max_length=32)] | None = None


class TaggingIn(_Strict):
    digest: Annotated[str, Field(max_length=64)]
    tagging_version: Annotated[str, Field(max_length=64)]
    signature: Annotated[str, Field(max_length=128)]
    tags: Annotated[
        dict[
            Annotated[str, Field(max_length=16)], Annotated[list[TagEntryIn], Field(max_length=40)]
        ],
        Field(max_length=MAX_CLAUSES),
    ]
    incomplete_reasons: Annotated[list[Annotated[str, Field(max_length=32)]], Field(max_length=8)]
    topics: Annotated[
        dict[Annotated[str, Field(max_length=64)], TopicStatusIn], Field(max_length=64)
    ]
    client_tags: Annotated[
        dict[
            Annotated[str, Field(max_length=16)],
            Annotated[list[Annotated[str, Field(max_length=64)]], Field(max_length=20)],
        ],
        Field(max_length=MAX_CLAUSES, default_factory=dict),
    ]


class AnalyzeBody(CheckBody):
    domain: str
    side: str
    document: UntrustedMaskedDocument
    topics: TopicSelection
    language: Literal["en", "uk", "ru"]
    tagging: TaggingIn
    flags: Annotated[
        list[Literal["not_read_material", "hidden_text_removed"]],
        Field(max_length=2, default_factory=list),
    ]
    annex_links: Annotated[
        list[Annotated[str, Field(max_length=16)]],
        Field(max_length=MAX_CLAUSES, default_factory=list),
    ]


@dataclass(frozen=True)
class Prepared:
    """Everything the stream needs."""

    plan: Plan
    pass_value: str | None
    hits: Hits
    job: TagJob
    request: AnalysisRequest
    facts: DocFacts
    aplan: AnalysisPlan


# --- request checks ---------------------------------------------------------------------


def _connection(  # noqa: PLR0911
    request: Request, state: CheckState, body: AnalyzeBody
) -> tuple[Plan, str | None] | Response:
    """Provider selection, the pass header and free-mode availability."""
    try:
        preset = PresetId(body.provider)
    except ValueError:
        return error_response("invalid_provider", 422)
    if body.turnstile_token is not None:
        return error_response("invalid_request", 422)
    named = body
    if preset is not PresetId.FREE and body.model is None and preset in MODEL_PAIRS:
        named = body.model_copy(update={"model": MODEL_PAIRS[preset].strong})
    plan = plan_connection(named, provider_key_header(request), state.settings)
    if isinstance(plan, Response):
        return plan
    values = request.headers.getlist(ANALYSIS_PASS_HEADER)
    if preset is not PresetId.FREE:
        return error_response("unexpected_analysis_pass", 422) if values else (plan, None)
    if not state.free_available:
        return error_response("free_mode_unavailable", 503)
    if len(values) != 1:
        return error_response("analysis_pass_invalid", 403)
    return plan, values[0]


def _plan(request: Request, state: CheckState, body: AnalyzeBody) -> JobPlan | Response:
    try:
        return plan_job(
            body.document, body.topics, catalog_of(request), state.settings, body.domain, body.side
        )
    except JobRefusedError as refusal:
        code = refusal.code
        if code == "document_too_large_for_tagging":
            code = "document_too_large_for_analysis"
        return error_response(code, refusal.status)
    except TopicSelectionError as error:
        return error_response(error.code, _STATUS.get(error.code, 422))
    except (TopicDefinitionError, TopicTextError) as error:
        return topic_error(error)


def _analysis_request(body: AnalyzeBody, model: str) -> AnalysisRequest:
    tagging = body.tagging
    signed: dict[str, dict[str, str]] = {}
    for clause_id, entries in tagging.tags.items():
        pairs: dict[str, str] = {
            e.topic_id: e.source for e in entries if e.source in ("model", "check")
        }
        if pairs:
            signed[clause_id] = pairs
    return AnalysisRequest(
        domain=body.domain,
        side=body.side,
        language=OutputLanguage(body.language),
        model=model,
        flags=frozenset(DocFlag(f) for f in body.flags),
        annex_links=frozenset(body.annex_links),
        reasons=tuple(tagging.incomplete_reasons),
        signed_tags=signed,
        status={
            topic_id: SignedStatus(s.model_tags_dropped, s.not_analyzed)
            for topic_id, s in tagging.topics.items()
        },
        client_tags={c: tuple(t) for c, t in tagging.client_tags.items()},
    )


def _free_admission(
    state: CheckState, prepared_pass: str | None, hits: Hits, digest: str, aplan: AnalysisPlan
) -> Response | None:
    """The pass records this document and its caps fit the worst case (no counting)."""
    if prepared_pass is None:
        return None
    try:
        _, entry = state.analysis.lookup(prepared_pass, hits.day_key)
        nonce = state.analysis.check(prepared_pass, hits.day_key)
    except FreePassError as error:
        return error_response(error.code, 403)
    if digest not in entry.documents:
        return error_response("analysis_pass_document_mismatch", 403)
    if not state.analysis.fits(nonce, aplan.calls, aplan.neurons):
        return error_response("analysis_pass_exhausted", 403)
    return None


async def _extraction(  # noqa: PLR0911
    request: Request, state: CheckState, declared: int
) -> Prepared | Response:
    """Everything that runs under the extraction slots: body, validation, sandbox, recompute."""
    settings = state.settings
    raw = await read_limited(request, declared, settings, ANALYZE_MAX_BODY_BYTES)
    if isinstance(raw, Response):
        return raw
    try:
        body = AnalyzeBody.model_validate_json(raw)
    except ValidationError:
        return error_response("invalid_request", 422)
    selected = _connection(request, state, body)
    if isinstance(selected, Response):
        return selected
    plan, pass_value = selected
    job_plan = _plan(request, state, body)
    if isinstance(job_plan, Response):
        return job_plan
    key = client_key(request.scope, settings)
    hits = Hits(state.analysis_minute, state.analysis_day, key, daily_key(key))
    refused = count_hits(hits)
    if refused is not None:
        return refused
    if pass_value is not None:
        try:
            state.analysis.lookup(pass_value, hits.day_key)
        except FreePassError as error:
            return error_response(error.code, 403)
    try:
        job = await prepare_job(job_plan, body.document, settings, sandbox_limits(settings))
        areq = _analysis_request(body, plan.model)
        tagging = body.tagging
        verify_tagging(
            state.signer, job, areq, tagging.digest, tagging.tagging_version, tagging.signature
        )
        merged = recompute_tags(job, areq)
        facts = make_facts(job, areq)
        aplan = plan_analysis(job, areq, merged, facts, catalog_of(request), settings)
    except SafetyRunError as error:
        if error.code == KEYWORD_BUDGET_EXCEEDED:
            return error_response(KEYWORD_BUDGET_EXCEEDED, 422)
        return safety_error(error)
    except JobRefusedError as refusal:
        return error_response(refusal.code, refusal.status)
    denied = _free_admission(state, pass_value, hits, job.child.digest, aplan)
    if denied is not None:
        return denied
    return Prepared(plan, pass_value, hits, job, areq, facts, aplan)


@router.post(ANALYZE_PATH)
async def analyze(request: Request) -> Response:
    state = check_state(request)
    settings = state.settings
    checked = check_upload_headers(
        request,
        max_bytes=ANALYZE_MAX_BODY_BYTES,
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
    return _start(request, state, prepared)


# --- the stream -----------------------------------------------------------------------------------


class _Settlement:
    """Free mode: the worst case is reserved before the stream and settled once after it."""

    def __init__(self, state: CheckState, prepared: Prepared, nonce: str) -> None:
        self._state = state
        self._prepared = prepared
        self._nonce = nonce
        self._done = False

    def settle(self, calls: int | None = None, spent: int | None = None) -> None:
        if self._done:
            return
        self._done = True
        plan = self._prepared.aplan
        actual_calls = plan.calls if calls is None else calls
        actual_spent = plan.neurons if spent is None else spent
        self._state.quota.settle_analysis(plan.neurons, actual_spent)
        self._state.analysis.settle(
            self._nonce, (plan.calls, actual_calls), (plan.neurons, actual_spent)
        )


def _spent(provider: AIProvider, counting: CountingProvider, worst: int) -> int:
    """Reported Neurons when every call returned and reported usage; else the worst case."""
    if counting.calls == 0:
        return 0
    if counting.completed < counting.calls:
        return worst
    reported = reported_neurons(provider)
    return worst if reported is None else reported


def _reserve(state: CheckState, prepared: Prepared) -> _Settlement | Response:
    aplan, hits = prepared.aplan, prepared.hits
    pass_value = prepared.pass_value
    if pass_value is None:
        return _Settlement(state, prepared, "")
    decision = state.quota.reserve_analysis(hits.day_key, aplan.neurons, start=False)
    if not decision.allowed:
        if decision.reason != "ip":
            hits.refund()
        return limited("free_quota_exhausted", 429, decision.retry_after)
    try:
        nonce = state.analysis.check(pass_value, hits.day_key)
    except FreePassError as error:
        state.quota.settle_analysis(aplan.neurons, 0)
        return error_response(error.code, 403)
    state.analysis.reserve(
        nonce, aplan.calls, aplan.neurons, prepared.job.child.digest, prepared.job.plan.chars
    )
    return _Settlement(state, prepared, nonce)


def _provider(state: CheckState, prepared: Prepared) -> AIProvider | Response:
    plan = prepared.plan
    settings = state.settings
    try:
        if plan.preset is PresetId.FREE:
            token, account = settings.cf_ai_token, settings.cf_account_id
            if token is None or account is None:
                return error_response("free_mode_unavailable", 503)
            return make_provider(state, plan, token, free_account=account.get_secret_value())
        key: SecretStr | None = plan.key
        if key is None:  # cheap validation guarantees a key for every non-free preset
            return error_response("invalid_provider_key", 422)
        return make_provider(state, plan, key, free_account=None)
    except ConnectionConfigError as error:
        return error_response(error.code, 422)


def _start(request: Request, state: CheckState, prepared: Prepared) -> Response:
    """Take the AI slots, the provider and the reservation, then answer with the stream. Every
    refusal here is still a JSON reply."""
    stack = ExitStack()
    try:
        stack.enter_context(ai_slots(state, prepared.hits.day_key))
    except BusyError:
        prepared.hits.refund()
        return busy()
    inner = _provider(state, prepared)
    if isinstance(inner, Response):
        stack.close()
        return inner
    reserved = _reserve(state, prepared)
    if isinstance(reserved, Response):
        stack.close()
        return reserved
    settings = state.settings
    counting = CountingProvider(inner, settings.analysis_call_deadline_seconds)
    free = prepared.plan.preset is PresetId.FREE
    catalog = catalog_of(request)
    started = time.monotonic()

    async def produce(emit: Emit) -> None:
        worst = prepared.aplan.neurons
        finished = False
        try:
            await stream_analysis(
                prepared.job.document,
                prepared.job.child.digest,
                prepared.aplan,
                prepared.request,
                prepared.facts,
                counting,
                catalog,
                settings.analysis_deadline_seconds,
                REASONING_EFFORT[prepared.plan.preset],
                state.result_signer,
                emit,
            )
            finished = True
        finally:
            if free:
                if finished:
                    reserved.settle(counting.calls, _spent(inner, counting, worst))
                else:  # cancelled or failed: the worst case stays charged
                    reserved.settle()
            logger.info(
                "analyze topics=%d calls=%d finished=%d duration_ms=%d",
                len(prepared.aplan.topics),
                counting.calls,
                int(finished),
                (time.monotonic() - started) * 1000,
            )

    def close() -> None:
        try:
            if free:
                reserved.settle()  # a no-op after the producer settled
        finally:
            stack.close()

    return SseResponse(
        produce,
        heartbeat=settings.analysis_heartbeat_seconds,
        send_timeout=settings.analysis_send_timeout_seconds,
        on_close=close,
    )
