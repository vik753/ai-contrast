"""Effective run formatting and hidden-text rules for DOCX (S3-T2 AC5; ADR 0009 Layer 1).

Effective formatting of a run, later layers override earlier ones:
docDefaults ``w:rPr`` → paragraph style (its ``basedOn`` chain, root first; the
default paragraph style when ``w:pStyle`` is missing or unknown) → character style
(its ``basedOn`` chain) → direct ``w:rPr``. A ``basedOn`` cycle stops at the first
style seen twice. Properties: ``w:vanish``, ``w:specVanish``, ``w:webHidden``,
``w:color``, ``w:shd``, ``w:highlight``, ``w:sz``, ``w:w``, ``w:spacing``,
``w:position``, ``w:rFonts``.

The background of a run: its highlight, else its shading, else the paragraph
shading (style chain, then direct), else the page background (``w:background``),
else white.

Rules (first match):

- ``hidden_formatting``: vanish, specVanish or webHidden on → removed;
- ``same_color``: the text colour equals the background (white text on no shading
  included; ``auto`` never matches) → removed;
- ``tiny_text``: ``w:sz`` at most 2 half-points, or ``w:w`` below 20 % → removed;
- borderline (kept, warning ``borderline_text``): ``w:sz`` at most 8 half-points,
  a colour within ``NEAR_COLOR_DELTA`` of the background in every channel, negative
  ``w:spacing`` or ``w:position``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

W: Final = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W: Final = "{" + W + "}"
VAL: Final = _W + "val"

HIDDEN_FORMATTING: Final = "hidden_formatting"
SAME_COLOR: Final = "same_color"
TINY_TEXT: Final = "tiny_text"

WHITE: Final = "FFFFFF"
AUTO: Final = "AUTO"
NONE: Final = "NONE"
MAX_TINY_SIZE: Final = 2  # half-points
MAX_BORDERLINE_SIZE: Final = 8  # half-points
MIN_SCALE_PERCENT: Final = 20
NEAR_COLOR_DELTA: Final = 32
_HEX_COLOR_LENGTH: Final = 6

_HIGHLIGHTS: Final = {
    "black": "000000",
    "blue": "0000FF",
    "cyan": "00FFFF",
    "green": "00FF00",
    "magenta": "FF00FF",
    "red": "FF0000",
    "yellow": "FFFF00",
    "white": "FFFFFF",
    "darkblue": "000080",
    "darkcyan": "008080",
    "darkgreen": "008000",
    "darkmagenta": "800080",
    "darkred": "800000",
    "darkyellow": "808000",
    "darkgray": "808080",
    "lightgray": "C0C0C0",
}
_ON: Final = frozenset({"1", "true", "on"})
_OFF: Final = frozenset({"0", "false", "off"})
_TOGGLES: Final = {
    _W + "vanish": "vanish",
    _W + "specVanish": "vanish_spec",
    _W + "webHidden": "web_hidden",
}

Props = dict[str, object]


def on_off(attrib: dict[str, str]) -> bool | None:
    value = attrib.get(VAL)
    if value is None:
        return True
    value = value.strip().casefold()
    if value in _ON:
        return True
    if value in _OFF:
        return False
    return None


def _int(value: str | None) -> int | None:
    if value is None:
        return None
    value = value.strip().removesuffix("%")
    try:
        return int(value)
    except ValueError:
        return None


def _color(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().upper()
    if value == AUTO:
        return AUTO
    if len(value) == _HEX_COLOR_LENGTH and all(c in "0123456789ABCDEF" for c in value):
        return value
    return None


def shading_fill(attrib: dict[str, str]) -> str | None:
    """The colour that a ``w:shd`` paints, or ``AUTO`` for none."""
    pattern = (attrib.get(VAL) or "").strip().casefold()
    if pattern == "nil":
        return AUTO
    if pattern == "solid":
        solid = _color(attrib.get(_W + "color"))
        if solid is not None and solid != AUTO:
            return solid
    return _color(attrib.get(_W + "fill"))


def read_run_property(tag: str, attrib: dict[str, str], props: Props) -> None:  # noqa: PLR0912
    """Record one child of ``w:rPr`` in ``props`` (unknown or invalid: ignored)."""
    toggle = _TOGGLES.get(tag)
    if toggle is not None:
        value = on_off(attrib)
        if value is not None:
            props[toggle] = value
        return
    local = tag.removeprefix(_W)
    if local == "color":
        color = _color(attrib.get(VAL))
        if color is not None:
            props["color"] = color
    elif local == "shd":
        fill = shading_fill(attrib)
        if fill is not None:
            props["shd"] = fill
    elif local == "highlight":
        name = (attrib.get(VAL) or "").strip().casefold()
        props["highlight"] = _HIGHLIGHTS.get(name, NONE)
    elif local in ("sz", "w", "spacing", "position"):
        number = _int(attrib.get(VAL))
        if number is not None:
            props[local] = number
    elif local == "rFonts":
        for key in ("ascii", "hAnsi"):
            font = attrib.get(_W + key)
            if font is not None:
                props["font_" + key] = font.strip().casefold()
    elif local == "rStyle":
        style_id = attrib.get(VAL)
        if style_id is not None:
            props["rstyle"] = style_id


@dataclass
class StyleDef:
    kind: str
    based_on: str | None = None
    rpr: Props = field(default_factory=dict)
    shading: str | None = None  # w:pPr/w:shd


@dataclass
class Styles:
    defaults: Props = field(default_factory=dict)
    default_shading: str | None = None
    default_paragraph: str | None = None
    styles: dict[str, StyleDef] = field(default_factory=dict)
    _chains: dict[tuple[str, str], tuple[Props, str | None]] = field(default_factory=dict)

    def _chain(self, style_id: str, kind: str) -> tuple[Props, str | None]:
        """Merged run properties and paragraph shading of a style chain, root first.

        Every style on the way is cached, so each style is merged once. The walk
        stops at a missing style, a style of another kind, a cached style, or the
        first style seen twice (a ``basedOn`` cycle).
        """
        path: list[tuple[str, StyleDef]] = []
        seen: set[str] = set()
        base: tuple[Props, str | None] = ({}, None)
        current: str | None = style_id
        while current is not None and current not in seen:
            cached = self._chains.get((current, kind))
            if cached is not None:
                base = cached
                break
            definition = self.styles.get(current)
            if definition is None or definition.kind != kind:
                break
            seen.add(current)
            path.append((current, definition))
            current = definition.based_on
        props, shading = base
        for current_id, definition in reversed(path):
            props = {**props, **definition.rpr}
            if definition.shading is not None:
                shading = definition.shading
            self._chains[(current_id, kind)] = (props, shading)
        return props, shading

    def paragraph_style(self, style_id: str | None) -> str | None:
        if style_id is not None:
            definition = self.styles.get(style_id)
            if definition is not None and definition.kind == "paragraph":
                return style_id
        return self.default_paragraph

    def paragraph(self, style_id: str | None) -> tuple[Props, str | None]:
        """Run properties and shading of the (resolved) paragraph style."""
        if style_id is None:
            return {}, None
        return self._chain(style_id, "paragraph")

    def table(self, style_id: str | None) -> Props:
        if style_id is None:
            return {}
        return self._chain(style_id, "table")[0]

    def character(self, style_id: str | None) -> Props:
        if style_id is None:
            return {}
        return self._chain(style_id, "character")[0]


@dataclass(frozen=True)
class Verdict:
    reason: str | None
    borderline: bool
    wingdings: bool


def _near(first: str, second: str) -> bool:
    return all(
        abs(int(first[i : i + 2], 16) - int(second[i : i + 2], 16)) <= NEAR_COLOR_DELTA
        for i in range(0, _HEX_COLOR_LENGTH, 2)
    )


def _background(props: Props, paragraph_shading: str | None, page: str) -> str:
    highlight = props.get("highlight")
    if isinstance(highlight, str) and highlight != NONE:
        return highlight
    for fill in (props.get("shd"), paragraph_shading):
        if isinstance(fill, str) and fill != AUTO:
            return fill
    return page


def judge(props: Props, paragraph_shading: str | None, page: str) -> Verdict:
    """Apply the rules of this module to effective run properties."""
    fonts = (props.get("font_ascii"), props.get("font_hAnsi"))
    wingdings = "wingdings" in fonts
    if props.get("vanish") or props.get("vanish_spec") or props.get("web_hidden"):
        return Verdict(HIDDEN_FORMATTING, borderline=False, wingdings=wingdings)
    color = props.get("color")
    background = _background(props, paragraph_shading, page)
    has_color = isinstance(color, str) and color != AUTO
    if has_color and color == background:
        return Verdict(SAME_COLOR, borderline=False, wingdings=wingdings)
    size = props.get("sz")
    scale = props.get("w")
    if (isinstance(size, int) and size <= MAX_TINY_SIZE) or (
        isinstance(scale, int) and scale < MIN_SCALE_PERCENT
    ):
        return Verdict(TINY_TEXT, borderline=False, wingdings=wingdings)
    spacing = props.get("spacing")
    position = props.get("position")
    borderline = (
        (isinstance(size, int) and size <= MAX_BORDERLINE_SIZE)
        or (isinstance(color, str) and has_color and _near(color, background))
        or (isinstance(spacing, int) and spacing < 0)
        or (isinstance(position, int) and position < 0)
    )
    return Verdict(None, borderline=borderline, wingdings=wingdings)
