"""S5b-T2 AC1: the type gate (``app.pseudo.gate``) and ``safety_pass``.

Assumed interface: ``PseudonymizedDocument`` (``.clauses``: tuple of
``PseudonymizedClause`` with ``.id`` and ``.text``), ``PseudonymizedText``,
``ConfirmedTopic``, ``safety_pass(untrusted) -> PseudonymizedDocument`` and
``SafetyError`` with ``.code`` and ``.spans``. The gate classes are frozen
slotted dataclasses; the sentinel is an ``InitVar`` without default.

Expected to fail until ``app/pseudo/gate.py`` exists (S5b-T2 not implemented).
"""

from __future__ import annotations

import copy
import dataclasses
import enum
import importlib
import pickle
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.safety_helpers import detector_version, doc, find_untrusted_model

gate: Any = importlib.import_module("app.pseudo.gate")
Make = Callable[..., TestClient]
GATE_NAMES = ("PseudonymizedDocument", "PseudonymizedClause", "PseudonymizedText", "ConfirmedTopic")


def _untrusted(client: TestClient, *texts: str, **kw: Any) -> Any:
    return find_untrusted_model().model_validate(doc(detector_version(client), *texts, **kw))


@pytest.fixture
def passed(make_client: Make) -> Any:
    client = make_client()
    return gate.safety_pass(_untrusted(client, "1. [A.ORG_1] pays.", "2. Second clause."))


def test_gate_module_exports_the_four_types_and_the_entry_points() -> None:
    for name in (*GATE_NAMES, "safety_pass", "SafetyError"):
        assert hasattr(gate, name), name


# --- safety_pass ---------------------------------------------------------------------------


def test_safety_pass_returns_a_document_with_the_input_texts_unchanged(passed: Any) -> None:
    assert isinstance(passed, gate.PseudonymizedDocument)
    assert [c.text for c in passed.clauses] == ["1. [A.ORG_1] pays.", "2. Second clause."]
    assert [c.id for c in passed.clauses] == ["c1", "c2"]


def test_safety_pass_clauses_are_a_tuple_of_gate_clauses(passed: Any) -> None:
    assert isinstance(passed.clauses, tuple)
    assert all(isinstance(c, gate.PseudonymizedClause) for c in passed.clauses)


def test_safety_pass_wrong_version_raises_safety_error_with_code(make_client: Make) -> None:
    client = make_client()
    untrusted = find_untrusted_model().model_validate(doc("old", "1. Pay."))

    with pytest.raises(gate.SafetyError) as raised:
        gate.safety_pass(untrusted)

    assert raised.value.code == "detector_version_mismatch"
    assert not raised.value.spans
    assert client


def test_safety_pass_leftover_email_raises_with_clause_relative_span(make_client: Make) -> None:
    client = make_client()
    text = "2. Write to ivan.testov@example.com please."

    with pytest.raises(gate.SafetyError) as raised:
        gate.safety_pass(_untrusted(client, "1. Pay.", text))

    assert raised.value.code == "unmasked_identifier"
    spans = [tuple(s) for s in raised.value.spans]
    assert len(spans) == 1
    clause_id, start, end = spans[0]
    assert clause_id == "c2"
    assert text[start:end] == "ivan.testov@example.com"


def test_safety_pass_invalid_placeholder_raises_with_code(make_client: Make) -> None:
    client = make_client()

    with pytest.raises(gate.SafetyError) as raised:
        gate.safety_pass(_untrusted(client, "Pay [A.ORG_3]."))

    assert raised.value.code == "invalid_placeholder"


def test_safety_error_string_holds_no_text(make_client: Make) -> None:
    client = make_client()
    text = "Write to ivan.testov@example.com please."

    with pytest.raises(gate.SafetyError) as raised:
        gate.safety_pass(_untrusted(client, text))

    assert "ivan.testov" not in str(raised.value)
    assert "ivan.testov" not in repr(raised.value)


# --- hardening ---------------------------------------------------------------------------------


def _all_instances(passed: Any) -> list[Any]:
    return [passed, passed.clauses[0]]


@pytest.mark.parametrize("which", [0, 1], ids=["document", "clause"])
def test_gate_dataclasses_replace_fails(passed: Any, which: int) -> None:
    with pytest.raises(Exception):  # noqa: B017, PT011
        dataclasses.replace(_all_instances(passed)[which])


@pytest.mark.parametrize("which", [0, 1], ids=["document", "clause"])
def test_gate_copy_copy_fails(passed: Any, which: int) -> None:
    with pytest.raises(Exception):  # noqa: B017, PT011
        copy.copy(_all_instances(passed)[which])


@pytest.mark.parametrize("which", [0, 1], ids=["document", "clause"])
def test_gate_copy_deepcopy_fails(passed: Any, which: int) -> None:
    with pytest.raises(Exception):  # noqa: B017, PT011
        copy.deepcopy(_all_instances(passed)[which])


