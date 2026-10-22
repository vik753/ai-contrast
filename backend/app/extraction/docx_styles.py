"""Effective run formatting and hidden-text rules for DOCX (S3-T2 AC5, review rounds 0
and 1; ADR 0009 Layer 1).

Principle: text is removed only when its invisibility is resolved exactly. When an
input cannot be resolved (a theme colour without a theme part, an unknown colour
name, a tint or shade that needs rounding, a shading pattern, a table style with
conditional formatting), the text is kept and flagged ``borderline_text``.

Effective formatting of a run, later layers override earlier ones: docDefaults →
table style → paragraph style (the default paragraph style when ``w:pStyle`` is
missing or unknown) → character style → direct ``w:rPr``. Each style is resolved
through its ``basedOn`` chain (root first; a cycle stops at the first style seen
twice). ``w:vanish`` is a toggle property (ECMA-376 17.7.3): the style layers are
XORed, direct formatting sets the value.

Text colour: ``w:themeColor`` (through the theme part, ``w:clrSchemeMapping``,
``w:themeTint`` and ``w:themeShade``) wins over ``w:val``; ``auto`` never matches.
Background, first layer that paints: highlight → run shading → paragraph shading
→ table cell shading → table shading → table style → page background (only with
``w:displayBackgroundShape``) → white.

Rules (first match):

- ``hidden_formatting``: ``w:vanish`` or ``w:specVanish`` → removed (``w:webHidden``
  is visible in print layout and is not removed);
- ``same_color``: the text colour equals the background, both resolved exactly →
  removed;
- ``tiny_text``: the font size (``w:szCs`` for runs with ``w:cs`` or ``w:rtl``,
  else ``w:sz``) at most 2 half-points, or ``w:w`` below 20 % → removed;
- borderline (kept, warning ``borderline_text``): size at most 8 half-points, a
  colour within ``NEAR_COLOR_DELTA`` of the background in every channel, negative
  ``w:spacing`` or ``w:position``, or any unresolved input above.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Final
from xml.etree.ElementTree import Element

from app.extraction.docx_xml import END, START

W: Final = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W: Final = "{" + W + "}"
VAL: Final = _W + "val"
A_NS: Final = "http://schemas.openxmlformats.org/drawingml/2006/main"

HIDDEN_FORMATTING: Final = "hidden_formatting"
SAME_COLOR: Final = "same_color"
TINY_TEXT: Final = "tiny_text"

WHITE: Final = "FFFFFF"
BLACK: Final = "000000"
AUTO: Final = "AUTO"
NONE: Final = "NONE"
MAX_TINY_SIZE: Final = 2  # half-points
MAX_BORDERLINE_SIZE: Final = 8  # half-points
MIN_SCALE_PERCENT: Final = 20
NEAR_COLOR_DELTA: Final = 32
_HEX_COLOR_LENGTH: Final = 6
_FULL: Final = 0xFF

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
_FLAGS: Final = {
    _W + "vanish": "vanish",
    _W + "specVanish": "vanish_spec",
    _W + "cs": "cs",
    _W + "rtl": "rtl",
}
# Half-points per unit (ST_HpsMeasure and the universal measure).
_HALF_POINTS: Final = {"pt": 2.0, "in": 144.0, "cm": 144 / 2.54, "mm": 14.4 / 2.54, "pc": 24.0}
_MEASURE: Final = re.compile(r"\s*([-+]?\d+(?:\.\d+)?)\s*(pt|in|cm|mm|pc|pi|%)?\s*")

# Theme colour names (ST_ThemeColor) → colour scheme elements, through the mapping.
_MAPPED: Final = {"background1": "bg1", "text1": "t1", "background2": "bg2", "text2": "t2"}
_SCHEME: Final = {
    "dark1": "dk1",
    "light1": "lt1",
    "dark2": "dk2",
    "light2": "lt2",
    **{f"accent{i}": f"accent{i}" for i in range(1, 7)},
    "hyperlink": "hlink",
    "followedHyperlink": "folHlink",
}
STANDARD_MAPPING: Final = {
    "bg1": "light1",
    "t1": "dark1",
    "bg2": "light2",
    "t2": "dark2",
    **{f"accent{i}": f"accent{i}" for i in range(1, 7)},
    "hyperlink": "hyperlink",
    "followedHyperlink": "followedHyperlink",
}

Props = dict[str, object]
# Raw colour attributes: (value, theme colour, tint, shade).
ColorSpec = tuple[str | None, str | None, str | None, str | None]
# Raw shading attributes: (pattern, colour spec of the pattern, fill spec).
ShadeSpec = tuple[str, ColorSpec, ColorSpec]


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


def measure(value: str | None, *, half_points: bool = False) -> float | None:
    """A number with an optional unit. ``half_points``: converted to half-points."""
    if value is None:
        return None
    match = _MEASURE.fullmatch(value)
    if match is None:
        return None
    number = float(match.group(1))
    unit = match.group(2)
    if unit is None and half_points and "." in match.group(1):
        # A size without a unit is an integer number of half-points: unresolved.
        return math.nan
    if unit is None or unit == "%":
        return number
    if not half_points:
        return number
    return number * _HALF_POINTS["pc" if unit == "pi" else unit]


def hex_color(value: str | None) -> str | None:
    """``RRGGBB`` upper case, ``AUTO``, or ``None`` for anything else."""
    if value is None:
        return None
    value = value.strip().upper()
    if value == AUTO:
        return AUTO
    if len(value) == _HEX_COLOR_LENGTH and all(c in "0123456789ABCDEF" for c in value):
        return value
    return None


def color_spec(attrib: dict[str, str], prefix: str = "") -> ColorSpec:
    """``w:color`` attributes, or the ``w:themeFill*`` group of ``w:shd``."""
    if prefix == "fill":
        return (
            attrib.get(_W + "fill"),
            attrib.get(_W + "themeFill"),
            attrib.get(_W + "themeFillTint"),
            attrib.get(_W + "themeFillShade"),
        )
    return (
        attrib.get(VAL if not prefix else _W + "color"),
        attrib.get(_W + "themeColor"),
        attrib.get(_W + "themeTint"),
        attrib.get(_W + "themeShade"),
    )


def shade_spec(attrib: dict[str, str]) -> ShadeSpec:
    pattern = (attrib.get(VAL) or "clear").strip().casefold()
    return pattern, color_spec(attrib, "pattern"), color_spec(attrib, "fill")


def read_run_property(tag: str, attrib: dict[str, str], props: Props) -> None:  # noqa: PLR0912
    """Record one child of ``w:rPr`` in ``props`` (unknown or invalid: ignored)."""
    flag = _FLAGS.get(tag)
    if flag is not None:
        value = on_off(attrib)
        if value is not None:
            props[flag] = value
        return
    local = tag.removeprefix(_W)
    if local == "color":
        props["color"] = color_spec(attrib)
    elif local == "shd":
        props["shd"] = shade_spec(attrib)
    elif local == "highlight":
        name = (attrib.get(VAL) or "").strip().casefold()
        props["highlight"] = _HIGHLIGHTS.get(name, NONE)
    elif local in ("sz", "szCs"):
        size = measure(attrib.get(VAL), half_points=True)
        if size is not None:
            props[local] = size
    elif local in ("w", "spacing", "position"):
        number = measure(attrib.get(VAL))
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


# --- Theme ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Color:
    """A resolved colour: ``hex`` is ``RRGGBB``, ``AUTO`` or ``None`` (unresolved);
    ``exact`` is false when rounding was needed."""

    hex: str | None
    exact: bool = True


UNRESOLVED: Final = Color(None, exact=False)


@dataclass
class Theme:
    scheme: dict[str, Color] = field(default_factory=dict)  # "dk1" → colour
    mapping: dict[str, str] = field(default_factory=lambda: dict(STANDARD_MAPPING))
    present: bool = False

    def resolve(self, spec: ColorSpec) -> Color | None:
        """The colour of a spec; ``None`` when the spec sets no colour."""
        value, theme_name, tint, shade = spec
        if theme_name is not None and theme_name.strip() not in ("", "none"):
            return self._theme_color(theme_name.strip(), tint, shade)
        color = hex_color(value)
        return None if color is None else Color(color)

    def _theme_color(self, name: str, tint: str | None, shade: str | None) -> Color:
        if not self.present:
            return UNRESOLVED
        mapped = (
            self.mapping.get(_MAPPED[name]) if name in _MAPPED else self.mapping.get(name, name)
        )
        color = self.scheme.get(_SCHEME.get(mapped or "", ""))
        if color is None:
            return UNRESOLVED
        for value, toward in ((tint, WHITE), (shade, BLACK)):
            color = _modulate(color, value, toward)
        return color


def _modulate(color: Color, value: str | None, toward: str) -> Color:
    """Tint (toward white) or shade (toward black). ``00`` and ``FF`` are exact;
    other values approximate Word's rounding."""
    if value is None or color.hex is None:
        return color
    try:
        amount = int(value, 16)
    except ValueError:
        return UNRESOLVED
    if amount == _FULL:
        return color
    if amount == 0:
        return Color(toward, exact=color.exact)
    channels = [int(color.hex[i : i + 2], 16) for i in range(0, 6, 2)]
    if toward == WHITE:
        mixed = [round(_FULL - (_FULL - c) * amount / _FULL) for c in channels]
    else:
        mixed = [round(c * amount / _FULL) for c in channels]
    return Color("".join(f"{c:02X}" for c in mixed), exact=False)


