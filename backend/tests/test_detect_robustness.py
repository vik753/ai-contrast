"""S2-T1 AC3: detection is robust and bounded (T4, T6).

- Seeded random inputs and every truncation of a small DOCX either return a
  ``FileKind`` or raise ``DetectionError``. Nothing else escapes.
- The worst case at the caps (2,000 entries in a 10 MiB file) finishes in
  under 0.5 s. The measurement takes the best of several runs, so a busy CI
  machine does not make the test flaky.
"""

from __future__ import annotations

import contextlib
import importlib
import random
import time
from collections.abc import Callable
from types import ModuleType
from typing import Any

from tests.zipbuild import (
    DOCX_PARTS,
    PDF_SAMPLE,
    build_zip,
    docx_entries,
    minimal_docx,
    stored,
)

MIB = 1024 * 1024
MAX_FILE_BYTES = 10 * MIB
MAX_ENTRIES = 2000
TIME_BUDGET_SECONDS = 0.5
TIMING_RUNS = 5

RANDOM_SEED = 20261021
RANDOM_CASES = 2400
MAX_RANDOM_LENGTH = 64 * 1024

# Prefixes that steer random data into each branch of the detector.
PREFIXES: tuple[bytes, ...] = (
    b"",
    b"PK\x03\x04",
    b"%PDF-",
    bytes.fromhex("D0CF11E0A1B11AE1"),
    b"\xef\xbb\xbf",
    b"\xff\xfe",
    b"\xfe\xff",
    b"{\\rtf",
)


def _module() -> ModuleType:
    return importlib.import_module("app.extraction.detect")


def _default_limits(module: ModuleType) -> Any:
    return module.ZipLimits(
        max_entries=MAX_ENTRIES, max_uncompressed_bytes=100 * MIB, max_ratio=200
    )


def _failures(inputs: list[tuple[str, bytes]]) -> list[str]:
    """Run detection on every input. Return a description of every input
    that raised anything other than ``DetectionError`` or returned something
    other than a ``FileKind``."""
    module = _module()
    limits = _default_limits(module)
    failures: list[str] = []
    for label, data in inputs:
        try:
            result = module.detect_kind(data, limits=limits)
        except module.DetectionError:
            continue
        except Exception as exc:  # noqa: BLE001 - collect, then report all
            failures.append(f"{label}: raised {type(exc).__name__}")
            continue
        if not isinstance(result, module.FileKind):
            failures.append(f"{label}: returned {type(result).__name__}")
    return failures


def test_detect_random_bytes_return_kind_or_detection_error() -> None:
    rng = random.Random(RANDOM_SEED)  # noqa: S311 - seeded test data, not crypto
    inputs: list[tuple[str, bytes]] = []
    for case in range(RANDOM_CASES):
        prefix = PREFIXES[case % len(PREFIXES)]
        length = rng.randint(1, MAX_RANDOM_LENGTH - len(prefix))
        inputs.append((f"random case {case}", prefix + rng.randbytes(length)))

    assert _failures(inputs) == []


def test_detect_random_short_bytes_return_kind_or_detection_error() -> None:
    rng = random.Random(RANDOM_SEED + 1)  # noqa: S311 - seeded test data, not crypto
    inputs = [(f"short case {case}", rng.randbytes(rng.randint(1, 64))) for case in range(2000)]

    assert _failures(inputs) == []


def test_detect_every_truncation_of_docx_returns_kind_or_detection_error() -> None:
    data = minimal_docx()
    inputs = [(f"truncated to {n} bytes", data[:n]) for n in range(1, len(data))]

    assert _failures(inputs) == []


def test_detect_every_truncation_of_stored_docx_with_comment_returns_kind_or_error() -> None:
    data = build_zip(docx_entries(), comment=b"synthetic comment")
    inputs = [(f"truncated to {n} bytes", data[:n]) for n in range(1, len(data))]

    assert _failures(inputs) == []


def test_detect_byte_mutations_of_docx_return_kind_or_detection_error() -> None:
    rng = random.Random(RANDOM_SEED + 2)  # noqa: S311 - seeded test data, not crypto
    original = minimal_docx()
    inputs: list[tuple[str, bytes]] = []
    for case in range(2000):
        data = bytearray(original)
        for _ in range(rng.randint(1, 8)):
            data[rng.randrange(len(data))] = rng.randrange(256)
        inputs.append((f"mutation case {case}", bytes(data)))

    assert _failures(inputs) == []


