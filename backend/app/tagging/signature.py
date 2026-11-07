"""The tag signature (ADR 0018 point 8, ADR 0019 point 1): HMAC-SHA256 over the digest, the
tagging version, the model and check tags and a binding, with a per-process key (one
``TagSigner`` per app, kept in ``app.state.tag_signer``).

Version 2 (stage 9). The binding covers the incomplete reasons, per topic the definition hash,
``model_tags_dropped`` and ``not_analyzed``, the topic order, the domain and the side.
``/api/tag`` returns the signature; ``/api/analyze`` refuses model or check tags, topic status
or a topic set that do not carry a matching signature. The key is ``secrets.token_bytes(32)``,
lives in process memory only and is never logged: a restart invalidates every signature.
Keyword and client tags are not signed (stage 9 recomputes keyword tags and accepts client tags
as add-only). Nothing here logs.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from fastapi import FastAPI

from app.pseudo.gate import ConfirmedTopic

__all__ = [
    "SignedTopic",
    "TagSigner",
    "tag_binding",
    "tag_signer",
    "topic_fingerprint",
    "verify_tag_signature",
]

VERSION: Final = "v2"
SIGNED_SOURCES: Final = frozenset({"model", "check"})


@dataclass(frozen=True, slots=True)
class SignedTopic:
    """One resolved topic with the status that tagging signed for it."""

    topic_id: str
    fingerprint: str
    model_tags_dropped: bool
    not_analyzed: str | None


def _lp(text: str) -> bytes:
    data = text.encode("utf-8")
    return len(data).to_bytes(4, "big") + data


def topic_fingerprint(topic: ConfirmedTopic) -> str:
    """A hash of everything that defines a confirmed topic (a changed definition changes it)."""
    canonical = json.dumps(
        [
            topic.domain,
            topic.topic_id,
            topic.title,
            topic.description,
            topic.side,
            [
                [
                    a.id,
                    a.label,
                    a.type,
                    list(a.units),
                    a.direction,
                    list(a.order),
                    list(a.values),
                    list(a.value_ids),
                    a.direction_source,
                ]
                for a in topic.attributes
            ],
            list(topic.synonyms_en),
            list(topic.synonyms_uk),
            list(topic.synonyms_ru),
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def tag_binding(
    *, reasons: Iterable[str], topics: Sequence[SignedTopic], domain: str, side: str
) -> str:
    """The part of the signature that is not a tag: reasons, topic set and status, domain, side."""
    digest = hashlib.sha256()
    for part in (
        "reasons",
        *sorted(set(reasons)),
        "domain",
        domain,
        "side",
        side,
        "topics",
        *(
            "\x1f".join(
                (t.topic_id, t.fingerprint, str(int(t.model_tags_dropped)), t.not_analyzed or "")
            )
            for t in topics
        ),
    ):
        digest.update(_lp(part))
    return digest.hexdigest()


class TagSigner:
    def __init__(self) -> None:
        self._key = secrets.token_bytes(32)

    @staticmethod
    def _tags_hash(tags: Mapping[str, Mapping[str, str]]) -> str:
        pairs = sorted(
            (clause, topic, source)
            for clause, by_topic in tags.items()
            for topic, source in by_topic.items()
            if source in SIGNED_SOURCES
        )
        digest = hashlib.sha256()
        for pair in pairs:
            for part in pair:
                digest.update(_lp(part))
        return digest.hexdigest()

    def sign(
        self,
        *,
        digest: str,
        tagging_version: str,
        tags: Mapping[str, Mapping[str, str]],
        binding: str,
    ) -> str:
        parts = (VERSION, digest, tagging_version, self._tags_hash(tags), binding)
        message = b"".join(_lp(p) for p in parts)
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()

    def verify(
        self,
        signature: str,
        *,
        digest: str,
        tagging_version: str,
        tags: Mapping[str, Mapping[str, str]],
        binding: str,
    ) -> bool:
        expected = self.sign(
            digest=digest, tagging_version=tagging_version, tags=tags, binding=binding
        )
        return hmac.compare_digest(expected.encode(), signature.encode("utf-8", "replace"))


def tag_signer(app: FastAPI) -> TagSigner:
    signer = getattr(app.state, "tag_signer", None)
    if not isinstance(signer, TagSigner):
        msg = "app state is not configured"
        raise TypeError(msg)
    return signer


def verify_tag_signature(  # noqa: PLR0913
    app: FastAPI,
    signature: str,
    *,
    digest: str,
    tagging_version: str,
    tags: Mapping[str, Mapping[str, str]],
    binding: str,
) -> bool:
    """Is ``signature`` the one this process gave for exactly these model and check tags and
    this binding (``tag_binding``)?"""
    return tag_signer(app).verify(
        signature, digest=digest, tagging_version=tagging_version, tags=tags, binding=binding
    )