_SYSTEM_COLORS: Final = {"window": WHITE, "windowtext": BLACK}


def _scheme_color(tag: str, item: Element) -> Color | None:
    """``a:srgbClr`` (exact) or ``a:sysClr``: ``window`` and ``windowText`` are white
    and black; a ``lastClr`` that disagrees, or another system colour (only its
    ``lastClr`` cache is known), is not exact."""
    if tag.endswith("}srgbClr"):
        value = hex_color(item.get("val"))
        return Color(value) if value is not None and value != AUTO else None
    last = hex_color(item.get("lastClr"))
    system = _SYSTEM_COLORS.get((item.get("val") or "").strip().casefold())
    if system is not None:
        return Color(system, exact=last in (None, system))
    return Color(last, exact=False) if last is not None and last != AUTO else UNRESOLVED


def parse_theme(events: Iterator[tuple[str, Any]]) -> dict[str, Color]:
    """The colour scheme of a theme part: ``dk1`` … ``folHlink`` → a colour."""
    scheme: dict[str, Color] = {}
    current: str | None = None
    in_scheme = False
    a = "{" + A_NS + "}"
    for event, item in events:
        if event == START:
            tag = item.tag
            if tag == a + "clrScheme":
                in_scheme = True
            elif in_scheme and current is None and tag.startswith(a):
                current = tag.removeprefix(a)
            elif current is not None and tag in (a + "srgbClr", a + "sysClr"):
                value = _scheme_color(tag, item)
                if value is not None:
                    scheme.setdefault(current, value)
        elif event == END:
            tag = item.tag
            if tag == a + "clrScheme":
                in_scheme = False
            elif current is not None and tag == a + current:
                current = None
    return scheme


