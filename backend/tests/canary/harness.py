"""Canary pipeline: extract -> /api/segment -> browser-equivalent masking -> /api/safety-check.

``run_cell(path, location)`` runs one document through the whole pipeline once (cached)
and returns everything the tests look at. Matching is case-insensitive, NFKC, with the
checked-in confusable skeleton, and ignores every non-alphanumeric character (separators,
zero-width and format characters, hyphens, spaces).
"""

from __future__ import annotations

import functools
import json
import logging
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from app.pseudo.matching import fold
from app.settings import Settings
from tests.canary import builders, known_leaks
from tests.canary.catalogue import Canary
from tests.canary.masking_ref import mask_segmentation
from tests.netfakes import StreamingTransport
from tests.segment_helpers import block, post_blocks

OCTET = {"Content-Type": "application/octet-stream"}
JSON_HEADERS = {"Content-Type": "application/json"}
DOCX_CT = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DOC_ID = "a1B2c3D4e5F6g7H8i9J0k1L2m3"
MIN_FRAGMENT = 5
FRAGMENT_RATIO = 0.7

# ------------------------------------------------------------------------------ matching


def key(value: str) -> str:
    """NFKC, case folding, confusable skeleton; every non-alphanumeric character removed."""
    return "".join(ch for ch in fold(value) if ch.isalnum())


PLACEHOLDER = re.compile(r"\[[A-Z]\.[A-Z_]+_[0-9]+\]")


def analyse(value: str) -> tuple[str, list[bool]]:
    """``key(value)`` plus, for every character of it, whether it starts a word.

    Placeholders and every non-alphanumeric character (whitespace, punctuation, brackets,
    hyphens, zero-width, ``№``) are word breaks; a letter/digit change is a boundary too.
    """
    chars: list[str] = []
    starts: list[bool] = []
    previous = ""  # last character seen; "" after a break
    for ch in fold(PLACEHOLDER.sub(" ", value).replace("№", " ")):
        if not ch.isalnum():
            previous = ""
            continue
        chars.append(ch)
        starts.append(previous == "" or previous.isdigit() != ch.isdigit())
        previous = ch
    return "".join(chars), starts


def leaked_part(needle: str, haystack_key: str, starts: list[bool]) -> str | None:
    """The part of ``needle`` found in the text, or ``None``.

    The whole value counts anywhere. A fragment of at least 70 % of one word of the needle
    (and at least 5 characters) counts as a partial mask when it begins at a word start or
    at a letter/digit boundary of the text (so also right after a placeholder, ``№``, ``-``,
    ``/`` or ``:``). Inside an ordinary word (``льник`` in "Страхувальник") or across the
    digits of a log line it is not a leak.
    """
    k = key(needle)
    if k and k in haystack_key:
        return k
    for word in needle.split():
        wk = key(word)
        if len(wk) < MIN_FRAGMENT:
            continue
        window = max(MIN_FRAGMENT, math.ceil(len(wk) * FRAGMENT_RATIO))
        for start in range(len(wk) - window + 1):
            fragment = wk[start : start + window]
            at = haystack_key.find(fragment)
            while at >= 0:
                if starts[at]:
                    return fragment
                at = haystack_key.find(fragment, at + 1)
    return None


def find_leaks(needles: Iterable[str], *texts: str) -> list[str]:
    text = "\n".join(texts)
    full, starts = analyse(text)
    return [n for n in needles if leaked_part(n, full, starts) is not None]


# --------------------------------------------------------------------------------- logs


_STANDARD = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime"}


