"""S3-T2 AC1-AC3: ZIP structure, OPC part names and package resolution (T4, T5, T11).

Unit tests of ``extract_docx`` (pure, called in the test process). Every archive is
built in test code. Must fail before the implementation exists.

Assumptions (see the test report): the codes ``archive_rejected`` and
``unsupported_type`` are raised as ``ExtractionError``; the part and total byte caps
fail with ``archive_rejected``; a package without any ``officeDocument``
relationship is ``suspicious_package``.
"""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree

import pytest

from tests.docxbuild import (
    CLAUSE,
    CT_MACRO,
    CT_MACRO_TEMPLATE,
    CT_MAIN,
    CT_TEMPLATE,
    LFH_CRC,
    LFH_CSIZE,
    LFH_FLAGS,
    LFH_METHOD,
    LFH_NAME,
    LFH_USIZE,
    REL_FOOTNOTES,
    REL_HYPERLINK,
    REL_OFFICE_DOCUMENT,
    REL_OFFICE_DOCUMENT_STRICT,
    STRICT_W,
    Package,
    Rel,
    build_docx,
    content_types_xml,
    deflated_entry,
    descriptor_local,
    document_xml,
    layout,
    layout_local,
    local_offsets,
    notes_xml,
    para,
    patch,
    rels_xml,
    stored_entries,
    styles_xml,
    u16,
    u32,
    with_descriptor_flag,
)
from tests.docxrun import code, extract, joined, texts
from tests.zipbuild import RawEntry, build_zip, stored

ARCHIVE = "archive_rejected"
SUSPICIOUS = "suspicious_package"
DOC_INDEX = 2  # [Content_Types].xml, _rels/.rels, word/document.xml


def _valid() -> tuple[list[RawEntry], bytes, list[int]]:
    entries = stored_entries()
    return entries, build_zip(entries), local_offsets(entries)


# --- Baseline -----------------------------------------------------------------------------------


def test_docx_minimal_package_extracted() -> None:
    result = extract(build_docx(Package(body=para(CLAUSE))))

    assert result.kind == "docx"
    assert texts(result) == [CLAUSE]


def test_docx_raw_stored_layout_extracted() -> None:
    entries = stored_entries()

    assert texts(extract(layout(entries))) == [CLAUSE]


def test_docx_result_bytes_is_input_length() -> None:
    data = build_docx(Package(body=para(CLAUSE)))

    assert extract(data).bytes == len(data)


# --- AC1: local headers against the central directory -----------------------------------------


def test_zip_local_header_bad_signature_rejected() -> None:
    _, data, offsets = _valid()

    assert code(patch(data, offsets[DOC_INDEX], b"PK\x03\x05")) == ARCHIVE


def test_zip_local_name_differs_from_central_rejected() -> None:
    _, data, offsets = _valid()
    start = offsets[DOC_INDEX] + LFH_NAME

    assert code(patch(data, start, b"word/documenX.xml")) == ARCHIVE


def test_zip_local_flags_differ_from_central_rejected() -> None:
    _, data, offsets = _valid()

    assert code(patch(data, offsets[DOC_INDEX] + LFH_FLAGS, u16(0x0800))) == ARCHIVE


def test_zip_local_method_differs_from_central_rejected() -> None:
    _, data, offsets = _valid()

    assert code(patch(data, offsets[DOC_INDEX] + LFH_METHOD, u16(8))) == ARCHIVE


def test_zip_local_crc_differs_from_central_rejected() -> None:
    _, data, offsets = _valid()

    assert code(patch(data, offsets[DOC_INDEX] + LFH_CRC, u32(0x12345678))) == ARCHIVE


@pytest.mark.parametrize("field", [LFH_CSIZE, LFH_USIZE], ids=["compressed", "uncompressed"])
def test_zip_local_size_differs_from_central_rejected(field: int) -> None:
    entries, data, offsets = _valid()
    size = len(entries[DOC_INDEX].data)

    assert code(patch(data, offsets[DOC_INDEX] + field, u32(size - 1))) == ARCHIVE


def test_zip_local_header_offset_at_or_after_cd_rejected() -> None:
    entries = stored_entries()
    # The central directory points the last entry at the central directory itself.
    data = layout(entries, offsets_override={len(entries) - 1: 10**6})

    assert code(data) == ARCHIVE