# --- Styles ---------------------------------------------------------------------------------


@dataclass
class StyleDef:
    kind: str
    based_on: str | None = None
    rpr: Props = field(default_factory=dict)
    shading: ShadeSpec | None = None  # w:pPr/w:shd
    cell_shading: ShadeSpec | None = None  # table styles: w:tcPr/w:shd
    table_shading: ShadeSpec | None = None  # table styles: w:tblPr/w:shd
    conditional: bool = False  # table styles: w:tblStylePr
    conditional_fills: list[ShadeSpec] = field(default_factory=list)


@dataclass(frozen=True)
class Resolved:
    """A style chain merged root first."""

    rpr: Props
    shading: ShadeSpec | None = None
    cell_shading: ShadeSpec | None = None
    table_shading: ShadeSpec | None = None
    conditional: bool = False
    conditional_fills: tuple[ShadeSpec, ...] = ()


EMPTY: Final = Resolved({})


@dataclass
class Styles:
    defaults: Props = field(default_factory=dict)
    default_shading: ShadeSpec | None = None
    default_paragraph: str | None = None
    default_table: str | None = None
    styles: dict[str, StyleDef] = field(default_factory=dict)
    _chains: dict[tuple[str, str], Resolved] = field(default_factory=dict)

    def chain(self, style_id: str | None, kind: str) -> Resolved:
        """A style chain merged root first. Every style on the way is cached, so each
        style is merged once. The walk stops at a missing style, a style of another
        kind, a cached style, or the first style seen twice (a ``basedOn`` cycle)."""
        if style_id is None:
            return EMPTY
        path: list[tuple[str, StyleDef]] = []
        seen: set[str] = set()
        base = EMPTY
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
        merged = base
        for current_id, definition in reversed(path):
            merged = Resolved(
                rpr={**merged.rpr, **definition.rpr},
                shading=definition.shading or merged.shading,
                cell_shading=definition.cell_shading or merged.cell_shading,
                table_shading=definition.table_shading or merged.table_shading,
                conditional=merged.conditional or definition.conditional,
                conditional_fills=merged.conditional_fills + tuple(definition.conditional_fills),
            )
            self._chains[(current_id, kind)] = merged
        return merged

    def paragraph_style(self, style_id: str | None) -> str | None:
        if style_id is not None:
            definition = self.styles.get(style_id)
            if definition is not None and definition.kind == "paragraph":
                return style_id
        return self.default_paragraph

    def table_style(self, style_id: str | None) -> str | None:
        if style_id is not None:
            definition = self.styles.get(style_id)
            if definition is not None and definition.kind == "table":
                return style_id
        return self.default_table


