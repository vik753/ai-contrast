# ruff: noqa: PLC0415, S105
"""Helpers of the S8-T2 tests (see README.md). No network: provider and Turnstile are fakes."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx2

from app.main import create_app
from app.pseudo.lexicon import DETECTOR_VERSION
from app.settings import Settings
from tests.ai.helpers import FakeUpstream, Seen
from tests.asgi_stream import chunks, drive, post_scope
from tests.check.helpers import DEFAULT_TOKEN, FREE_ENV, KEY_HEADER, PUBLIC_IP, Rig
from tests.topics.helpers import CATALOG_OK

TAG = "/api/tag"
MODEL = {"provider": "openai", "model": "gpt-cheap-1", "check_model": "gpt-strong-1"}
FIXTURES = Path(__file__).resolve().parents[2] / "eval" / "tagging" / "fixtures"
PASS_HEADER = "X-Analysis-Pass"
TagFn = Callable[[list[str], int], Any]
CheckFn = Callable[[list[tuple[str, str]]], Any]


def tag_out(tags: Mapping[str, Sequence[tuple[str, str]]]) -> str:
    return json.dumps(
        {
            "tags": [
                {"clause": cid, "topics": [{"index": i, "confidence": c} for i, c in items]}
                for cid, items in tags.items()
            ]
        }
    )


def check_out(answers: Mapping[tuple[str, str], bool]) -> str:
    return json.dumps(
        {"answers": [{"clause": c, "topic": t, "regulates": v} for (c, t), v in answers.items()]}
    )


def _completion(text: str, prompt: int = 20, completion: int = 10) -> httpx2.Response:
    body = {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "created": 1,
        "model": "test-model-1",
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}
        ],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
        },
    }
    return httpx2.Response(200, json=body)


class TagUpstream(FakeUpstream):
    """Answers TAG_CLAUSES and CHECK_TAGS calls. ``tag``/``check`` build the model text.

    A function may return a ``str`` (sent as is), a ``dict`` (tags / answers), or an
    ``int`` (an HTTP error status). Default: no tags, every asked pair answered ``yes``.
    """

    def __init__(self, tag: TagFn | None = None, check: CheckFn | None = None) -> None:
        self.tag_fn: TagFn = tag or (lambda ids, n: {})
        self.check_fn: CheckFn = check or (lambda pairs: dict.fromkeys(pairs, True))
        self.calls: list[tuple[str, str, list[str], list[tuple[str, str]], str]] = []
        super().__init__(self._answer)

    @staticmethod
    def text_of(seen: Seen) -> str:
        data = json.loads(seen.body)
        return "\n".join(str(m.get("content")) for m in data["messages"])

    def _answer(self, request: httpx2.Request) -> httpx2.Response:
        from app.ai.prompts import PromptTemplate

        data = json.loads(request.content)
        msgs = data["messages"]
        full = "\n".join(str(m["content"]) for m in msgs)
        users = "\n".join(str(m["content"]) for m in msgs if m["role"] != "system")
        model = str(data.get("model"))
        if PromptTemplate.CHECK_TAGS.value in full:
            pairs = re.findall(r"^(c\d+) (T\d+)$", full, re.M)
            self.calls.append(("check", model, [], pairs, full))
            result = self.check_fn(pairs)
            if isinstance(result, dict):
                return _completion(check_out(result))
        else:
            ids = list(dict.fromkeys(re.findall(r"\bc\d+\b", users)))
            n_topics = len(set(re.findall(r"^T(\d+):", full, re.M)))
            self.calls.append(("tag", model, ids, [], full))
            result = self.tag_fn(ids, n_topics)
            if isinstance(result, dict):
                return _completion(tag_out(result))
        if isinstance(result, int):
            return httpx2.Response(result, json={"error": {"message": "x"}})
        return _completion(str(result))

    def of(self, kind: str) -> list[tuple[str, str, list[str], list[tuple[str, str]], str]]:
        return [c for c in self.calls if c[0] == kind]


def custom(n: int = 1, title: str = "", syn: Sequence[str] = (), desc: str = "") -> dict[str, Any]:
    return {
        "origin": "custom",
        "domain": "kasko",
        "topic_id": f"custom_{n}",
        "title": title or ("Deductible handling", "Roadside assistance", "Glass repair")[n - 1],
        "description": desc or "Rules of the subject",
        "side": "insured",
        "synonyms_en": list(syn),
    }


def two_topics() -> dict[str, Any]:
    return {"custom": [custom(1, syn=["deductible"]), custom(2, syn=["towing"])]}


def document(*texts: str, label: str = "A") -> dict[str, Any]:
    return {
        "label": label,
        "detector_version": DETECTOR_VERSION,
        "clauses": [{"id": f"c{i}", "text": t} for i, t in enumerate(texts, 1)],
        "acknowledged_unmasked": [],
    }


DEFAULT_TEXTS = (
    "The deductible is paid by the insured for every loss.",
    "Towing to the nearest garage is included.",
    "Notices are sent in writing.",
)


def tag_body(
    *texts: str, topics: dict[str, Any] | None = None, label: str = "A", **over: Any
) -> dict[str, Any]:
    return {
        **MODEL,
        "domain": "kasko",
        "side": "insured",
        "document": document(*(texts or DEFAULT_TEXTS), label=label),
        "topics": topics or two_topics(),
        **over,
    }


def big_doc(chars: int, seed: str, per_clause: int = 1000) -> tuple[str, ...]:
    out: list[str] = []
    n = 0
    while sum(map(len, out)) < chars:
        n += 1
        word = f"{seed}{n % 7} "
        out.append((word * (per_clause // len(word) + 1))[:per_clause])
    return tuple(out)


class TagRig(Rig):
    """A ``Rig`` whose app uses the fixture catalog and a ``TagUpstream``."""

    def __init__(
        self,
        tag: TagFn | None = None,
        check: CheckFn | None = None,
        *,
        upstream: Any = None,
        **settings: Any,
    ) -> None:
        settings.setdefault("topics_catalog_dir", CATALOG_OK)
        settings.setdefault("tag_per_minute", 1000)
        settings.setdefault("tag_per_day", 10000)
        self.tags = upstream or TagUpstream(tag, check)
        super().__init__(provider_transport=self.tags, **settings)

    def post(
        self,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        ip: str = PUBLIC_IP,
        path: str = TAG,
    ) -> httpx2.Response:
        use = KEY_HEADER if headers is None else headers
        return self.client(ip).post(path, json=body, headers=use)  # type: ignore[return-value]

    def tag(self, *texts: str, **kw: Any) -> httpx2.Response:
        return self.post(tag_body(*texts), **kw)

    def free_tag(
        self,
        body: dict[str, Any] | None = None,
        *,
        token: str | None = DEFAULT_TOKEN,
        pass_: str | None = None,
        ip: str = PUBLIC_IP,
    ) -> httpx2.Response:
        base = body or tag_body()
        base = {k: v for k, v in base.items() if k not in MODEL}
        headers: dict[str, str] = {}
        if pass_ is not None:
            headers[PASS_HEADER] = pass_
        elif token is not None:
            base["turnstile_token"] = token
        return self.post({"provider": "free", **base}, headers=headers, ip=ip)

    def catalog_version(self) -> str:
        return str(self.client().get("/api/topics/catalog").json()["catalog_version"])


def free_tag_rig(tag: TagFn | None = None, check: CheckFn | None = None, **settings: Any) -> TagRig:
    return TagRig(tag, check, **{**FREE_ENV, "free_neuron_budget": 9999, **settings})


def error_of(response: Any) -> str:
    return str(json.loads(response.content)["error"])


def issue(rig: TagRig, token: str = "tok-1", ip: str = PUBLIC_IP) -> str:  # noqa: S107
    response = rig.free_tag(token=token, ip=ip)
    assert response.status_code == 200, response.text
    return str(response.json()["analysis_pass"])


def by_topic(reply: dict[str, Any], clause: str) -> dict[str, str]:
    return {t["topic_id"]: t["source"] for t in reply["tags"][clause]}


def load_fixture_clauses(name: str) -> tuple[list[str], dict[str, str]]:
    """Clause texts of an adversarial fixture (one clause per block, title skipped)
    and a map clause number -> clause id."""
    data = json.loads((FIXTURES / f"{name}.contract.json").read_text(encoding="utf-8"))
    texts: list[str] = []
    numbers: dict[str, str] = {}
    for block in data["blocks"]:
        match = re.match(r"^(\d+(?:\.\d+)*)\.?\s", block["text"])
        if not match:
            continue
        texts.append(block["text"])
        numbers[match.group(1)] = f"c{len(texts)}"
    return texts, numbers


def gated_tag_rig(gate: httpx2.AsyncBaseTransport, **settings: Any) -> TagRig:
    rig = TagRig()
    rig.app = create_app(
        Settings(
            environment="development",
            topics_catalog_dir=CATALOG_OK,
            tag_per_minute=1000,
            tag_per_day=10000,
            **settings,
        ),
        provider_transport=gate,
        turnstile_transport=rig.turnstile,
        clock=rig.clock,
    )
    return rig


def scope(path: str, body: bytes, ip: str, headers: dict[str, str]) -> dict[str, Any]:
    s = post_scope(
        path,
        content_type="application/json",
        content_length=len(body),
        extra_headers=list(headers.items()),
    )
    s["client"] = (ip, 50000)
    return s


async def post_async(
    rig: TagRig, body: dict[str, Any], ip: str, headers: dict[str, str] | None = None
) -> Any:
    raw = json.dumps(body).encode()
    use = KEY_HEADER if headers is None else headers
    return await drive(rig.app, scope(TAG, raw, ip, use), chunks(raw))


async def wait_started(gate: Any, n: int) -> None:
    for _ in range(500):
        if gate.started >= n:
            return
        await asyncio.sleep(0.01)
    assert gate.started >= n