def test_zip_first_entry_not_at_offset_zero_rejected() -> None:
    entries = stored_entries()

    assert code(layout(entries, gaps={0: b"\x00" * 16})) == ARCHIVE


def test_zip_gap_between_entries_rejected() -> None:
    entries = stored_entries()

    assert code(layout(entries, gaps={DOC_INDEX: b"hidden bytes"})) == ARCHIVE


def test_zip_gap_before_central_directory_rejected() -> None:
    entries = stored_entries()

    assert code(layout(entries, tail_gap=b"PK\x03\x04 smuggled")) == ARCHIVE


def test_zip_offsets_not_increasing_rejected() -> None:
    entries = stored_entries()
    order = list(range(len(entries)))
    order[1], order[DOC_INDEX] = order[DOC_INDEX], order[1]

    assert code(layout(entries, cd_order=order)) == ARCHIVE


def test_zip_two_central_records_same_local_header_rejected() -> None:
    entries = stored_entries()
    extra = stored("word/other.xml", entries[DOC_INDEX].data)
    data = layout(
        [*entries, extra],
        locals_=[layout_local(e) for e in entries] + [b""],
        offsets_override={len(entries): local_offsets(entries)[DOC_INDEX]},
    )

    assert code(data) == ARCHIVE


def test_zip_entry_overlapping_next_rejected() -> None:
    entries = stored_entries()
    rels = entries[1]
    longer = len(rels.data) + 4
    # Both headers claim 4 bytes more than the data: the entry runs into the next header.
    entries[1] = RawEntry(
        name=rels.name,
        data=rels.data,
        compressed_size=longer,
        uncompressed_size=longer,
    )

    assert code(layout(entries)) == ARCHIVE


# --- AC1: data descriptor ---------------------------------------------------------------------


def _descriptor_archive(*, signature: bool = True, bad_crc: bool = False) -> bytes:
    entries = [with_descriptor_flag(e) for e in stored_entries()]
    blobs = [descriptor_local(e, signature=signature) for e in entries]
    if bad_crc:
        blobs[DOC_INDEX] = descriptor_local(entries[DOC_INDEX], signature=signature, crc=1)
    return layout(entries, locals_=blobs)


@pytest.mark.parametrize("signature", [True, False], ids=["signed", "unsigned"])
def test_zip_data_descriptor_accepted(signature: bool) -> None:
    assert texts(extract(_descriptor_archive(signature=signature))) == [CLAUSE]


def test_zip_data_descriptor_crc_differs_from_central_rejected() -> None:
    assert code(_descriptor_archive(bad_crc=True)) == ARCHIVE


def test_zip_descriptor_flag_only_in_central_rejected() -> None:
    entries = stored_entries()
    flagged = [*entries]
    flagged[DOC_INDEX] = with_descriptor_flag(entries[DOC_INDEX])
    blobs = [layout_local(e) for e in entries]  # local headers without bit 3

    assert code(layout(flagged, locals_=blobs)) == ARCHIVE


# --- AC1: real size and CRC while streaming ----------------------------------------------------


def _with_doc_entry(entry: RawEntry) -> bytes:
    entries = stored_entries()
    entries[DOC_INDEX] = entry
    return layout(entries)


def test_zip_wrong_crc_in_both_headers_rejected() -> None:
    entries = stored_entries()
    doc = entries[DOC_INDEX]
    entries[DOC_INDEX] = RawEntry(name=doc.name, data=doc.data, crc=0x0BADC0DE)

    assert code(layout(entries)) == ARCHIVE


def test_zip_deflated_part_valid_extracted() -> None:
    doc = stored_entries()[DOC_INDEX]

    assert texts(extract(_with_doc_entry(deflated_entry("word/document.xml", doc.data)))) == [
        CLAUSE
    ]


def test_zip_real_size_above_declared_rejected() -> None:
    # The first ``declared`` bytes are a valid document with a matching CRC; a reader
    # that stops at the declared size would accept it.
    valid = document_xml(para(CLAUSE))
    real = valid + b"<!-- " + b"x" * 5000 + b" -->"
    entry = deflated_entry("word/document.xml", real, declared_size=len(valid), crc_of=valid)

    assert code(_with_doc_entry(entry)) == ARCHIVE


