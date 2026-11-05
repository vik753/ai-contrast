"""The tag signature (ADR 0018 point 8): HMAC-SHA256 over the digest, the tagging version and
the model and check tags, with a per-process key (one ``TagSigner`` per app, kept in
``app.state.tag_signer``).

``/api/tag`` returns it; stage 9 refuses model or check tags that do not carry a matching
signature. The key is ``secrets.token_bytes(32)``, lives in process memory only and is never
logged: a restart invalidates every signature. Keyword and client tags are not signed (stage
9 recomputes keyword tags and accepts client tags as add-only). Nothing here logs.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Mapping
from typing import Final

from fastapi import FastAPI

__all__ = ["TagSigner", "tag_signer", "verify_tag_signature"]

VERSION: Final = "v1"
SIGNED_SOURCES: Final = frozenset({"model", "check"})


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
                data = part.encode("utf-8")
                digest.update(len(data).to_bytes(4, "big"))
                digest.update(data)
        return digest.hexdigest()

    def sign(
        self, *, digest: str, tagging_version: str, tags: Mapping[str, Mapping[str, str]]
    ) -> str:
        parts = (VERSION, digest, tagging_version, self._tags_hash(tags))
        message = b"".join(len(p.encode()).to_bytes(4, "big") + p.encode() for p in parts)
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()

    def verify(
        self,
        signature: str,
        *,
        digest: str,
        tagging_version: str,
        tags: Mapping[str, Mapping[str, str]],
    ) -> bool:
        expected = self.sign(digest=digest, tagging_version=tagging_version, tags=tags)
        return hmac.compare_digest(expected.encode(), signature.encode("utf-8", "replace"))


def tag_signer(app: FastAPI) -> TagSigner:
    signer = getattr(app.state, "tag_signer", None)
    if not isinstance(signer, TagSigner):
        msg = "app state is not configured"
        raise TypeError(msg)
    return signer


def verify_tag_signature(
    app: FastAPI,
    signature: str,
    *,
    digest: str,
    tagging_version: str,
    tags: Mapping[str, Mapping[str, str]],
) -> bool:
    """Is ``signature`` the one this process gave for exactly these model and check tags?"""
    return tag_signer(app).verify(
        signature, digest=digest, tagging_version=tagging_version, tags=tags
    )