@pytest.mark.parametrize("protocol", range(pickle.HIGHEST_PROTOCOL + 1))
@pytest.mark.parametrize("which", [0, 1], ids=["document", "clause"])
def test_gate_pickle_dumps_fails_for_every_protocol(passed: Any, which: int, protocol: int) -> None:
    with pytest.raises(Exception):  # noqa: B017, PT011
        pickle.dumps(_all_instances(passed)[which], protocol=protocol)


@pytest.mark.parametrize("method", ["__copy__", "__reduce__", "__reduce_ex__"])
def test_gate_instance_reduce_and_copy_methods_raise(passed: Any, method: str) -> None:
    args: tuple[Any, ...] = (2,) if method == "__reduce_ex__" else ()
    with pytest.raises(Exception):  # noqa: B017, PT011
        getattr(passed, method)(*args)


def test_gate_instance_deepcopy_method_raises(passed: Any) -> None:
    with pytest.raises(Exception):  # noqa: B017, PT011
        passed.__deepcopy__({})


@pytest.mark.parametrize("name", GATE_NAMES)
def test_gate_type_is_frozen_slotted_dataclass_with_own_copy_guards(name: str) -> None:
    cls: Any = getattr(gate, name)

    assert dataclasses.is_dataclass(cls)
    assert cls.__dict__["__dataclass_params__"].frozen is True
    assert "__slots__" in cls.__dict__
    for method in ("__copy__", "__deepcopy__", "__reduce__", "__reduce_ex__"):
        assert method in cls.__dict__, method


@pytest.mark.parametrize("name", GATE_NAMES)
def test_gate_type_has_initvar_sentinel_without_default(name: str) -> None:
    cls = getattr(gate, name)

    initvars = [
        f
        for f in cls.__dataclass_fields__.values()
        if f._field_type is dataclasses._FIELD_INITVAR  # type: ignore[attr-defined]
    ]
    assert len(initvars) >= 1
    assert all(
        f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
        for f in initvars
    )


def _plausible_kwargs(cls: type) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    for f in cls.__dataclass_fields__.values():  # type: ignore[attr-defined]
        if f._field_type is dataclasses._FIELD:  # type: ignore[attr-defined]
            kwargs[f.name] = ()
    return kwargs


@pytest.mark.parametrize("name", GATE_NAMES)
def test_gate_construction_without_sentinel_fails(name: str) -> None:
    cls = getattr(gate, name)

    with pytest.raises(TypeError):
        cls(**_plausible_kwargs(cls))


@pytest.mark.parametrize("name", GATE_NAMES)
def test_gate_construction_with_a_wrong_sentinel_fails(name: str) -> None:
    cls = getattr(gate, name)
    kwargs = _plausible_kwargs(cls)
    for f in cls.__dataclass_fields__.values():
        if f._field_type is dataclasses._FIELD_INITVAR:  # type: ignore[attr-defined]
            for wrong in (object(), None, True, 0, "sentinel"):
                with pytest.raises(Exception):  # noqa: B017, PT011
                    cls(**{**kwargs, f.name: wrong})


@pytest.mark.parametrize("which", [0, 1], ids=["document", "clause"])
def test_gate_fields_cannot_be_assigned(passed: Any, which: int) -> None:
    obj = _all_instances(passed)[which]

    with pytest.raises(dataclasses.FrozenInstanceError):
        obj.text = "other"
    with pytest.raises(dataclasses.FrozenInstanceError):
        obj.clauses = ()


def test_gate_instance_has_no_dict_and_accepts_no_new_attribute(passed: Any) -> None:
    assert not hasattr(passed, "__dict__")
    with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
        passed.extra = 1


def test_gate_document_fields_are_immutable_values(passed: Any) -> None:
    allowed = (
        str,
        int,
        bool,
        float,
        tuple,
        enum.Enum,
        type(None),
        *(getattr(gate, n) for n in GATE_NAMES),
    )
    for obj in (passed, *passed.clauses):
        for f in dataclasses.fields(obj):
            value = getattr(obj, f.name)
            assert isinstance(value, allowed), (f.name, type(value))
            assert not isinstance(value, (list, dict, set, bytearray)), f.name
            if isinstance(value, tuple):
                assert all(
                    isinstance(v, (str, int, *(getattr(gate, n) for n in GATE_NAMES)))
                    for v in value
                )


def test_gate_clauses_inside_a_document_are_frozen_gate_objects(passed: Any) -> None:
    for clause in passed.clauses:
        with pytest.raises(dataclasses.FrozenInstanceError):
            clause.text = "x"


def test_gate_two_passes_of_equal_input_give_equal_documents(make_client: Make) -> None:
    client = make_client()

    first = gate.safety_pass(_untrusted(client, "Pay."))
    second = gate.safety_pass(_untrusted(client, "Pay."))

    assert [c.text for c in first.clauses] == [c.text for c in second.clauses]
