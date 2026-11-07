# ruff: noqa: E501, PLC0415, PLW0108
"""Helpers of the S9-T3 tests (see README.md). No network: provider and Turnstile are fakes."""

from __future__ import annotations

import asyncio
import copy
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx2

from tests.check.helpers import FREE_ENV, KEY_HEADER, PUBLIC_IP
from tests.tag_api.helpers import (
    PASS_HEADER,
    TagFn,
    TagRig,
    TagUpstream,
    custom,
    tag_body,
)
from tests.tag_api.helpers import issue as _issue

ANALYZE = "/api/analyze"
TITLES = {
    "Towing aid": "custom_1",
    "Glass aid": "custom_2",
    "Theft cover": "theft_cover",
    "Deductible": "deductible",
}
DEFAULT_TEXTS = (
    "The deductible for each insured event is 5000 UAH.",
    "Towing to the nearest garage is included in the cover without any limit.",
    "Notices are sent in writing to the address of the other party.",
    "A penalty of five percent applies for every day of late payment.",
)
QUOTE1 = "The deductible for each insured event is 5000 UAH"
RateTopicFn = Callable[[str, list[str]], Any]
RateOtherFn = Callable[[list[str]], Any]


def rev(clause: str, quote: str) -> dict[str, str]:
    return {"clause": clause, "quote": quote}


def rfind(
    rating: str = "yellow",
    *,
    attribute: str | None = None,
    explanation: str = "Reason of the rating.",
    evidence: Sequence[dict[str, str]] = (),
) -> dict[str, Any]:
    return {
        "rating": rating,
        "attribute": attribute,
        "explanation": explanation,
        "evidence": list(evidence) or [rev("c1", QUOTE1)],
    }


def amount(number: float = 5000, evidence: Sequence[dict[str, str]] = ()) -> dict[str, Any]:
    return {
        "attribute": "deductible_amount",
        "value": {"type": "amount", "number": number, "currency": "UAH"},
        "evidence": list(evidence) or [rev("c1", "is 5000 UAH")],
    }


def topic_out(
    findings: Sequence[dict[str, Any]] = (),
    attributes: Sequence[dict[str, Any]] = (),
    injection: Sequence[dict[str, str]] = (),
) -> dict[str, Any]:
    return {
        "attributes": list(attributes),
        "findings": list(findings),
        "injection_suspected": list(injection),
    }


def other_out(
    ids: Sequence[str], findings: dict[str, list[dict[str, Any]]] | None = None
) -> dict[str, Any]:
    found = findings or {}
    return {
        "clauses": [
            {"clause": i, "no_issue": not found.get(i), "findings": found.get(i, [])} for i in ids
        ]
    }


@dataclass
class RateCall:
    kind: str  # "topic" | "other"
    model: str
    topic: str | None
    ids: list[str]
    full: str


