"""Helpers of the S7-T2 tests (see README.md). No network: provider and Turnstile are fakes."""

from __future__ import annotations

import json
import secrets
import string
from typing import Any

import httpx2

from app.main import create_app
from app.pseudo.lexicon import DETECTOR_VERSION
from app.settings import Settings
from tests.ai.helpers import FakeUpstream, Reply, model_reply
from tests.check.helpers import DEFAULT_TOKEN, FREE_ENV, KEY_HEADER, PUBLIC_IP, Rig
from tests.topics.helpers import CATALOG_OK

SUGGEST = "/api/topics/suggest"
PROPOSE = "/api/topics/propose-attributes"
EXPAND = "/api/topics/expand-synonyms"
PATHS = {"suggest": SUGGEST, "propose": PROPOSE, "expand": EXPAND}
MODEL = {"provider": "openai", "model": "gpt-test-1"}
CLAUSES = (
    "1. The Insurer pays the claim within thirty days after the documents are received.",
    "2. The Insured bears a deductible for every loss under this agreement.",
)


def canary(prefix: str = "Canary") -> str:
    """A letters-only word that passes the topic grammar and is unique per call."""
    return prefix + "".join(secrets.choice(string.ascii_lowercase) for _ in range(14))


class SeqUpstream(FakeUpstream):
    """Answers with the given model texts in order; the last text repeats."""

    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        super().__init__(self._next)

    def _next(self, request: httpx2.Request) -> httpx2.Response:
        text = self.texts.pop(0) if len(self.texts) > 1 else self.texts[0]
        reply: Reply = model_reply(text)
        return reply(request)

    def bodies(self) -> list[str]:
        return [s.body.decode("utf-8", "replace") for s in self.seen]


def suggest_out(*items: tuple[str, str]) -> str:
    return json.dumps({"topics": [{"name": n, "description": d} for n, d in items]})


def attr_out(*attrs: dict[str, Any]) -> str:
    return json.dumps({"attributes": list(attrs)})


def attr(attr_id: str = "towing_limit", label: str = "Towing limit", **more: Any) -> dict[str, Any]:
    return {"id": attr_id, "label": label, "type": "amount", "units": ["UAH"], **more}


def syn_out(
    en: list[str] | None = None, uk: list[str] | None = None, ru: list[str] | None = None
) -> str:
    return json.dumps({"synonyms_en": en or [], "synonyms_uk": uk or [], "synonyms_ru": ru or []})


def document(*texts: str, label: str = "A") -> dict[str, Any]:
    return {
        "label": label,
        "detector_version": DETECTOR_VERSION,
        "clauses": [{"id": f"c{i}", "text": t} for i, t in enumerate(texts or CLAUSES, 1)],
        "acknowledged_unmasked": [],
    }


def topic(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "origin": "custom",
        "domain": "kasko",
        "topic_id": "custom_1",
        "title": "Roadside assistance",
        "description": "Towing and help on the road",
        "side": "insured",
    }
    return {**base, **changes}


def suggest_body(*texts: str, label: str = "A", **over: Any) -> dict[str, Any]:
    return {
        **MODEL,
        "domain": "kasko",
        "side": "insured",
        "document": document(*texts, label=label),
        **over,
    }


def topic_body(**topic_changes: Any) -> dict[str, Any]:
    return {**MODEL, "topic": topic(**topic_changes)}


class TRig(Rig):
    """A ``Rig`` whose app uses the fixture catalog."""

    def __init__(self, *texts: str, **settings: Any) -> None:
        settings.setdefault("topics_catalog_dir", CATALOG_OK)
        upstream = SeqUpstream(*(texts or (attr_out(attr()),)))
        super().__init__(provider_transport=upstream, **settings)

    def post(
        self,
        path: str,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        ip: str = PUBLIC_IP,
    ) -> httpx2.Response:
        use = KEY_HEADER if headers is None else headers
        return self.client(ip).post(path, json=body, headers=use)  # type: ignore[return-value]

    def suggest(self, *texts: str, **kw: Any) -> httpx2.Response:
        return self.post(SUGGEST, suggest_body(*texts), **kw)

    def propose(self, **kw: Any) -> httpx2.Response:
        return self.post(PROPOSE, topic_body(), **kw)

    def expand(self, **kw: Any) -> httpx2.Response:
        return self.post(EXPAND, topic_body(), **kw)

    def free_call(
        self,
        kind: str = "propose",
        *,
        token: str | None = DEFAULT_TOKEN,
        pass_: str | None = None,
        ip: str = PUBLIC_IP,
    ) -> httpx2.Response:
        body = suggest_body() if kind == "suggest" else topic_body()
        body = {"provider": "free", **{k: v for k, v in body.items() if k not in MODEL}}
        headers: dict[str, str] = {}
        if pass_ is not None:
            headers["X-Free-Pass"] = pass_
        elif token is not None:
            body["turnstile_token"] = token
        return self.post(PATHS[kind], body, headers=headers, ip=ip)

    @property
    def wire(self) -> list[str]:
        return [s.body.decode("utf-8", "replace") for s in self.upstream.seen]


def free_trig(*texts: str, **settings: Any) -> TRig:
    base = {"topics_per_minute": 100, "topics_per_day": 1000}
    return TRig(*texts, **{**FREE_ENV, **base, **settings})


def error_of(response: Any) -> str:
    return str(json.loads(response.content)["error"])


def gated_rig(gate: httpx2.AsyncBaseTransport, **settings: Any) -> TRig:
    """A rig whose provider transport is ``gate`` (the test decides when it answers)."""
    rig = TRig()
    rig.app = create_app(
        Settings(environment="development", topics_catalog_dir=CATALOG_OK, **settings),
        provider_transport=gate,
        turnstile_transport=rig.turnstile,
        clock=rig.clock,
    )
    return rig
