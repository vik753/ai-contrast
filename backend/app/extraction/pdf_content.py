"""Content that pdfminer does not interpret (S3-T3 review round 1, items 1 and 6).

Runs inside the parsing child (ADR 0011).

- ``OptionalContent``: the default configuration (``/OCProperties /D``) of the
  catalog. An optional content group is *off* when it is in ``/OFF`` or the base
  state is ``OFF`` and it is not in ``/ON``. A membership dictionary (``OCMD``)
  is evaluated with ``/P`` (``AnyOn`` default); a visibility expression
  (``/VE``) or anything else we cannot resolve counts as *off* (fail closed: the
  text is then kept with ``borderline_text``, never removed).
- ``tiling_runs_text``: a tiling pattern whose cell shows text (``BT``) or runs a
  Form XObject. pdfminer never runs pattern cells, so that text is not read
  (material ``not_read_pattern``).
"""

from __future__ import annotations

import re
from typing import Final

from pdfminer.pdftypes import PDFObjRef, PDFStream, resolve1
from pdfminer.psparser import PSLiteral, literal_name

MAX_OC_GROUPS: Final = 10_000
# A text object or an XObject call in a content stream (tokens, not inside names).
_TEXT_OPERATOR: Final = re.compile(rb"(?<![A-Za-z0-9/])BT(?![A-Za-z0-9])")
_DO_OPERATOR: Final = re.compile(rb"/([^\s/\[\]<>(){}%]+)\s+Do(?![A-Za-z0-9])")


def _ids(value: object) -> set[int]:
    items = resolve1(value)
    if not isinstance(items, list):
        return set()
    return {item.objid for item in items[:MAX_OC_GROUPS] if isinstance(item, PDFObjRef)}


class OptionalContent:
    """Which optional content groups are off in the default configuration."""

    def __init__(self, catalog: dict[str, object]) -> None:
        props = resolve1(catalog.get("OCProperties"))
        config = resolve1(props.get("D")) if isinstance(props, dict) else None
        config = config if isinstance(config, dict) else {}
        base = resolve1(config.get("BaseState"))
        self._base_off = isinstance(base, PSLiteral) and literal_name(base) == "OFF"
        self._on = _ids(config.get("ON"))
        self._off = _ids(config.get("OFF"))

    def _group_off(self, ref: object) -> bool:
        if not isinstance(ref, PDFObjRef):
            return True  # a direct group cannot be named in /ON or /OFF
        if ref.objid in self._off:
            return True
        return self._base_off and ref.objid not in self._on

    def is_off(self, ref: object) -> bool:
        """``ref`` is an OCG or OCMD reference (or a direct dictionary)."""
        spec = resolve1(ref)
        if not isinstance(spec, dict):
            return True
        kind = resolve1(spec.get("Type"))
        kind_name = literal_name(kind) if isinstance(kind, PSLiteral) else ""
        if kind_name == "OCG":
            return self._group_off(ref)
        if kind_name != "OCMD" or "VE" in spec:
            return True
        groups = resolve1(spec.get("OCGs"))
        refs = groups if isinstance(groups, list) else [spec.get("OCGs")]
        offs = [self._group_off(item) for item in refs[:MAX_OC_GROUPS]]
        if not offs:
            return False  # no groups: the membership has no effect
        policy = resolve1(spec.get("P"))
        name = literal_name(policy) if isinstance(policy, PSLiteral) else "AnyOn"
        visible = {
            "AnyOn": not all(offs),
            "AllOn": not any(offs),
            "AnyOff": any(offs),
            "AllOff": all(offs),
        }.get(name)
        return visible is not True


def tiling_runs_text(pattern: object) -> bool:
    """``pattern`` is a tiling pattern whose cell shows text or runs a Form XObject."""
    stream = resolve1(pattern)
    if not isinstance(stream, PDFStream):
        return False
    kind = resolve1(stream.get("PatternType"))
    if kind != 1:
        return False
    data = stream.get_data()
    if _TEXT_OPERATOR.search(data):
        return True
    resources = resolve1(stream.get("Resources"))
    xobjects = resolve1(resources.get("XObject")) if isinstance(resources, dict) else None
    for match in _DO_OPERATOR.finditer(data):
        xobject = (
            resolve1(xobjects.get(match.group(1).decode("latin-1")))
            if isinstance(xobjects, dict)
            else None
        )
        subtype = resolve1(xobject.get("Subtype")) if isinstance(xobject, PDFStream) else None
        if not (isinstance(subtype, PSLiteral) and literal_name(subtype) == "Image"):
            return True  # a form, or an XObject we cannot resolve
    return False
