"""S6-T2 review finding (HIGH): decompression bomb. ADR 0016 point 3 (response cap).

Every AI request sends ``Accept-Encoding: identity`` (whatever the SDK sets). A reply with a
``Content-Encoding`` other than identity is a ``provider_bad_response``. A body that is small
compressed and huge uncompressed is never decoded: the call stays far below the size of the
decoded body. Both paths: ``transport=`` (mock) and production (guarded client over a fake
network backend that sees the raw HTTP bytes).
"""

from __future__ import annotations

import gzip
import tracemalloc
import zlib
from collections.abc import AsyncIterator
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from app.ai.factory import provider_for
from app.ai.port import AIProvider
from app.ai.presets import PresetId
from app.net.guard import GuardedNetworkBackend
from tests.ai.helpers import KEY, MIB, FakeUpstream, failure, make_provider, model_reply, run
from tests.netfakes import PUBLIC_V4, FakeStream, ResolverSpy, SpyInner

PRESETS = [PresetId.ANTHROPIC, PresetId.OPENAI]
OPS = ["check", "complete_json"]
PATHS = ["transport", "production"]
ENCODINGS = [
    "gzip",
    "GZIP",
    "x-gzip",
    "deflate",
    "br",
    "zstd",
    "compress",
    "gzip, deflate",
    "identity, gzip",
    "gzip, identity",
    "unknown-coding",
]
PLAIN_LIMIT = 24 * MIB  # the decoded bomb is 64 MiB; a call may not come close
BOMB_SIZE = 64 * MIB


class _RawStream(httpx2.AsyncByteStream):
    """A lazy stream (httpx2 does not read it while the response is built)."""

    def __init__(self, data: bytes) -> None:
        self.data = data

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for start in range(0, len(self.data), 16384):
            yield self.data[start : start + 16384]


class _RecordingStream(FakeStream):
    def __init__(self, answer: bytes, writes: list[bytes]) -> None:
        super().__init__(answer)
        self._writes = writes

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        self._writes.append(bytes(buffer))


class _RecordingInner(SpyInner):
    def __init__(self, answer: bytes) -> None:
        super().__init__(answer=answer)
        self.writes: list[bytes] = []

    async def connect_tcp(self, host: str, port: int, *args: Any, **kwargs: Any) -> FakeStream:  # type: ignore[override]
        self.connects.append((host, port))
        return _RecordingStream(self.answer, self.writes)


def _ok_body(preset: PresetId) -> bytes:
    path = "/v1/messages" if preset is PresetId.ANTHROPIC else "/v1/chat/completions"
    return model_reply()(httpx2.Request("POST", f"https://x.example{path}")).content


def _raw_http(headers: dict[str, str], body: bytes) -> bytes:
    lines = {"Content-Length": str(len(body)), "Connection": "close", **headers}
    head = "HTTP/1.1 200 OK\r\n" + "".join(f"{k}: {v}\r\n" for k, v in lines.items()) + "\r\n"
    return head.encode() + body


def _setup(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    preset: PresetId,
    headers: dict[str, str],
    body: bytes,
) -> tuple[AIProvider, Any]:
    """A provider whose upstream answers ``200`` with ``headers`` and the raw ``body``."""
    if path == "transport":
        upstream = FakeUpstream(
            lambda request: httpx2.Response(200, headers=headers, stream=_RawStream(body))
        )
        provider, _ = make_provider(preset, upstream=upstream)
        return provider, upstream
    inner = _RecordingInner(_raw_http(headers, body))
    real = GuardedNetworkBackend
    # Every module that builds the default guarded backend gets the fake network below it.
    for module in ("app.net.client", "app.net.ai_client", "app.net.guard"):
        monkeypatch.setattr(
            f"{module}.GuardedNetworkBackend",
            lambda: real(resolver=ResolverSpy([PUBLIC_V4]), inner=inner),
            raising=False,
        )
    return provider_for(preset, "test-model-1", SecretStr(KEY)), inner


def _accept_encodings(path: str, observed: Any) -> list[str]:
    if path == "transport":
        return [s.headers.get("accept-encoding", "<absent>") for s in observed.seen]
    raw = b"".join(observed.writes).decode("latin-1").lower()
    return [
        line.split(":", 1)[1].strip()
        for line in raw.split("\r\n")
        if line.startswith("accept-encoding:")
    ]


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("preset", PRESETS)
def test_encoding_request_asks_for_identity_only(
    monkeypatch: pytest.MonkeyPatch, preset: PresetId, op: str, path: str
) -> None:
    provider, observed = _setup(
        monkeypatch, path, preset, {"content-type": "application/json"}, _ok_body(preset)
    )

    run(provider, op)

    assert _accept_encodings(path, observed) == ["identity"]


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("header", [{}, {"content-encoding": "identity"}])
def test_encoding_identity_or_absent_content_encoding_is_accepted(
    monkeypatch: pytest.MonkeyPatch, preset: PresetId, op: str, path: str, header: dict[str, str]
) -> None:
    provider, _ = _setup(
        monkeypatch,
        path,
        preset,
        {"content-type": "application/json", **header},
        _ok_body(preset),
    )

    assert run(provider, op) is not None


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("encoding", ENCODINGS)
def test_encoding_content_encoding_other_than_identity_is_a_bad_response(
    monkeypatch: pytest.MonkeyPatch, preset: PresetId, op: str, path: str, encoding: str
) -> None:
    body = gzip.compress(_ok_body(preset))
    provider, _ = _setup(
        monkeypatch,
        path,
        preset,
        {"content-type": "application/json", "content-encoding": encoding},
        body,
    )

    assert failure(provider, op).code == "provider_bad_response"


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("op", OPS)
@pytest.mark.parametrize("preset", PRESETS)
@pytest.mark.parametrize("coding", ["gzip", "deflate"])
def test_encoding_compression_bomb_is_refused_without_decoding(
    monkeypatch: pytest.MonkeyPatch, preset: PresetId, op: str, path: str, coding: str
) -> None:
    padding = b'{"pad":"' + b"0" * BOMB_SIZE + b'"}'
    bomb = gzip.compress(padding, 9) if coding == "gzip" else zlib.compress(padding, 9)
    del padding
    assert len(bomb) < 256 * 1024
    provider, _ = _setup(
        monkeypatch,
        path,
        preset,
        {"content-type": "application/json", "content-encoding": coding},
        bomb,
    )
    decoded: list[int] = []
    real_decompressobj = zlib.decompressobj

    def spy(*args: Any, **kwargs: Any) -> Any:
        decoded.append(1)
        return real_decompressobj(*args, **kwargs)

    monkeypatch.setattr(zlib, "decompressobj", spy)

    tracemalloc.start()
    try:
        error = failure(provider, op)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert error.code == "provider_bad_response"
    assert peak < PLAIN_LIMIT
    assert decoded == []