def test_zip_real_size_below_declared_rejected() -> None:
    valid = document_xml(para(CLAUSE))
    entry = deflated_entry("word/document.xml", valid, declared_size=len(valid) + 100)

    assert code(_with_doc_entry(entry)) == ARCHIVE


def test_zip_part_above_part_byte_cap_rejected() -> None:
    data = build_docx(Package(body=para(CLAUSE) * 50))

    assert code(data, max_part_bytes=1024) == ARCHIVE


def test_zip_total_above_total_byte_cap_rejected() -> None:
    data = build_docx(Package(body=para(CLAUSE) * 50))

    assert code(data, max_total_bytes=2048) == ARCHIVE


def test_zip_part_just_below_part_byte_cap_extracted() -> None:
    data = build_docx(Package(body=para(CLAUSE)))

    assert texts(extract(data, max_part_bytes=4096)) == [CLAUSE]


# --- AC2: OPC part names ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "word/%64ocument2.xml",  # "d"
        "word/media/%41.png",  # "A"
        "word/media/a%2Db.png",  # "-"
        "word/media/a%7Eb.png",  # "~"
        "word/media/a%5Fb.png",  # "_"
        "word/media/a%2Eb.png",  # "."
        "word/media/a%30b.png",  # "0"
        "word/media%2Fimage.png",  # "/"
        "word/media%2fimage.png",  # "/" lower case
    ],
)
def test_opc_percent_encoded_unreserved_or_slash_rejected(name: str) -> None:
    data = build_docx(Package(body=para(CLAUSE), extra=[(name, b"synthetic")]))

    assert code(data) == ARCHIVE


def test_opc_percent_encoded_main_part_name_rejected() -> None:
    entries = [stored(n, d) for n, d in Package(body=para(CLAUSE)).parts()]
    entries[DOC_INDEX] = stored("word/%64ocument.xml", entries[DOC_INDEX].data)

    assert code(build_zip(entries)) == ARCHIVE


def test_opc_percent_encoded_reserved_character_accepted() -> None:
    data = build_docx(Package(body=para(CLAUSE), extra=[("word/media/image%20one.png", b"x")]))

    assert texts(extract(data)) == [CLAUSE]


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("word/media/image.png", "WORD/Media/Image.PNG"),
        ("word/media/a%20b.png", "word/media/a b.png"),
        ("word/media/%C3%A4.png", "word/media/%c3%a4.png"),
        ("word/media/%C3%A4.png", "word/media/%C3%84.png"),  # a-umlaut vs A-umlaut
        ("word/media/stra%C3%9Fe.png", "word/media/STRASSE.png"),  # casefold: sharp s
    ],
)
def test_opc_duplicate_names_after_decoding_and_casefold_rejected(first: str, second: str) -> None:
    data = build_docx(
        Package(body=para(CLAUSE), extra=[(first, b"synthetic"), (second, b"synthetic")])
    )

    assert code(data) == ARCHIVE


def test_opc_duplicate_main_part_differing_in_case_rejected() -> None:
    data = build_docx(
        Package(body=para(CLAUSE), extra=[("Word/Document.XML", document_xml(para("Decoy.")))])
    )

    assert code(data) == ARCHIVE


# --- AC3: DTD anywhere -> suspicious_package ----------------------------------------------------

DTD = '<?xml version="1.0"?>\n<!DOCTYPE x [<!ENTITY e "synthetic entity">]>\n'
XXE = '<?xml version="1.0"?>\n<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/hostname">]>\n'
LAUGHS = (
    '<?xml version="1.0"?>\n<!DOCTYPE x [<!ENTITY a "aaaaaaaaaa">'
    '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>\n'
)


def test_dtd_in_content_types_rejected() -> None:
    pkg = Package(
        body=para(CLAUSE),
        content_types=content_types_xml([("/word/document.xml", CT_MAIN)], prolog=DTD),
    )

    assert code(build_docx(pkg)) == SUSPICIOUS