class AnalyzeUpstream(TagUpstream):
    """TagUpstream that also answers RATE_TOPIC and RATE_OTHER.

    ``topic_fn(topic_id, clause_ids)`` and ``other_fn(clause_ids)`` return a dict (the answer),
    a str (sent as is) or an int (HTTP error). Default: topics give no findings, Other is all no_issue.
    ``hang`` makes every rating call wait until cancelled (``hung`` counts them, ``cancelled`` the cancelled).
    ``delay`` makes every rating call slow.
    """

    def __init__(self, tag: TagFn | None = None, check: Any = None) -> None:
        self.topic_fn: RateTopicFn = lambda t, ids: topic_out()
        self.other_fn: RateOtherFn = lambda ids: other_out(ids)
        self.rates: list[RateCall] = []
        self.hang = False
        self.delay = 0.0
        self.hung = 0
        self.cancelled = 0
        super().__init__(tag, check)

    @staticmethod
    def _kind(request: httpx2.Request) -> str | None:
        from app.ai.prompts import PromptTemplate
        from tests.tag_api.helpers import _flat

        data = json.loads(request.content)
        text = "\n".join(
            [_flat(data.get("system", "")), *(_flat(m["content"]) for m in data["messages"])]
        )
        for kind, template in (
            ("topic", PromptTemplate.RATE_TOPIC),
            ("other", PromptTemplate.RATE_OTHER),
        ):
            if template.value in text:
                return kind
        return None

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        await request.aread()
        if self._kind(request):
            if self.hang:
                self.hung += 1
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.cancelled += 1
                    raise
            if self.delay:
                await asyncio.sleep(self.delay)
        return await super().handle_async_request(request)

    def _answer(self, request: httpx2.Request) -> httpx2.Response:
        from tests.tag_api.helpers import _completion, _flat

        kind = self._kind(request)
        if kind is None:
            return super()._answer(request)
        data = json.loads(request.content)
        msgs = data["messages"]
        anthropic = request.url.path.endswith("/messages")
        system = _flat(data.get("system", "")) if anthropic else ""
        system += "\n".join(_flat(m["content"]) for m in msgs if m["role"] == "system")
        users = "\n".join(_flat(m["content"]) for m in msgs if m["role"] != "system")
        ids = list(dict.fromkeys(re.findall(r"\bc\d+\b", users)))
        topic = None
        if kind == "topic":
            topic = next(
                (t for k, t in sorted(TITLES.items(), key=lambda kv: -len(kv[0])) if k in system),
                None,
            )
        self.rates.append(RateCall(kind, str(data.get("model")), topic, ids, system + "\n" + users))
        result = self.topic_fn(topic or "", ids) if kind == "topic" else self.other_fn(ids)
        if isinstance(result, int):
            return httpx2.Response(result, json={"error": {"message": "x"}})
        text = json.dumps(result) if isinstance(result, dict) else str(result)
        return _completion(text, anthropic=anthropic)

    def of(self, kind: str) -> list[Any]:  # type: ignore[override]
        if kind in ("topic", "other"):
            return [r for r in self.rates if r.kind == kind]
        return super().of(kind)

    def topic_calls(self, topic_id: str) -> list[RateCall]:
        return [r for r in self.rates if r.kind == "topic" and r.topic == topic_id]


@dataclass
class Reply:
    status: int
    headers: dict[str, str]
    raw: str
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)

    @property
    def is_stream(self) -> bool:
        return self.headers.get("content-type", "").startswith("text/event-stream")

    @property
    def error(self) -> str:
        return str(json.loads(self.raw)["error"])

    def of(self, name: str) -> list[dict[str, Any]]:
        return [d for n, d in self.events if n == name]

    @property
    def done(self) -> dict[str, Any]:
        done = self.of("done")
        assert done, self.raw[:2000]
        return done[0]

    def topic(self, topic_id: str) -> dict[str, Any]:
        return next(t for t in self.of("topic") if t["topic_id"] == topic_id)

    def findings(self, topic_id: str) -> list[dict[str, Any]]:
        return list(self.topic(topic_id)["findings"])

    def other_findings(self) -> list[dict[str, Any]]:
        return [f for o in self.of("other") for f in o["findings"]]

    def ratings(self) -> list[str]:
        out = [f["rating"] for t in self.of("topic") for f in t["findings"]]
        return out + [f["rating"] for f in self.other_findings()]


def parse_sse(status: int, headers: dict[str, str], raw: str) -> Reply:
    reply = Reply(status, {k.lower(): v for k, v in headers.items()}, raw)
    if not reply.is_stream:
        return reply
    for block in raw.replace("\r\n", "\n").split("\n\n"):
        lines = [x for x in block.split("\n") if x]
        if not lines:
            continue
        if all(x.startswith(":") for x in lines):
            reply.comments.append(block)
            continue
        name = next(x[7:].strip() for x in lines if x.startswith("event:"))
        data = "".join(x[5:].lstrip() for x in lines if x.startswith("data:"))
        reply.events.append((name, json.loads(data)))
    return reply


def sse_blocks(raw: str) -> list[str]:
    return [
        b for b in raw.replace("\r\n", "\n").split("\n\n") if b.strip() and not b.startswith(":")
    ]


def ref(topic_id: str, rig: TagRig, side: str = "insured", domain: str = "kasko") -> dict[str, str]:
    return {
        "domain": domain,
        "topic_id": topic_id,
        "side": side,
        "lang": "en",
        "catalog_version": rig.catalog_version(),
    }


def topics_for(rig: TagRig, *catalog: str, n_custom: int = 1) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if catalog:
        out["catalog"] = [ref(t, rig) for t in catalog]
    if n_custom:
        out["custom"] = [
            custom(1, title="Towing aid", syn=["towing"]),
            custom(2, title="Glass aid", syn=["windscreen"]),
        ][:n_custom]
    return out