class LogTap(logging.Handler):
    """Collects what a log handler could see: message, arguments, custom attributes and
    exception text. The standard record attributes (``created``, ``msecs``, ``thread`` ...)
    are numeric noise that would collide with digit canaries, so they are left out."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.parts: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.parts.append(record.getMessage())
        self.parts.append(repr(record.args))
        self.parts.append(repr({k: v for k, v in record.__dict__.items() if k not in _STANDARD}))
        if record.exc_info and record.exc_info[1] is not None:
            self.parts.append(str(record.exc_info[1]))
        if record.exc_text:
            self.parts.append(record.exc_text)

    @property
    def text(self) -> str:
        return "\n".join(self.parts)


class tap_logs:  # noqa: N801 - a context manager used like a function
    def __enter__(self) -> LogTap:
        self.tap = LogTap()
        root = logging.getLogger()
        self.level = root.level
        self.quiet = [(n, logging.getLogger(n).level) for n in ("httpx", "httpcore")]
        for name, _ in self.quiet:
            logging.getLogger(name).setLevel(logging.WARNING)
        root.setLevel(logging.DEBUG)
        root.addHandler(self.tap)
        return self.tap

    def __exit__(self, *exc: object) -> None:
        root = logging.getLogger()
        root.removeHandler(self.tap)
        root.setLevel(self.level)
        for name, level in self.quiet:
            logging.getLogger(name).setLevel(level)


# ------------------------------------------------------------------------------- client


@functools.cache
def client() -> TestClient:
    """One app for the whole canary run; the Google fake is installed per call."""
    return TestClient(create_app(Settings()), raise_server_exceptions=False)


def google_export(
    data: bytes, *, status: int = 200, headers: dict[str, str] | None = None
) -> TestClient:
    """The client with a fake Google transport that answers every request with ``data``."""
    app = client().app
    reply_headers = {"Content-Type": DOCX_CT, **(headers or {})}
    app.state.google_client_factory = lambda: httpx.AsyncClient(  # type: ignore[attr-defined]
        transport=StreamingTransport(
            lambda request: httpx.Response(status, headers=reply_headers, content=data)
        )
    )
    return client()


def extract(
    path: str,
    data: bytes,
    *,
    headers: dict[str, str] | None = None,
    url: str = "",
    google_headers: dict[str, str] | None = None,
) -> Any:
    c = client()
    if path == "gdoc":
        c = google_export(data, headers=google_headers)
        return c.post("/api/extract/google-doc", json={"document_id": DOC_ID}, headers=headers)
    return c.post("/api/extract" + url, content=data, headers={**OCTET, **(headers or {})})


# -------------------------------------------------------------------------------- cells


@dataclass
class CellRun:
    path: str
    location: str
    canaries: list[Canary]
    extract_status: int = 0
    blocks: list[dict[str, Any]] = field(default_factory=list)
    segment_status: int = 0
    segment: dict[str, Any] = field(default_factory=dict)
    masked: list[dict[str, str]] = field(default_factory=list)
    acknowledged: list[list[Any]] = field(default_factory=list)
    safety_status: int = 0
    safety_text: str = ""
    safety_headers: dict[str, str] = field(default_factory=dict)
    safety_payload: dict[str, Any] = field(default_factory=dict)
    logs: str = ""

    @property
    def masked_text(self) -> str:
        return "\n".join(c["text"] for c in self.masked)

    @property
    def block_text(self) -> str:
        return "\n".join(b["text"] for b in self.blocks)


def input_blocks(
    path: str, location: str, canaries: list[Canary]
) -> tuple[int, list[dict[str, Any]]]:
    """Run the input path; returns the extract status and the blocks for ``/api/segment``."""
    if path == "ocr":
        return 200, builders.ocr_blocks(location, canaries)
    if path == "txt":
        data = builders.txt_bytes(location, canaries)
    elif path == "pdf":
        data = builders.build_pdf_for(location, canaries)
    else:
        data = builders.build_docx_for(location, canaries)
    response = extract(path, data)
    if response.status_code != 200:
        return response.status_code, []
    blocks: list[dict[str, Any]] = response.json()["blocks"]
    return 200, blocks


def pipeline(blocks: list[dict[str, Any]], run: CellRun) -> CellRun:
    """segment -> masking -> safety check, filling ``run``."""
    response = post_blocks(client(), [block(b["text"], b["part"], b["page"]) for b in blocks])
    run.segment_status = response.status_code
    if response.status_code != 200:
        return run
    run.segment = response.json()
    masked = mask_segmentation(run.segment, "A")
    run.masked, run.acknowledged = masked.clauses, masked.acknowledged
    run.safety_payload = {
        "label": "A",
        "detector_version": run.segment["detector_version"],
        "clauses": run.masked,
        "acknowledged_unmasked": run.acknowledged,
    }
    reply = client().post(
        "/api/safety-check",
        content=json.dumps(run.safety_payload, ensure_ascii=False).encode(),
        headers=JSON_HEADERS,
    )
    run.safety_status = reply.status_code
    run.safety_text = reply.text
    run.safety_headers = dict(reply.headers)
    return run


@functools.cache
def run_cell(path: str, location: str, group: str = "all") -> CellRun:
    """One cell. ``all`` plants every canary; ``clean`` leaves out the documented gaps of
    ``known_leaks.py``, so that the safety check (which refuses a document with a
    remaining identifier) can answer 200. Detection depends a little on the neighbours,
    so the leak checks use ``all`` and the safety check uses ``clean``."""
    expected = known_leaks.expected_leaks(path, location)
    canaries = [
        c for c in builders.applicable(path, location) if group == "all" or c.id not in expected
    ]
    run = CellRun(path, location, canaries)
    if not canaries:
        return run
    with tap_logs() as tap:
        status, blocks = input_blocks(path, location, canaries)
        run.extract_status, run.blocks = status, blocks
        if status == 200:
            pipeline(blocks, run)
    run.logs = tap.text
    return run


# --------------------------------------------------------------------- stage 6 plug-in


class WireCapture:
    """Collects everything an ``AIProvider`` adapter would put on the wire.

    Stage 6 hook: a fake provider (or a patched SDK transport) calls ``record`` with the
    request it would send (system prompt, messages, headers, URL). The canary tests then
    call ``assert_clean``. Until stage 6 nothing records, so the check passes vacuously;
    ``tests/canary/test_harness_selfcheck.py`` proves that it fails when a canary is recorded.
    """

    def __init__(self) -> None:
        self.captured: list[str] = []

    def record(self, *parts: object) -> None:
        self.captured.extend(p if isinstance(p, str) else repr(p) for p in parts)

    def leaks(self, needles: Iterable[str]) -> list[str]:
        return find_leaks(needles, *self.captured)
