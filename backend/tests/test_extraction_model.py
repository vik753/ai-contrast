"""S3-T1 AC3 and the stage 3 response contract: strict Pydantic models
(``extra="forbid"``) in ``app/extraction/model.py``.

The parent validates the child's JSON with these models; anything outside the
contract is rejected (-> ``extraction_failed`` in the sandbox tests).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from app.extraction.model import ExtractionError, ExtractionResult


def _valid() -> dict[str, Any]:
    return {
        "kind": "pdf",
        "bytes": 12345,
        "language": "uk",
        "pages": 3,
        "blocks": [{"text": "Clause 1.", "part": "body", "page": 1}],
        "ocr_pages": [2],
        "removed": [{"reason": "white_text", "count": 4, "sample": "hidden"}],
        "warnings": [{"code": "incremental_update", "page": 2}],
    }


def _text_kind() -> dict[str, Any]:
    return {
        "kind": "text",
        "bytes": 10,
        "language": "en",
        "pages": None,
        "blocks": [{"text": "Clause 1.", "part": "body", "page": None}],
        "ocr_pages": [],
        "removed": [],
        "warnings": [],
    }


def _invalid(data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ExtractionResult.model_validate_json(json.dumps(data))


@pytest.mark.parametrize("factory", [_valid, _text_kind], ids=["pdf", "text"])
def test_model_contract_example_validates(factory: Any) -> None:
    data = factory()

    result = ExtractionResult.model_validate_json(json.dumps(data))

    assert json.loads(result.model_dump_json()) == data


@pytest.mark.parametrize("part", ["body", "footnote", "endnote", "header", "footer", "textbox"])
def test_model_every_contract_part_accepted(part: str) -> None:
    data = _valid()
    data["blocks"][0]["part"] = part

    assert ExtractionResult.model_validate_json(json.dumps(data)).blocks[0].part == part


@pytest.mark.parametrize("language", ["uk", "ru", "en", "mixed", "unknown"])
def test_model_every_contract_language_accepted(language: str) -> None:
    data = _valid()
    data["language"] = language

    assert ExtractionResult.model_validate_json(json.dumps(data)).language == language


def test_model_extra_top_level_key_rejected() -> None:
    _invalid({**_valid(), "unexpected": 1})


@pytest.mark.parametrize("list_name", ["blocks", "removed", "warnings"])
def test_model_extra_nested_key_rejected(list_name: str) -> None:
    data = _valid()
    data[list_name][0]["unexpected"] = 1
    _invalid(data)


@pytest.mark.parametrize("key", sorted(_valid()))
def test_model_missing_key_rejected(key: str) -> None:
    data = _valid()
    del data[key]
    _invalid(data)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("kind", "html"),
        ("language", "de"),
        ("bytes", "12345"),
        ("pages", "3"),
        ("ocr_pages", ["2"]),
    ],
)
def test_model_wrong_top_level_value_rejected(key: str, value: Any) -> None:
    _invalid({**_valid(), key: value})


def test_model_unknown_part_rejected() -> None:
    data = _valid()
    data["blocks"][0]["part"] = "comment"
    _invalid(data)


def test_model_non_string_block_text_rejected() -> None:
    data = _valid()
    data["blocks"][0]["text"] = 42
    _invalid(data)


def test_model_removed_sample_at_200_characters_accepted() -> None:
    data = _valid()
    data["removed"][0]["sample"] = "x" * 200

    assert ExtractionResult.model_validate_json(json.dumps(data)).removed[0].sample == "x" * 200


def test_model_removed_sample_above_200_characters_rejected() -> None:
    data = _valid()
    data["removed"][0]["sample"] = "x" * 201
    _invalid(data)


def test_extraction_error_carries_code() -> None:
    assert ExtractionError("extraction_failed").code == "extraction_failed"
