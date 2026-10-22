"""Self-checks of the test PDF builder (``tests/pdfbuild.py``). These pass without the
S3-T3 implementation: they make sure the fixtures are what the tests claim."""

from __future__ import annotations

import re

from tests.pdfbuild import (
    Encryption,
    Page,
    build_pdf,
    incremental_update,
    last_startxref,
    rc4,
    replace_content,
    text,
    text_pdf,
)

_ENTRY = re.compile(rb"(\d{10}) 00000 n\r\n")


def _sections(data: bytes) -> list[tuple[int, list[tuple[int, int]]]]:
    """(xref offset, [(object number, offset)]) for every revision, newest first."""
    out = []
    at = last_startxref(data)
    seen = set()
    while at not in seen:
        seen.add(at)
        assert data[at : at + 5] == b"xref\n"
        table, trailer = data[at:].split(b"trailer", 1)
        entries = []
        rows = table.split(b"\n")[1:]
        i = 0
        while i < len(rows) and rows[i].strip():
            first, count = (int(v) for v in rows[i].split())
            for k in range(count):
                row = rows[i + 1 + k] + b"\n"
                match = _ENTRY.match(row)
                if match:
                    entries.append((first + k, int(match.group(1))))
            i += 1 + count
        out.append((at, entries))
        prev = re.search(rb"/Prev (\d+)", trailer.split(b"startxref", 1)[0])
        if prev is None:
            break
        at = int(prev.group(1))
    return out


def test_xref_offsets_point_at_their_objects() -> None:
    data = build_pdf([Page(text("Synthetic.")), Page(text("Синтетичний текст."))])

    for _, entries in _sections(data):
        for num, offset in entries:
            assert data[offset:].startswith(f"{num} 0 obj".encode())


def test_incremental_updates_chain_back_to_base() -> None:
    data = text_pdf("Synthetic.")
    for n in range(3):
        data = incremental_update(data, replace_content(0, text(f"Revision {n}.")))

    assert len(_sections(data)) == 4


def test_self_loop_points_at_own_xref() -> None:
    data = incremental_update(text_pdf("Synthetic."), replace_content(0, ""), self_loop=True)

    at = last_startxref(data)
    assert f"/Prev {at} ".encode() in data[at:]


def test_rc4_known_answer() -> None:
    assert rc4(b"Key", b"Plaintext").hex() == "bbf316e8d940af0ad3"


def test_encryption_dictionary_has_32_byte_owner_and_user_values() -> None:
    for revision in (2, 3):
        enc = Encryption(revision=revision)
        assert len(enc.owner_value()) == 32
        assert len(enc.user_value()) == 32
    assert b"/Encrypt" in build_pdf(text("Synthetic."), encryption=Encryption())
