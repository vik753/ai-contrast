"""Topic catalog: models, caps and loader (ADR 0017 points 1 and 2).

The catalog is a directory of JSON files, one domain per file (``shared/topics/``). The loader
fails closed: a missing or empty directory, a file that is not valid, an unknown key, a cap
broken, a duplicate id or any text that fails the topic safety pass raises ``CatalogError``
and the app does not start. A ``CatalogError`` message names the file and the field, never
the offending text. ``catalog_version`` is the SHA-256 of the file names and contents.
"""

# ruff: noqa: TRY003, PLR0912
from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.topics.model import (
    ALL_UNITS,
    DIRECTIONS_BY_TYPE,
    ID_RE,
    MAX_SYNONYMS,
    MAX_VALUES,
    NON_CATALOG_ID_RE,
    AttributeDefinition,
    TopicDefinition,
)
from app.topics.safety import TextKind, TopicTextError, check_topic_text

__all__ = ["Catalog", "CatalogError", "load_catalog"]

LANGS: Final = ("en", "uk", "ru")
MAX_DOMAINS: Final = 16
MAX_TOPICS: Final = 30
MAX_ATTRIBUTES: Final = 12
MAX_SIDES: Final = 5
MAX_FILE_BYTES: Final = 1024 * 1024
MAX_MEMO: Final = 8

AttributeType = Literal["amount", "percentage", "duration", "enum", "categories", "text"]
# A direction: one word, or for an enum the value ids in order, best first.
Direction = str | tuple[str, ...]


class CatalogError(Exception):
    """The catalog is invalid. The message holds file names and field paths, never text."""


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Texts(_Model):
    """One text in each language."""

    en: str
    uk: str
    ru: str

    def get(self, lang: str) -> str:
        return str(getattr(self, lang))


class SynonymLists(_Model):
    en: Annotated[tuple[str, ...], Field(max_length=MAX_SYNONYMS)]
    uk: Annotated[tuple[str, ...], Field(max_length=MAX_SYNONYMS)]
    ru: Annotated[tuple[str, ...], Field(max_length=MAX_SYNONYMS)]

    def get(self, lang: str) -> tuple[str, ...]:
        return tuple(getattr(self, lang))


class Value(_Model):
    id: str
    labels: Texts


class Attribute(_Model):
    id: str
    labels: Texts
    type: AttributeType
    units: tuple[str, ...] | None = None
    values: tuple[Value, ...] | None = None
    directions: dict[str, Direction]


class Topic(_Model):
    id: str
    names: Texts
    descriptions: Texts
    synonyms: SynonymLists
    attributes: Annotated[tuple[Attribute, ...], Field(min_length=1, max_length=MAX_ATTRIBUTES)]


class Side(_Model):
    id: str
    names: Texts


def _check_attribute(attribute: Attribute, sides: set[str]) -> None:
    kind = attribute.type
    if ID_RE.fullmatch(attribute.id) is None:
        raise ValueError("bad attribute id")
    if attribute.units is not None:
        allowed = ALL_UNITS.get(kind, frozenset())
        if not attribute.units or not set(attribute.units) <= allowed:
            raise ValueError("bad units")
        if len(set(attribute.units)) != len(attribute.units):
            raise ValueError("duplicate unit")
    value_ids = [value.id for value in attribute.values or ()]
    if kind in {"enum", "categories"}:
        if not 1 <= len(value_ids) <= MAX_VALUES or len(set(value_ids)) != len(value_ids):
            raise ValueError("bad values")
        if any(ID_RE.fullmatch(v) is None for v in value_ids):
            raise ValueError("bad value id")
        for lang in LANGS:
            labels = [value.labels.get(lang) for value in attribute.values or ()]
            if len(set(labels)) != len(labels):
                raise ValueError("duplicate value label")
    elif attribute.values is not None:
        raise ValueError("values on a type without values")
    if set(attribute.directions) != sides:
        raise ValueError("directions must name every side")
    allowed_words = DIRECTIONS_BY_TYPE[kind] - {"ordered"}
    for direction in attribute.directions.values():
        if isinstance(direction, str):
            if direction not in allowed_words:
                raise ValueError("bad direction")
        elif kind != "enum" or sorted(direction) != sorted(value_ids):
            raise ValueError("bad enum order")