def _default_flag(item: Element) -> bool:
    value = item.get(_W + "default")
    return value is not None and bool(on_off({VAL: value}))


def parse_styles(events: Iterator[tuple[str, Any]]) -> Styles:  # noqa: PLR0912 - one branch per element
    """``styles.xml``: docDefaults, styles with ``basedOn``, ``rPr``, ``pPr/shd`` and,
    for table styles, ``tcPr/shd``, ``tblPr/shd`` and conditional formatting."""
    styles = Styles()
    stack: list[str] = []
    current: StyleDef | None = None
    current_id: str | None = None
    for event, item in events:
        if event == START:
            stack.append(item.tag)
            depth = len(stack)
            tag = item.tag
            parent = stack[-2] if depth > 1 else ""
            if depth == 2 and tag == _W + "style":  # noqa: PLR2004 - w:styles/w:style
                current = StyleDef(kind=item.get(_W + "type") or "paragraph")
                current_id = item.get(_W + "styleId")
                if current_id is not None and _default_flag(item):
                    if current.kind == "paragraph" and styles.default_paragraph is None:
                        styles.default_paragraph = current_id
                    elif current.kind == "table" and styles.default_table is None:
                        styles.default_table = current_id
            elif current is not None and depth >= 3:  # noqa: PLR2004 - inside w:style
                _style_element(current, stack, tag, item.attrib)
            elif depth == 5 and stack[1] == _W + "docDefaults":  # noqa: PLR2004 - */rPr/*
                if parent == _W + "rPr":
                    read_run_property(tag, item.attrib, styles.defaults)
                elif parent == _W + "pPr" and tag == _W + "shd":
                    styles.default_shading = shade_spec(item.attrib)
        elif event == END:
            if len(stack) == 2 and current is not None:  # noqa: PLR2004
                if current_id is not None:
                    styles.styles.setdefault(current_id, current)
                current = None
            stack.pop()
    return styles


def _style_element(style: StyleDef, stack: list[str], tag: str, attrib: dict[str, str]) -> None:
    depth = len(stack)
    parent = stack[-2]
    if _W + "tblStylePr" in stack:
        style.conditional = True
        if tag == _W + "shd":
            style.conditional_fills.append(shade_spec(attrib))
        return
    if depth == 3 and tag == _W + "basedOn":  # noqa: PLR2004
        style.based_on = attrib.get(VAL)
    elif depth == 4 and parent == _W + "rPr":  # noqa: PLR2004
        read_run_property(tag, attrib, style.rpr)
    elif depth == 4 and tag == _W + "shd":  # noqa: PLR2004
        if parent == _W + "pPr":
            style.shading = shade_spec(attrib)
        elif parent == _W + "tcPr":
            style.cell_shading = shade_spec(attrib)
        elif parent == _W + "tblPr":
            style.table_shading = shade_spec(attrib)