def test_detect_zip_central_directory_field_mutations_return_kind_or_error() -> None:
    # Overwrite each 2- and 4-byte field of the central directory and EOCD
    # with extreme values.
    original = build_zip(docx_entries())
    cd_start = original.index(b"PK\x01\x02")
    inputs: list[tuple[str, bytes]] = []
    for offset in range(cd_start, len(original) - 1):
        for value in (b"\x00\x00", b"\xff\xff", b"\xff\xff\xff\xff", b"\x00\x00\x00\x80"):
            data = bytearray(original)
            data[offset : offset + len(value)] = value
            inputs.append((f"field at {offset} set to {value.hex()}", bytes(data[: len(original)])))

    assert _failures(inputs) == []


# --- Bounded work -------------------------------------------------------------------


def _best_time(func: Callable[[], object]) -> float:
    best = float("inf")
    for _ in range(TIMING_RUNS):
        start = time.perf_counter()
        func()
        best = min(best, time.perf_counter() - start)
    return best


def _worst_case_archive(*, duplicate_last: bool = False) -> bytes:
    """2,000 entries with 512-byte names, padded with one stored entry to
    exactly 10 MiB."""
    entries = docx_entries()
    for i in range(MAX_ENTRIES - len(entries) - 1):
        prefix = f"word/media/{i:05d}-"
        entries.append(stored(prefix + "n" * (512 - len(prefix))))
    if duplicate_last:
        # The duplicate of the first name hides at the very end.
        entries.append(stored(DOCX_PARTS[0][0].upper()))
    else:
        entries.append(stored("word/media/padding.bin"))
    assert len(entries) == MAX_ENTRIES

    size_without_padding = len(build_zip(entries))
    entries[-1].data = b"p" * (MAX_FILE_BYTES - size_without_padding)
    data = build_zip(entries)
    assert len(data) == MAX_FILE_BYTES
    return data


def test_detect_worst_case_at_caps_returns_docx() -> None:
    module = _module()

    assert module.detect_kind(_worst_case_archive(), limits=_default_limits(module)) == (
        module.FileKind.DOCX
    )


def test_detect_worst_case_at_caps_finishes_under_half_second() -> None:
    module = _module()
    data = _worst_case_archive()
    limits = _default_limits(module)

    elapsed = _best_time(lambda: module.detect_kind(data, limits=limits))

    assert elapsed < TIME_BUDGET_SECONDS, f"took {elapsed:.3f} s"


def test_detect_worst_case_with_last_duplicate_finishes_under_half_second() -> None:
    module = _module()
    data = _worst_case_archive(duplicate_last=True)
    limits = _default_limits(module)

    codes: list[str] = []

    def run() -> None:
        try:
            module.detect_kind(data, limits=limits)
        except module.DetectionError as exc:
            codes.append(exc.code)

    elapsed = _best_time(run)

    assert codes == ["archive_rejected"] * TIMING_RUNS
    assert elapsed < TIME_BUDGET_SECONDS


def test_detect_ten_mib_without_eocd_finishes_under_half_second() -> None:
    module = _module()
    data = b"PK\x03\x04" + b"\x00" * (MAX_FILE_BYTES - 4)
    limits = _default_limits(module)

    def run() -> None:
        with contextlib.suppress(module.DetectionError):
            module.detect_kind(data, limits=limits)

    assert _best_time(run) < TIME_BUDGET_SECONDS


def test_detect_ten_mib_text_finishes_under_half_second() -> None:
    module = _module()
    data = b"synthetic contract text\n" * (MAX_FILE_BYTES // 24)
    limits = _default_limits(module)

    assert _best_time(lambda: module.detect_kind(data, limits=limits)) < TIME_BUDGET_SECONDS


def test_detect_ten_mib_pdf_finishes_under_half_second() -> None:
    module = _module()
    data = PDF_SAMPLE + b"\x00" * (MAX_FILE_BYTES - len(PDF_SAMPLE))
    limits = _default_limits(module)

    assert _best_time(lambda: module.detect_kind(data, limits=limits)) < TIME_BUDGET_SECONDS