class Domain(_Model):
    id: str
    names: Texts
    sides: Annotated[tuple[Side, ...], Field(min_length=2, max_length=MAX_SIDES)]
    topics: Annotated[tuple[Topic, ...], Field(min_length=1, max_length=MAX_TOPICS)]

    @model_validator(mode="after")
    def _rules(self) -> Domain:
        if ID_RE.fullmatch(self.id) is None:
            raise ValueError("bad domain id")
        side_ids = [side.id for side in self.sides]
        if len(set(side_ids)) != len(side_ids) or any(ID_RE.fullmatch(s) is None for s in side_ids):
            raise ValueError("bad side ids")
        topic_ids = [topic.id for topic in self.topics]
        if (
            len(set(topic_ids)) != len(topic_ids)
            or any(ID_RE.fullmatch(t) is None for t in topic_ids)
            or any(NON_CATALOG_ID_RE.fullmatch(t) for t in topic_ids)
        ):
            raise ValueError("bad topic ids")
        for topic in self.topics:
            attribute_ids = [attribute.id for attribute in topic.attributes]
            if len(set(attribute_ids)) != len(attribute_ids):
                raise ValueError("duplicate attribute id")
            for attribute in topic.attributes:
                _check_attribute(attribute, set(side_ids))
        return self


def _definition_attribute(attribute: Attribute, side: str, lang: str) -> AttributeDefinition:
    direction = attribute.directions[side]
    labels = {value.id: value.labels.get(lang) for value in attribute.values or ()}
    order: tuple[str, ...] = ()
    if isinstance(direction, tuple):
        order = direction
        direction = "ordered"
    return AttributeDefinition(
        id=attribute.id,
        label=attribute.labels.get(lang),
        type=attribute.type,
        units=attribute.units or (),
        direction=direction,
        order=order,
        values=tuple(labels.values()),
        value_ids=tuple(labels),
        direction_source="catalog",
    )


class Catalog(_Model):
    """The whole catalog. ``model_dump(mode="json")`` is the body of ``GET /api/topics/catalog``."""

    catalog_version: str
    domains: tuple[Domain, ...]

    def definition(self, domain_id: str, topic_id: str, side: str, lang: str) -> TopicDefinition:
        """The catalog topic for one side and one UI language. Raises ``KeyError`` if unknown."""
        if lang not in LANGS:
            raise KeyError(lang)
        domain = next((d for d in self.domains if d.id == domain_id), None)
        if domain is None:
            raise KeyError(domain_id)
        topic = next((t for t in domain.topics if t.id == topic_id), None)
        if topic is None:
            raise KeyError(topic_id)
        if side not in {s.id for s in domain.sides}:
            raise KeyError(side)
        return TopicDefinition(
            origin="catalog",
            domain=domain.id,
            topic_id=topic.id,
            title=topic.names.get(lang),
            description=topic.descriptions.get(lang),
            side=side,
            attributes=tuple(_definition_attribute(a, side, lang) for a in topic.attributes),
            synonyms_en=topic.synonyms.get("en"),
            synonyms_uk=topic.synonyms.get("uk"),
            synonyms_ru=topic.synonyms.get("ru"),
        )

    def has_side(self, domain_id: str, side: str) -> bool:
        """The domain exists and has this side."""
        return any(d.id == domain_id and side in {s.id for s in d.sides} for d in self.domains)

    def matches(self, definition: TopicDefinition) -> bool:
        """The definition equals the catalog topic in one of the three languages."""
        if definition.origin != "catalog" or definition.domain is None:
            return False
        for lang in LANGS:
            try:
                expected = self.definition(
                    definition.domain, definition.topic_id, definition.side, lang
                )
            except KeyError:
                return False
            if expected == definition:
                return True
        return False


