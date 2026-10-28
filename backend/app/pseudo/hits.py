"""Hit collection with the caps checked while detection runs (ADR 0015 point 1)."""

from __future__ import annotations

from typing import Final, NamedTuple

MAX_ENTITIES: Final = 5_000
MAX_SPANS: Final = 50_000

HIGH: Final = "high"
NORMAL: Final = "normal"

ORG: Final = "ORG"
PERSON: Final = "PERSON"
TAX_ID: Final = "TAX_ID"
ACCOUNT: Final = "ACCOUNT"
ADDRESS: Final = "ADDRESS"
PHONE: Final = "PHONE"
EMAIL: Final = "EMAIL"
URL: Final = "URL"
PERSONAL_DOC: Final = "PERSONAL_DOC"
DOC_NO: Final = "DOC_NO"
VEHICLE: Final = "VEHICLE"
SIGNATURE: Final = "SIGNATURE"
HEALTH: Final = "HEALTH"

# Order for ties between hits of the same length (earlier wins).
CLASS_ORDER: Final = (
    EMAIL, URL, PHONE, ACCOUNT, DOC_NO, PERSONAL_DOC, VEHICLE, TAX_ID, SIGNATURE, ADDRESS,
    HEALTH, ORG, PERSON,
)  # fmt: skip


class TooManyIdentifiersError(Exception):
    """A cap was hit; the message holds no input."""

    def __init__(self) -> None:
        super().__init__("too_many_identifiers")


class Hit(NamedTuple):
    """A match in the matching view: class, precision, ``[start, end)`` and the group key."""

    cls: str
    precision: str
    start: int
    end: int
    key: str


class Hits:
    """The hits of one document. Both caps are checked on every ``add`` (fail closed): the
    number of hits (spans) and the number of distinct (class, key) pairs (entities)."""

    def __init__(self) -> None:
        self.items: list[Hit] = []
        self._groups: set[tuple[str, str]] = set()

    def add(self, cls: str, precision: str, start: int, end: int, key: str) -> None:
        if start >= end:
            return
        if len(self.items) >= MAX_SPANS:
            raise TooManyIdentifiersError
        self._groups.add((cls, key))
        if len(self._groups) > MAX_ENTITIES:
            raise TooManyIdentifiersError
        self.items.append(Hit(cls, precision, start, end, key))
