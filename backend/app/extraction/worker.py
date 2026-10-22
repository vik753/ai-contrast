"""The parsing child (ADR 0011; threat model T4, T6).

Started by ``app.extraction.sandbox`` only, never by hand. Protocol:

- argv: ``memory_bytes cpu_seconds`` (set by the parent, never from input).
- stdin: one JSON header line ``{"kind", "size", "max_text_chars", "max_blocks",
  "docx_max_part_bytes", "docx_max_total_bytes", "docx_max_xml_depth",
  "docx_max_elements", "pdf_max_pages", "pdf_max_prev_chain"}``, then exactly
  ``size`` bytes of the file.
- stdout: one JSON object, ``{"result": <ExtractionResult>}`` or
  ``{"error": "<code>"}``; exit status 0.
- Any other failure: exit status 1 and nothing on stdout. stderr is drained and
  thrown away by the parent.

The child sets its own limits before it reads any input. It imports only the
extraction code: no FastAPI, no settings, no logging configuration.

``AI_CONTRAST_WORKER_TEST_HOOK`` (tests only): the parent sets it in the child's
minimal environment only when a test passes ``test_hook``; the HTTP handler never
does. The hook runs after the limits are set and the input is read.
"""

from __future__ import annotations

import json
import os
import resource
import signal
import sys
import time
from typing import BinaryIO, Final

# Open files: stdin, stdout, stderr and a few for module imports.
MAX_OPEN_FILES: Final = 32
MAX_HEADER_BYTES: Final = 1024
HOOK_ENV: Final = "AI_CONTRAST_WORKER_TEST_HOOK"
FAILURE_EXIT: Final = 1
UNKNOWN_HOOK_EXIT: Final = 2
_HOOK_EXIT: Final = 3
_FLOOD_BYTES: Final = 4 * 1024 * 1024
_HUGE_MEMORY: Final = 1024 * 1024 * 1024


def set_limits(memory_bytes: int, cpu_seconds: int) -> None:
    """Soft and hard limits; the child cannot raise them again."""
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (MAX_OPEN_FILES, MAX_OPEN_FILES))
    # No new processes: `fork` fails (for a user other than root, ADR 0011).
    resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))
    # SIGXCPU at the soft limit, SIGKILL one second later at the hard limit.
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    data = stream.read(size)
    if len(data) != size or stream.read(1):
        raise ValueError
    return data


def _non_negative(header: dict[str, object], key: str) -> int:
    value = header.get(key)
    if type(value) is not int or value < 0:
        raise ValueError
    return value


def _run_hook(name: str, data: bytes, out: BinaryIO) -> None:  # noqa: PLR0912 - one branch per hook
    if name == "sleep":
        time.sleep(3600)
    elif name == "burn_cpu":
        while True:
            pass
    elif name == "allocate_memory":
        block = bytearray(_HUGE_MEMORY)
        block[::4096] = b"\x01" * len(block[::4096])
    elif name == "huge_output":
        chunk = b"x" * 65536
        while True:
            out.write(chunk)
    elif name == "exit_nonzero":
        os._exit(_HOOK_EXIT)
    elif name == "kill_self":
        os.kill(os.getpid(), signal.SIGKILL)
    elif name == "write_file":
        with open("ai-contrast-write-probe", "wb") as probe:  # noqa: PTH123 - test hook
            probe.write(data)
    elif name == "stderr_echo":
        sys.stderr.buffer.write(data)
        sys.stderr.buffer.flush()
        os._exit(FAILURE_EXIT)
    elif name == "stderr_flood":
        written = 0
        while written < _FLOOD_BYTES:
            sys.stderr.buffer.write(data)
            written += len(data)
        sys.stderr.buffer.flush()
    elif name == "fork":
        _fork_probe()
    elif name == "invalid_json":
        out.write(b"not json")
        out.flush()
        os._exit(0)
    elif name == "invalid_schema":
        out.write(b'{"unexpected": 1}')
        out.flush()
        os._exit(0)
    else:
        os._exit(UNKNOWN_HOOK_EXIT)


def _fork_probe() -> None:
    """Test hook: exit with ``_HOOK_EXIT`` if ``fork`` works; else go on normally."""
    try:
        pid = os.fork()
    except OSError:
        return
    if pid == 0:
        os._exit(0)
    os.waitpid(pid, 0)
    os._exit(_HOOK_EXIT)


def _extract(kind: str, data: bytes, header: dict[str, object]) -> bytes:
    from app.extraction.model import (  # noqa: PLC0415 - after the limits
        ExtractionError,
        ExtractionResult,
    )

    max_chars = _non_negative(header, "max_text_chars")
    max_blocks = _non_negative(header, "max_blocks")
    result: ExtractionResult
    try:
        if kind == "text":
            from app.extraction.text import extract_text_file  # noqa: PLC0415 - after the limits

            result = extract_text_file(data, max_chars=max_chars, max_blocks=max_blocks)
        elif kind == "docx":
            from app.extraction.docx import DocxLimits, extract_docx  # noqa: PLC0415

            limits = DocxLimits(
                max_part_bytes=_non_negative(header, "docx_max_part_bytes"),
                max_total_bytes=_non_negative(header, "docx_max_total_bytes"),
                max_xml_depth=_non_negative(header, "docx_max_xml_depth"),
                max_elements=_non_negative(header, "docx_max_elements"),
            )
            result = extract_docx(data, max_chars=max_chars, max_blocks=max_blocks, limits=limits)
        elif kind == "pdf":
            from app.extraction.pdf import PdfLimits, extract_pdf  # noqa: PLC0415

            pdf_limits = PdfLimits(
                max_pages=_non_negative(header, "pdf_max_pages"),
                max_prev_chain=_non_negative(header, "pdf_max_prev_chain"),
            )
            result = extract_pdf(
                data, max_chars=max_chars, max_blocks=max_blocks, limits=pdf_limits
            )
        else:
            raise ValueError
    except ExtractionError as error:
        return json.dumps({"error": error.code}).encode()
    return b'{"result":' + result.model_dump_json().encode() + b"}"


def _main(argv: list[str]) -> None:
    memory_bytes, cpu_seconds = (int(arg) for arg in argv)
    set_limits(memory_bytes, cpu_seconds)

    stdin = sys.stdin.buffer
    header = json.loads(stdin.readline(MAX_HEADER_BYTES))
    if not isinstance(header, dict):
        raise TypeError
    kind = header.get("kind")
    if not isinstance(kind, str):
        raise TypeError
    data = _read_exact(stdin, _non_negative(header, "size"))

    out = sys.stdout.buffer
    hook = os.environ.get(HOOK_ENV)
    if hook is not None:
        _run_hook(hook, data, out)

    reply = _extract(kind, data, header)
    out.write(reply)
    out.flush()


def main() -> None:
    """Entry point. Exits 0 after writing a reply, 1 on any other failure."""
    try:
        _main(sys.argv[1:])
    except Exception:  # noqa: BLE001 - no traceback: it may hold contract text
        os._exit(FAILURE_EXIT)
    sys.exit(0)