def _texts(domain: Domain) -> Iterator[tuple[str, str, TextKind, str | None]]:
    """Every text of a domain: field path, text, kind, language (synonyms only)."""
    name = TextKind.NAME
    for lang in LANGS:
        yield f"names.{lang}", domain.names.get(lang), name, None
        for side in domain.sides:
            yield f"sides.{side.id}.names.{lang}", side.names.get(lang), name, None
        for topic in domain.topics:
            base = f"topics.{topic.id}"
            yield f"{base}.names.{lang}", topic.names.get(lang), name, None
            yield (
                f"{base}.descriptions.{lang}",
                topic.descriptions.get(lang),
                (TextKind.DESCRIPTION),
                None,
            )
            for synonym in topic.synonyms.get(lang):
                yield f"{base}.synonyms.{lang}", synonym, TextKind.SYNONYM, lang
            for attribute in topic.attributes:
                at = f"{base}.attributes.{attribute.id}"
                yield f"{at}.labels.{lang}", attribute.labels.get(lang), TextKind.LABEL, None
                for value in attribute.values or ():
                    yield (
                        f"{at}.values.{value.id}.{lang}",
                        value.labels.get(lang),
                        (TextKind.VALUE),
                        None,
                    )


def _verify_texts(file: str, domain: Domain) -> None:
    for path, text, kind, lang in _texts(domain):
        try:
            check_topic_text(text, kind, lang)
        except TopicTextError as error:
            raise CatalogError(f"{file}: {path}: {error.code}") from None


def _parse(file: str, raw: bytes) -> Domain:
    try:
        data = json.loads(raw)
    except ValueError:
        raise CatalogError(f"{file}: not valid JSON") from None
    try:
        return Domain.model_validate(data)
    except ValidationError as error:
        # Only the location and the error type: the input value may be any text.
        first = error.errors(include_input=False, include_url=False, include_context=False)[0]
        where = ".".join(str(part) for part in first["loc"])
        detail = first["msg"] if first["type"] == "value_error" else first["type"]
        raise CatalogError(f"{file}: invalid ({where}: {detail})") from None


def _read_files(path: Path) -> list[tuple[str, bytes]]:
    if not path.is_dir():
        raise CatalogError("catalog directory not found")
    files = sorted(p for p in path.glob("*.json") if p.is_file())
    if not files:
        raise CatalogError("catalog directory has no domain files")
    if len(files) > MAX_DOMAINS:
        raise CatalogError("too many domain files")
    result: list[tuple[str, bytes]] = []
    for file in files:
        try:
            raw = file.read_bytes()
        except OSError:
            raise CatalogError(f"{file.name}: cannot be read") from None
        if len(raw) > MAX_FILE_BYTES:
            raise CatalogError(f"{file.name}: file too large")
        result.append((file.name, raw))
    return result


def _version(files: list[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for name, raw in files:
        for part in (name.encode("utf-8"), raw):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
    return digest.hexdigest()


# The text pass of a big catalog takes seconds; a version is verified once per process.
_VERIFIED: dict[str, Catalog] = {}
_LOCK = threading.Lock()


def load_catalog(path: Path) -> Catalog:
    """Load and verify every ``*.json`` file of the directory ``path``. Raises ``CatalogError``."""
    files = _read_files(path)
    version = _version(files)
    with _LOCK:
        known = _VERIFIED.get(version)
    if known is not None:
        return known
    domains: list[Domain] = []
    for name, raw in files:
        domain = _parse(name, raw)
        if any(domain.id == other.id for other in domains):
            raise CatalogError(f"{name}: duplicate domain id")
        _verify_texts(name, domain)
        domains.append(domain)
    catalog = Catalog(catalog_version=version, domains=tuple(sorted(domains, key=lambda d: d.id)))
    with _LOCK:
        if len(_VERIFIED) >= MAX_MEMO:
            _VERIFIED.clear()
        _VERIFIED[version] = catalog
    return catalog
