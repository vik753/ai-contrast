"""ClientSlots: explicit acquire/release, no object whose loss leaks a slot."""

from __future__ import annotations

import pytest

from app.limits.slots import ClientSlots


def test_acquire_up_to_the_limit_then_refuse() -> None:
    slots = ClientSlots(2)

    assert [slots.try_acquire("a") for _ in range(3)] == [True, True, False]
    assert slots.try_acquire("b") is True


def test_release_frees_a_slot_and_forgets_empty_keys() -> None:
    slots = ClientSlots(1)
    slots.try_acquire("a")
    slots.release("a")

    assert slots.in_use("a") == 0
    assert slots.try_acquire("a") is True


def test_refused_acquire_holds_nothing() -> None:
    slots = ClientSlots(1)
    slots.try_acquire("a")
    slots.try_acquire("a")
    slots.release("a")

    assert slots.in_use("a") == 0


def test_release_without_slot_raises() -> None:
    with pytest.raises(RuntimeError, match=r"\S"):
        ClientSlots(1).release("a")


def test_non_positive_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"\S"):
        ClientSlots(0)
