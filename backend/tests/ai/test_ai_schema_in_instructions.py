"""S6-T2 review finding (MAJOR): the JSON schema of ``request.schema`` is in the instructions.

``build_messages`` puts ``schema.model_json_schema()`` (deterministic serialization) into the
instruction (system) message, never into a data block. The schema comes from the class, not
from a runtime string. The serialization format is free: the tests look for a JSON object
equal to the schema inside the instruction text.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import BaseModel, Field

from app.ai.port import AIRequest
from app.ai.presets import PresetId
from app.ai.prompting import build_messages
from tests.ai.helpers import first_template, make_document, make_provider, run
from tests.ai.test_ai_wire import split_prompt


class Alpha(BaseModel):
    zeta_unique_field_q9: bool = Field(description="ALPHA-DESCRIPTION-MARKER")


class Beta(BaseModel):
    omega_unique_field_k4: int


def _request(schema: type[BaseModel]) -> AIRequest:
    return AIRequest(
        template=first_template(), document=make_document(), schema=schema, max_tokens=64
    )


def _objects(text: str) -> list[Any]:
    decoder = json.JSONDecoder()
    found: list[Any] = []
    for index, char in enumerate(text):
        if char == "{":
            try:
                found.append(decoder.raw_decode(text, index)[0])
            except ValueError:
                continue
    return found


def _system(schema: type[BaseModel]) -> str:
    return build_messages(_request(schema))[0].content


def _user(schema: type[BaseModel]) -> str:
    return "\n".join(m.content for m in build_messages(_request(schema)) if m.role == "user")


@pytest.mark.parametrize("schema", [Alpha, Beta])
def test_schema_json_is_in_the_instruction_message(schema: type[BaseModel]) -> None:
    assert schema.model_json_schema() in _objects(_system(schema))


@pytest.mark.parametrize("schema", [Alpha, Beta])
def test_schema_is_never_in_a_data_block(schema: type[BaseModel]) -> None:
    user = _user(schema)

    assert next(iter(schema.model_fields)) not in user
    assert "ALPHA-DESCRIPTION-MARKER" not in user
    assert schema.model_json_schema() not in _objects(user)


def test_schema_instruction_still_starts_from_the_template_text() -> None:
    assert first_template().value in _system(Alpha)


def test_schema_change_of_the_class_changes_the_instruction() -> None:
    assert _system(Alpha) != _system(Beta)
    assert "omega_unique_field_k4" not in _system(Alpha)
    assert "zeta_unique_field_q9" not in _system(Beta)


def test_schema_serialization_is_deterministic_across_builds() -> None:
    assert _system(Alpha) == _system(Alpha)
    assert _system(Beta) == _system(Beta)


def test_schema_text_comes_from_the_class_description_not_from_the_caller() -> None:
    assert "ALPHA-DESCRIPTION-MARKER" in _system(Alpha)


def test_schema_instruction_does_not_depend_on_the_document() -> None:
    other = AIRequest(
        template=first_template(),
        document=make_document("1. Another clause text only."),
        schema=Alpha,
        max_tokens=64,
    )

    assert build_messages(other)[0].content == _system(Alpha)


@pytest.mark.parametrize("preset", [PresetId.ANTHROPIC, PresetId.OPENAI])
def test_schema_reaches_the_wire_in_the_instruction_part_only(preset: PresetId) -> None:
    provider, upstream = make_provider(preset)

    run(provider, "complete_json", _request(Alpha))
    instructions, data = split_prompt(upstream.seen[0].json)

    assert Alpha.model_json_schema() in _objects(instructions)
    assert "zeta_unique_field_q9" not in data