class AnalyzeRig(TagRig):
    def __init__(
        self,
        tag: TagFn | None = None,
        *,
        upstream: AnalyzeUpstream | None = None,
        **settings: Any,
    ) -> None:
        settings.setdefault("analysis_per_minute", 1000)
        settings.setdefault("analysis_per_day", 10000)
        # No wall-clock deadline can fire by accident on a slow machine; deadline tests set their own.
        settings.setdefault("analysis_deadline_seconds", 3600.0)
        settings.setdefault("analysis_call_deadline_seconds", 600.0)
        settings.setdefault("tag_deadline_seconds", 3600.0)
        settings.setdefault("tag_call_deadline_seconds", 600.0)
        self.up = upstream or AnalyzeUpstream(tag)
        super().__init__(upstream=self.up, **settings)

    # -- building requests

    def base(
        self, *texts: str, topics: dict[str, Any] | None = None, **over: Any
    ) -> dict[str, Any]:
        topics = topics if topics is not None else topics_for(self, "deductible", n_custom=0)
        return tag_body(*(texts or DEFAULT_TEXTS), topics=topics, **over)

    def tagged(self, tb: dict[str, Any], **kw: Any) -> dict[str, Any]:
        r = self.post(tb, **kw)
        assert r.status_code == 200, r.text
        return r.json()  # type: ignore[no-any-return]

    def body(self, tb: dict[str, Any], reply: dict[str, Any], **over: Any) -> dict[str, Any]:
        body = {k: v for k, v in tb.items() if k not in ("check_model", "turnstile_token")}
        body["language"] = "en"
        body["tagging"] = {
            "digest": reply["digest"],
            "tagging_version": reply["tagging_version"],
            "signature": reply["signature"],
            "tags": copy.deepcopy(reply["tags"]),
            "incomplete_reasons": list(reply["incomplete_reasons"]),
            "topics": copy.deepcopy(reply["topics"]),
            "client_tags": {},
        }
        body.update(over)
        return body

    def ready(
        self, *texts: str, topics: dict[str, Any] | None = None, **over: Any
    ) -> dict[str, Any]:
        """Tag a document (the tag step) and build the matching analyze body."""
        tb = self.base(*texts, topics=topics)
        return self.body(tb, self.tagged(tb), **over)

    # -- calling

    def analyze(
        self,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        ip: str = PUBLIC_IP,
    ) -> Reply:
        use = {**KEY_HEADER, "Accept-Encoding": "gzip"} if headers is None else headers
        r = self.client(ip).post(ANALYZE, json=body, headers=use)
        return parse_sse(r.status_code, dict(r.headers), r.text)

    def run(self, *texts: str, topics: dict[str, Any] | None = None, **over: Any) -> Reply:
        return self.analyze(self.ready(*texts, topics=topics, **over))


def free_analyze_rig(tag: TagFn | None = None, **settings: Any) -> AnalyzeRig:
    return AnalyzeRig(tag, **{**FREE_ENV, "free_neuron_budget": 9999, **settings})


FREE_STRIP = ("provider", "model", "check_model", "turnstile_token")


def free_ready(
    rig: AnalyzeRig, pass_: str | None = None, tb: dict[str, Any] | None = None
) -> tuple[dict[str, Any], str]:
    """Tag a document in free mode; return the free analyze body and the analysis pass."""
    tb = tb or rig.base()
    r = rig.free_tag(tb, pass_=pass_) if pass_ else rig.free_tag(tb)
    assert r.status_code == 200, r.text
    reply = r.json()
    token = pass_ or reply["analysis_pass"]
    body = rig.body({k: v for k, v in tb.items() if k not in FREE_STRIP}, reply)
    body["provider"] = "free"
    return body, str(token)


def free_analyze(
    rig: AnalyzeRig, body: dict[str, Any], pass_: str | None, ip: str = PUBLIC_IP
) -> Reply:
    headers = {PASS_HEADER: pass_} if pass_ else {}
    return rig.analyze(body, headers=headers, ip=ip)


def issue(rig: AnalyzeRig, ip: str = PUBLIC_IP) -> str:
    return _issue(rig, ip=ip)


def span_ok(span: list[Any], clause: str, inside: tuple[int, int]) -> bool:
    """The evidence span names ``clause`` and covers the offsets ``inside``."""
    return span[0] == clause and span[1] <= inside[0] and span[2] >= inside[1]


def at(text: str, part: str) -> tuple[int, int]:
    i = text.index(part)
    return i, i + len(part)