def test_dtd_in_root_rels_rejected() -> None:
    pkg = Package(
        body=para(CLAUSE),
        root_rels=rels_xml([Rel("rId1", REL_OFFICE_DOCUMENT, "word/document.xml")], prolog=DTD),
    )

    assert code(build_docx(pkg)) == SUSPICIOUS


def test_dtd_in_document_rels_rejected() -> None:
    pkg = Package(
        body=para(CLAUSE),
        doc_rels_xml=rels_xml(
            [Rel("rIdX", REL_HYPERLINK, "https://example.invalid/", external=True)], prolog=DTD
        ),
    )

    assert code(build_docx(pkg)) == SUSPICIOUS


@pytest.mark.parametrize(
    ("prolog", "reference"),
    [(DTD, "&e;"), (XXE, "&e;"), (LAUGHS, "&c;")],
    ids=["internal", "xxe", "laughs"],
)
def test_dtd_in_main_part_rejected(prolog: str, reference: str) -> None:
    # ``para`` escapes text, so the entity reference is written as raw XML.
    body = para(CLAUSE) + f"<w:p><w:r><w:t>{reference}</w:t></w:r></w:p>"
    pkg = Package(document=document_xml(body, prolog=prolog))

    assert code(build_docx(pkg)) == SUSPICIOUS


def test_dtd_in_styles_rejected() -> None:
    styles = DTD.encode() + styles_xml().split(b"\n", 1)[1]

    assert code(build_docx(Package(body=para(CLAUSE), styles=styles))) == SUSPICIOUS


def test_dtd_in_footnotes_rejected() -> None:
    notes = DTD.encode() + notes_xml("footnotes", [para("Note.")]).split(b"\n", 1)[1]
    pkg = Package(
        body=para(CLAUSE),
        doc_rels=[Rel("rIdFn", REL_FOOTNOTES, "footnotes.xml")],
        extra=[("word/footnotes.xml", notes)],
    )

    assert code(build_docx(pkg)) == SUSPICIOUS


# --- AC3: officeDocument relationship -------------------------------------------------------------


def test_strict_relationship_type_unsupported() -> None:
    pkg = Package(body=para(CLAUSE), office_rel_type=REL_OFFICE_DOCUMENT_STRICT)

    assert code(build_docx(pkg)) == "docx_strict_unsupported"


def test_strict_namespace_in_main_part_unsupported() -> None:
    decl = f'xmlns:w="{STRICT_W}"'
    pkg = Package(document=document_xml(para(CLAUSE), decl=decl))

    assert code(build_docx(pkg)) == "docx_strict_unsupported"


@pytest.mark.parametrize(
    "content_type",
    [CT_MACRO, CT_TEMPLATE, CT_MACRO_TEMPLATE],
    ids=["docm", "dotx", "dotm"],
)
def test_main_part_macro_or_template_type_unsupported(content_type: str) -> None:
    pkg = Package(body=para(CLAUSE), main_content_type=content_type)

    assert code(build_docx(pkg)) == "unsupported_type"


def test_main_part_without_override_type_unsupported() -> None:
    # Only the Default "xml" -> application/xml applies to the main part.
    pkg = Package(body=para(CLAUSE), content_types=content_types_xml([]))

    assert code(build_docx(pkg)) in {"unsupported_type", SUSPICIOUS}


def test_main_part_at_other_name_extracted() -> None:
    pkg = Package(body=para(CLAUSE), main_part="word/main.xml")

    assert texts(extract(build_docx(pkg))) == [CLAUSE]


def test_decoy_word_document_not_target_rejected() -> None:
    pkg = Package(
        body=para(CLAUSE),
        main_part="word/main.xml",
        extra=[("word/document.xml", document_xml(para("Decoy clause (synthetic).")))],
    )

    assert code(build_docx(pkg)) == SUSPICIOUS


def test_two_office_document_relationships_rejected() -> None:
    root = rels_xml(
        [
            Rel("rId1", REL_OFFICE_DOCUMENT, "word/document.xml"),
            Rel("rId2", REL_OFFICE_DOCUMENT, "word/second.xml"),
        ]
    )
    pkg = Package(
        body=para(CLAUSE),
        root_rels=root,
        extra=[("word/second.xml", document_xml(para("Second body (synthetic).")))],
    )

    assert code(build_docx(pkg)) == SUSPICIOUS


