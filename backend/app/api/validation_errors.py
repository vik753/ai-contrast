"""Safe 422 responses for request validation errors (threat model T1, T3).

FastAPI's default 422 body echoes ``input``, ``ctx`` and ``msg``, which can hold the
provider key or contract text. Its ``loc`` can also hold client-chosen strings
(unknown JSON keys, dict keys). This handler returns only sanitized locations::

    {"error": "invalid_request", "fields": [["body", "items", "1"], ...]}

Rules for each location:

- the first part (the source: ``body``, ``header``, ``query``, ``path``, ``cookie``)
  is kept;
- a later part is kept only if it is a name declared by our code (a route parameter
  name or alias, or a field name or alias of a body model, recursively for nested
  models) or a list index (sent as a string); any other part becomes ``"*"``;
- for ``extra_forbidden`` errors the last part (the unknown key) is dropped;
- each part is cut to 64 characters.

Locations are deduplicated in order. At most 20 are returned; if there are more, a
plain ``"..."`` string is appended as the 21st entry.

Request bodies should be Pydantic models: only their field names and aliases count as
declared names. Keys inside a plain ``dict`` body are client-chosen and become ``"*"``.

Special body cases:

- malformed JSON gives ``["body", "<offset>"]``: Pydantic reports the character
  offset of the parse error as an integer, which is kept like a list index;
- a body with a non-JSON ``Content-Type`` (for example ``text/plain`` or a form) is
  not parsed as JSON for a model parameter, so the location is ``["body"]``: the error
  type is ``model_attributes_type`` for a non-empty body and ``missing`` for an empty one.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, get_args

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import AliasChoices, AliasPath, BaseModel

MAX_FIELDS = 20
MAX_PART_LENGTH = 64
OVERFLOW_MARKER = "..."
UNKNOWN_PART = "*"
SOURCES = frozenset({"body", "header", "query", "path", "cookie"})


def _alias_names(alias: object) -> Iterable[str]:
    if isinstance(alias, str):
        yield alias
    elif isinstance(alias, AliasPath):
        yield from (part for part in alias.path if isinstance(part, str))
    elif isinstance(alias, AliasChoices):
        for choice in alias.choices:
            yield from _alias_names(choice)


def _collect_from_annotation(annotation: object, names: set[str], seen: set[int]) -> None:
    """Add field names and aliases of every model reachable from ``annotation``."""
    if id(annotation) in seen:
        return
    seen.add(id(annotation))
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        for name, info in annotation.model_fields.items():
            names.add(name)
            names.update(_alias_names(info.alias))
            names.update(_alias_names(info.validation_alias))
            _collect_from_annotation(info.annotation, names, seen)
        return
    # list[X], dict[K, V], X | None, Annotated[X, ...] and other generics.
    for arg in get_args(annotation):
        _collect_from_annotation(arg, names, seen)


def declared_names(route: APIRoute) -> set[str]:
    """Names declared by our code for one route: parameters and body model fields.

    This reads ``route.dependant`` (FastAPI's ``fastapi.dependencies.models.Dependant``:
    ``path_params``, ``query_params``, ``header_params``, ``cookie_params``,
    ``body_params``, ``dependencies``). It is an internal, undocumented FastAPI API and
    may change in any FastAPI release. Guarding tests that fail if it changes:
    ``tests/test_validation_locations.py`` (path, query and nested body names stay
    visible) and this test:

    ``tests/test_hardening.py::test_declared_names_include_nested_aliases_and_dependencies``
    """
    names: set[str] = set()
    seen: set[int] = set()
    pending = [route.dependant]
    while pending:
        dependant = pending.pop()
        pending.extend(dependant.dependencies)
        for param in (
            *dependant.path_params,
            *dependant.query_params,
            *dependant.header_params,
            *dependant.cookie_params,
            *dependant.body_params,
        ):
            names.add(param.name)
            names.add(param.alias)
            _collect_from_annotation(param.field_info.annotation, names, seen)
    return names


def sanitize_location(loc: Iterable[Any], error_type: str, names: set[str]) -> list[str]:
    parts = list(loc)
    if error_type == "extra_forbidden" and parts:
        parts = parts[:-1]
    safe: list[str] = []
    for index, part in enumerate(parts):
        is_source = index == 0 and part in SOURCES
        is_index = isinstance(part, int) and not isinstance(part, bool)
        is_declared = isinstance(part, str) and part in names
        text = str(part) if is_source or is_index or is_declared else UNKNOWN_PART
        safe.append(text[:MAX_PART_LENGTH])
    return safe


def safe_fields(errors: Iterable[dict[str, Any]], names: set[str]) -> list[list[str] | str]:
    fields: list[list[str] | str] = []
    seen: set[tuple[str, ...]] = set()
    for error in errors:
        loc = sanitize_location(error.get("loc", ()), str(error.get("type", "")), names)
        key = tuple(loc)
        if key in seen:
            continue
        if len(seen) == MAX_FIELDS:
            fields.append(OVERFLOW_MARKER)
            break
        seen.add(key)
        fields.append(loc)
    return fields


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    route = request.scope.get("route")
    names = declared_names(route) if isinstance(route, APIRoute) else set()
    errors = exc.errors() if isinstance(exc, RequestValidationError) else []
    return JSONResponse(
        {"error": "invalid_request", "fields": safe_fields(errors, names)}, status_code=422
    )
