"""Parsing sandbox: one child process per file with OS limits (ADR 0011; T4, T6).

``run_extraction`` starts ``sys.executable -I -B -c <bootstrap> <app root> <memory>
<cpu>`` in a new session (own process group), with the working directory ``/tmp``
and a minimal environment (the server environment is never copied). The bootstrap
puts the app root (computed here from ``app.__file__``, never from input or the
environment) first on ``sys.path`` and runs ``app.extraction.worker``. The child
sets ``RLIMIT_AS``, ``RLIMIT_CPU``, ``RLIMIT_FSIZE`` = 0, ``RLIMIT_NOFILE`` and
``RLIMIT_CORE`` = 0 before it reads any input.

The parent writes a JSON header line and the file bytes to stdin, reads stdout up to
``max_result_bytes`` and drains stderr into nothing, all at the same time (no pipe
deadlock), under one wall-clock deadline. Then:

- deadline passed → ``extraction_timeout``;
- non-zero exit, a signal (CPU or memory limit included), more output than the cap,
  invalid JSON, a reply outside the schema, or a result that does not match the
  request or the caps → ``extraction_failed``;
- a child error reply → its code (only codes from ``ChildErrorCode``).

The process group is killed on every path that leaves the child running (errors,
timeout, cancellation), and the child is always reaped. Nothing from the child is
logged: one log line holds the outcome code and the duration only.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

import app
from app.extraction.detect import FileKind
from app.extraction.model import (
    DEFAULT_MAX_BLOCKS,
    DEFAULT_MAX_DOCX_ELEMENTS,
    DEFAULT_MAX_DOCX_PART_BYTES,
    DEFAULT_MAX_DOCX_XML_DEPTH,
    DEFAULT_MAX_PDF_PAGES,
    DEFAULT_MAX_PDF_PREV_CHAIN,
    DEFAULT_MAX_TEXT_CHARS,
    DEFAULT_MAX_ZIP_UNCOMPRESSED_BYTES,
    EXTRACTION_FAILED,
    EXTRACTION_TIMEOUT,
    TOO_MUCH_TEXT,
    ChildErrorCode,
    ExtractionError,
    ExtractionResult,
)

logger = logging.getLogger("ai_contrast.extraction")

WORKER_CWD: Final = "/tmp"  # noqa: S108 - the child writes no files (RLIMIT_FSIZE = 0)
HOOK_ENV: Final = "AI_CONTRAST_WORKER_TEST_HOOK"
READ_CHUNK: Final = 64 * 1024
# After the kill, the rest of the pipes is read and thrown away within this time.
DISCARD_SECONDS: Final = 5
# The app root: the directory that holds the `app` package of this server.
APP_ROOT: Final = str(Path(app.__file__).resolve().parent.parent)
_BOOTSTRAP: Final = (
    "import sys\nsys.path.append(sys.argv.pop(1))\nfrom app.extraction.worker import main\nmain()\n"
)


@dataclass(frozen=True)
class SandboxLimits:
    memory_bytes: int
    cpu_seconds: int
    wall_seconds: int
    max_result_bytes: int
    max_text_chars: int = DEFAULT_MAX_TEXT_CHARS
    max_blocks: int = DEFAULT_MAX_BLOCKS
    # DOCX caps (S3-T2); the defaults are the settings defaults.
    docx_max_part_bytes: int = DEFAULT_MAX_DOCX_PART_BYTES
    docx_max_total_bytes: int = DEFAULT_MAX_ZIP_UNCOMPRESSED_BYTES
    docx_max_xml_depth: int = DEFAULT_MAX_DOCX_XML_DEPTH
    docx_max_elements: int = DEFAULT_MAX_DOCX_ELEMENTS
    # PDF caps (S3-T3); the defaults are the settings defaults.
    pdf_max_pages: int = DEFAULT_MAX_PDF_PAGES
    pdf_max_prev_chain: int = DEFAULT_MAX_PDF_PREV_CHAIN


class _ChildReply(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    result: ExtractionResult | None = None
    error: ChildErrorCode | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Self:
        if (self.result is None) == (self.error is None):
            msg = "exactly one of result and error"
            raise ValueError(msg)
        return self


class _ResultTooLargeError(Exception):
    pass


def _child_env(test_hook: str | None) -> dict[str, str]:
    env = {"LC_ALL": "C.UTF-8"}
    if test_hook is not None:
        env[HOOK_ENV] = test_hook
    return env


def _kill_group(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        # The child leads its own session, so its process group id is its pid.
        os.killpg(process.pid, signal.SIGKILL)


async def _write_input(process: asyncio.subprocess.Process, header: bytes, data: bytes) -> None:
    stdin = process.stdin
    if stdin is None:  # pragma: no cover - always a pipe
        return
    # The child may exit before it reads everything; its exit status decides.
    with contextlib.suppress(BrokenPipeError, ConnectionResetError):
        stdin.write(header)
        stdin.write(data)
        await stdin.drain()
        stdin.close()
        await stdin.wait_closed()


async def _read_capped(stream: asyncio.StreamReader | None, cap: int) -> bytes:
    if stream is None:  # pragma: no cover - always a pipe
        return b""
    buffer = bytearray()
    while chunk := await stream.read(READ_CHUNK):
        buffer += chunk
        if len(buffer) > cap:
            raise _ResultTooLargeError
    return bytes(buffer)


async def _drain(stream: asyncio.StreamReader | None) -> None:
    if stream is None:  # pragma: no cover - always a pipe
        return
    while await stream.read(READ_CHUNK):
        pass


async def _discard_rest(process: asyncio.subprocess.Process) -> None:
    """Read the pipes of a dead child to their end, so that they close."""
    with contextlib.suppress(TimeoutError):
        async with asyncio.timeout(DISCARD_SECONDS):
            await asyncio.gather(_drain(process.stdout), _drain(process.stderr))


async def _communicate(
    process: asyncio.subprocess.Process, header: bytes, data: bytes, cap: int
) -> bytes:
    """Write the input, drain stderr and read stdout at the same time."""
    writer = asyncio.create_task(_write_input(process, header, data))
    drainer = asyncio.create_task(_drain(process.stderr))
    reader = asyncio.create_task(_read_capped(process.stdout, cap))
    tasks = (writer, drainer, reader)
    try:
        output = await reader
        await drainer
        await writer
        await process.wait()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return output


def _parse_reply(
    output: bytes, kind: FileKind, data: bytes, limits: SandboxLimits
) -> ExtractionResult:
    try:
        reply = _ChildReply.model_validate_json(output)
    except ValidationError:
        # `from None`: a validation error may quote the child output.
        raise ExtractionError(EXTRACTION_FAILED) from None
    if reply.error is not None:
        raise ExtractionError(reply.error)
    result = reply.result
    if result is None or result.kind != kind.value or result.bytes != len(data):
        raise ExtractionError(EXTRACTION_FAILED)
    # The caps again, in the parent: every cap fails closed.
    if len(result.blocks) > limits.max_blocks or (
        sum(len(block.text) for block in result.blocks) > limits.max_text_chars
    ):
        raise ExtractionError(TOO_MUCH_TEXT)
    return result


async def _run(
    data: bytes, kind: FileKind, limits: SandboxLimits, test_hook: str | None
) -> ExtractionResult:
    header = json.dumps(
        {
            "kind": kind.value,
            "size": len(data),
            "max_text_chars": limits.max_text_chars,
            "max_blocks": limits.max_blocks,
            "docx_max_part_bytes": limits.docx_max_part_bytes,
            "docx_max_total_bytes": limits.docx_max_total_bytes,
            "docx_max_xml_depth": limits.docx_max_xml_depth,
            "docx_max_elements": limits.docx_max_elements,
            "pdf_max_pages": limits.pdf_max_pages,
            "pdf_max_prev_chain": limits.pdf_max_prev_chain,
        }
    ).encode()
    try:
        process = await _start_child(limits, test_hook)
    except OSError:
        # No traceback: the outcome code is logged by `run_extraction`.
        raise ExtractionError(EXTRACTION_FAILED) from None
    try:
        async with asyncio.timeout(limits.wall_seconds):
            output = await _communicate(process, header + b"\n", data, limits.max_result_bytes)
    except TimeoutError:
        raise ExtractionError(EXTRACTION_TIMEOUT) from None
    except _ResultTooLargeError:
        raise ExtractionError(EXTRACTION_FAILED) from None
    finally:
        _kill_group(process)
        # Always reap (no zombie, also after a timeout or a cancellation) and read the
        # pipes to their end at the same time, so that neither can wait on the other.
        await asyncio.gather(process.wait(), _discard_rest(process))
    if process.returncode != 0:
        raise ExtractionError(EXTRACTION_FAILED)
    return _parse_reply(output, kind, data, limits)


async def _start_child(limits: SandboxLimits, test_hook: str | None) -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        "-B",
        "-c",
        _BOOTSTRAP,
        APP_ROOT,
        str(limits.memory_bytes),
        str(limits.cpu_seconds),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=WORKER_CWD,
        env=_child_env(test_hook),
        start_new_session=True,
        close_fds=True,
    )


async def run_extraction(
    data: bytes,
    kind: FileKind,
    *,
    limits: SandboxLimits,
    test_hook: str | None = None,
) -> ExtractionResult:
    """Extract ``data`` of ``kind`` in a new child process.

    Raises ``ExtractionError`` with a code. ``test_hook`` is for tests only; the HTTP
    handler never passes it.
    """
    start = time.monotonic()
    outcome = EXTRACTION_FAILED
    try:
        result = await _run(data, kind, limits, test_hook)
        outcome = "ok"
    except ExtractionError as error:
        outcome = error.code
        raise
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    finally:
        logger.info(
            "extraction kind=%s outcome=%s duration_ms=%d",
            kind.value,
            outcome,
            (time.monotonic() - start) * 1000,
        )
    return result