def test_two_office_document_relationships_same_target_rejected() -> None:
    root = rels_xml(
        [
            Rel("rId1", REL_OFFICE_DOCUMENT, "word/document.xml"),
            Rel("rId2", REL_OFFICE_DOCUMENT, "/word/document.xml"),
        ]
    )

    assert code(build_docx(Package(body=para(CLAUSE), root_rels=root))) == SUSPICIOUS


def test_no_office_document_relationship_rejected() -> None:
    pkg = Package(body=para(CLAUSE), root_rels=rels_xml([]))

    assert code(build_docx(pkg)) == SUSPICIOUS


@pytest.mark.parametrize(
    ("target", "external"),
    [
        ("https://example.invalid/word/document.xml", True),
        ("word/document.xml", True),
        ("../word/document.xml", False),
        ("file:///word/document.xml", False),
    ],
    ids=["external-url", "external-mode", "parent", "file-uri"],
)
def test_office_document_target_outside_package_rejected(target: str, external: bool) -> None:
    root = rels_xml([Rel("rId1", REL_OFFICE_DOCUMENT, target, external)])

    assert code(build_docx(Package(body=para(CLAUSE), root_rels=root))) == SUSPICIOUS


def test_office_document_absolute_target_extracted() -> None:
    root = rels_xml([Rel("rId1", REL_OFFICE_DOCUMENT, "/word/document.xml")])

    assert texts(extract(build_docx(Package(body=para(CLAUSE), root_rels=root)))) == [CLAUSE]


# --- AC3: notes, headers and footers only through the main part's relationships ---------------


def test_unrelated_footnotes_part_not_read() -> None:
    hidden = "Unrelated footnote clause (synthetic)."
    pkg = Package(
        body=para(CLAUSE),
        extra=[("word/footnotes.xml", notes_xml("footnotes", [para(hidden)]))],
    )

    assert hidden not in joined(extract(build_docx(pkg)))


def test_footnotes_at_other_name_read_through_relationship() -> None:
    note = "Footnote clause at a non-standard part name (synthetic)."
    pkg = Package(body=para(CLAUSE), footnotes=[para(note)], footnotes_part="word/notes7.xml")

    assert texts(extract(build_docx(pkg)), "footnote") == [note]


def test_footnotes_related_from_root_not_read() -> None:
    note = "Footnote related from the package root (synthetic)."
    root = rels_xml(
        [
            Rel("rId1", REL_OFFICE_DOCUMENT, "word/document.xml"),
            Rel("rId2", REL_FOOTNOTES, "word/rootnotes.xml"),
        ]
    )
    pkg = Package(
        body=para(CLAUSE),
        root_rels=root,
        extra=[("word/rootnotes.xml", notes_xml("footnotes", [para(note)]))],
    )

    assert note not in joined(extract(build_docx(pkg)))


# --- Fixture self-checks (pass before the implementation) -------------------------------------


def _zipfile_texts(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_fixture_layout_is_valid_zip() -> None:
    entries = stored_entries()

    assert _zipfile_texts(layout(entries)) == {e.name_bytes().decode(): e.data for e in entries}


@pytest.mark.parametrize("signature", [True, False], ids=["signed", "unsigned"])
def test_fixture_descriptor_archive_is_valid_zip(signature: bool) -> None:
    assert len(_zipfile_texts(_descriptor_archive(signature=signature))) == len(stored_entries())


def test_fixture_lax_reader_accepts_real_size_above_declared() -> None:
    # Python ``zipfile`` stops at the declared size: the check must be our own.
    valid = document_xml(para(CLAUSE))
    real = valid + b"<!-- " + b"x" * 5000 + b" -->"
    entry = deflated_entry("word/document.xml", real, declared_size=len(valid), crc_of=valid)

    assert _zipfile_texts(_with_doc_entry(entry))["word/document.xml"] == valid


def test_fixture_built_docx_parts_are_well_formed_xml() -> None:
    pkg = Package(body=para(CLAUSE), footnotes=[para("Note.")], headers=[para("Head.")])
    for name, data in pkg.parts():
        if name.endswith((".xml", ".rels")):
            ElementTree.fromstring(data)  # noqa: S314 - our own synthetic XML