# --- Verdict ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    reason: str | None
    borderline: bool
    font: str  # "wingdings", "symbol" or ""


@dataclass(frozen=True)
class Background:
    """The layers under a run, top first, as raw shading specs (``None``: unset)."""

    layers: tuple[ShadeSpec | None, ...]
    conditional: bool
    conditional_fills: tuple[ShadeSpec, ...]


def _near(first: str, second: str) -> bool:
    return all(
        abs(int(first[i : i + 2], 16) - int(second[i : i + 2], 16)) <= NEAR_COLOR_DELTA
        for i in range(0, _HEX_COLOR_LENGTH, 2)
    )


def _shade_color(spec: ShadeSpec, theme: Theme) -> Color | None:
    """The colour a shading paints; ``None`` when it paints nothing."""
    pattern, pattern_color, fill = spec
    if pattern == "nil":
        return None
    if pattern not in ("clear", "solid"):
        # A pattern mixes the pattern colour (``w:color``, ``auto`` included) and the
        # fill: not resolved.
        return UNRESOLVED
    if pattern == "solid":
        solid = theme.resolve(pattern_color)
        if solid is not None and solid.hex != AUTO:
            return solid
    painted = theme.resolve(fill)
    if painted is None or painted.hex == AUTO:
        return None
    return painted


def _background(props: Props, background: Background, theme: Theme, page: Color) -> Color:
    highlight = props.get("highlight")
    if isinstance(highlight, str) and highlight != NONE:
        return Color(highlight)
    run_shading = props.get("shd")
    layers = (run_shading if isinstance(run_shading, tuple) else None, *background.layers)
    for layer in layers:
        if layer is None:
            continue
        color = _shade_color(layer, theme)
        if color is not None:
            return color
    return page


def _color_rule(
    props: Props, background: Background, theme: Theme, page: Color
) -> tuple[bool, bool]:
    """(same colour resolved exactly, borderline)."""
    spec = props.get("color")
    color = theme.resolve(spec) if isinstance(spec, tuple) else None
    if color is None or color.hex == AUTO:
        return False, False
    text = color.hex
    if text is None:
        return False, True  # an unresolved text colour: kept
    borderline = any(
        painted is not None and (painted.hex is None or _near(text, painted.hex))
        for painted in (_shade_color(fill, theme) for fill in background.conditional_fills)
    )
    painted_under = _background(props, background, theme, page)
    under = painted_under.hex
    if under is None:
        return False, True
    if text == under:
        if color.exact and painted_under.exact and not background.conditional:
            return True, False
        return False, True
    return False, borderline or _near(text, under)


def judge(props: Props, background: Background, theme: Theme, page: Color) -> Verdict:
    """Apply the rules of this module to effective run properties."""
    fonts = (props.get("font_ascii"), props.get("font_hAnsi"))
    font = "wingdings" if "wingdings" in fonts else "symbol" if "symbol" in fonts else ""
    if props.get("vanish") or props.get("vanish_spec"):
        return Verdict(HIDDEN_FORMATTING, borderline=False, font=font)
    same, borderline = _color_rule(props, background, theme, page)
    if same:
        return Verdict(SAME_COLOR, borderline=False, font=font)
    complex_script = bool(props.get("cs") or props.get("rtl"))
    size = props.get("szCs" if complex_script else "sz")
    if isinstance(size, float) and math.isnan(size):
        borderline = True  # an unresolved size: kept
    scale = props.get("w")
    if (isinstance(size, float) and size <= MAX_TINY_SIZE) or (
        isinstance(scale, float) and scale < MIN_SCALE_PERCENT
    ):
        return Verdict(TINY_TEXT, borderline=False, font=font)
    spacing = props.get("spacing")
    position = props.get("position")
    borderline = (
        borderline
        or (isinstance(size, float) and size <= MAX_BORDERLINE_SIZE)
        or (isinstance(spacing, float) and spacing < 0)
        or (isinstance(position, float) and position < 0)
    )
    return Verdict(None, borderline=borderline, font=font)
