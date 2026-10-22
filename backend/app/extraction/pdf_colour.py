"""Colour spaces of the PDF extractor (S3-T3 AC4, review round 1 item 2).

Runs inside the parsing child (ADR 0011). pdfminer keeps only the name and the
component count of a colour space, so CalGray, Lab, Indexed, Separation and
DeviceN colours cannot be compared with white. Here the colour space is parsed
from the resources and every colour is resolved to a device colour
(``Colour``: DeviceGray, DeviceRGB or DeviceCMYK, components in 0..1), or to
``None`` when it cannot be resolved exactly:

- DeviceGray, DeviceRGB, DeviceCMYK: as they are;
- ICCBased: as the device space with the same number of components (1, 3, 4);
- CalGray, CalRGB: the components as DeviceGray / DeviceRGB (white is exact:
  all components 1; the luminance is approximate);
- Lab: white only for L = 100 with a = b = 0; other colours are compared by
  their lightness ``L / 100`` (never exact white when a or b is not 0);
- Indexed: through its lookup table into the resolved base space;
- Separation and DeviceN: all tints 0 = no ink (white, tech-lead rule of round 1);
  other tints through a Type 2 (exponential) tint transform with one input,
  else ``None``. The ``None`` colorant → ``None``.
- Pattern and anything else → ``None``.

``None`` is never treated as white: text in such a colour is kept with
``borderline_text``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from pdfminer.pdftypes import PDFStream, resolve1
from pdfminer.psparser import PSLiteral, literal_name

# A colour in device space: (colour space name, components in 0..1).
Colour = tuple[str, tuple[float, ...]]

DEVICE_COMPONENTS: Final = {"DeviceGray": 1, "DeviceRGB": 3, "DeviceCMYK": 4}
_DEVICE_ALIASES: Final = {"G": "DeviceGray", "RGB": "DeviceRGB", "CMYK": "DeviceCMYK"}
_ICC_SPACES: Final = {1: "DeviceGray", 3: "DeviceRGB", 4: "DeviceCMYK"}
# Nesting of colour spaces (Indexed → base, Separation → alternate).
MAX_SPACE_DEPTH: Final = 4
MAX_COMPONENTS: Final = 32
MAX_HIVAL: Final = 255
LAB_WHITE_L: Final = 100.0
# A Lab colour with chroma is never exact white.
_LAB_CHROMA_CAP: Final = 0.99


def clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def _number(value: object) -> float | None:
    value = resolve1(value)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _numbers(value: object, size: int | None = None) -> tuple[float, ...] | None:
    items = resolve1(value)
    if not isinstance(items, list) or (size is not None and len(items) != size):
        return None
    out = [_number(item) for item in items]
    if any(item is None for item in out):
        return None
    return tuple(item for item in out if item is not None)


@dataclass(frozen=True, slots=True)
class TintFunction:
    """A Type 2 (exponential) function with one input: ``C0 + x^N (C1 - C0)``."""

    c0: tuple[float, ...]
    c1: tuple[float, ...]
    exponent: float
    domain: tuple[float, float]

    def __call__(self, x: float) -> tuple[float, ...] | None:
        low, high = self.domain
        x = min(high, max(low, x))
        try:
            power = x**self.exponent
        except (ArithmeticError, ValueError):
            return None
        if isinstance(power, complex) or not math.isfinite(power):
            return None
        return tuple(a + power * (b - a) for a, b in zip(self.c0, self.c1, strict=True))


def _tint_function(spec: object, outputs: int) -> TintFunction | None:
    spec = resolve1(spec)
    if isinstance(spec, PDFStream):
        return None  # Types 0 and 4 are streams: not evaluated.
    if not isinstance(spec, dict) or _number(spec.get("FunctionType")) != 2.0:  # noqa: PLR2004
        return None
    exponent = _number(spec.get("N"))
    domain = _numbers(spec.get("Domain"), 2)
    c0 = _numbers(spec["C0"]) if "C0" in spec else (0.0,)
    c1 = _numbers(spec["C1"]) if "C1" in spec else (1.0,)
    if exponent is None or domain is None or c0 is None or c1 is None:
        return None
    if len(c0) != outputs or len(c1) != outputs:
        return None
    return TintFunction(c0=c0, c1=c1, exponent=exponent, domain=(domain[0], domain[1]))


@dataclass(frozen=True, slots=True)
class ColourSpace:
    """A parsed colour space (see the module doc). ``kind`` is its family name."""

    kind: str
    ncomponents: int
    base: ColourSpace | None = None  # Indexed base, Separation/DeviceN alternate
    lookup: bytes = b""  # Indexed
    hival: int = 0  # Indexed
    ranges: tuple[float, ...] = ()  # Lab: a and b ranges
    tint: TintFunction | None = None  # Separation/DeviceN
    no_colorant: bool = False  # Separation /None

    def initial(self) -> Colour | None:
        """The colour that ``cs`` / ``CS`` set (ISO 32000-1, 8.6.8)."""
        if self.kind == "DeviceCMYK" or (
            self.kind == "ICCBased" and self.ncomponents == 4  # noqa: PLR2004
        ):
            return ("DeviceCMYK", (0.0, 0.0, 0.0, 1.0))
        if self.kind in {"Separation", "DeviceN"}:
            return self.resolve((1.0,) * self.ncomponents)
        if self.kind == "Lab":
            return self.resolve((0.0, 0.0, 0.0))
        return self.resolve((0.0,) * self.ncomponents)

    def resolve(self, components: Sequence[object]) -> Colour | None:  # noqa: PLR0911
        values = [_number(c) for c in components]
        if len(values) != self.ncomponents or any(v is None for v in values):
            return None
        c = tuple(v for v in values if v is not None)
        kind = self.kind
        if kind in DEVICE_COMPONENTS:
            return (kind, tuple(clamp(x) for x in c))
        if kind == "ICCBased":
            return (_ICC_SPACES[self.ncomponents], tuple(clamp(x) for x in c))
        if kind == "CalGray":
            return ("DeviceGray", (clamp(c[0]),))
        if kind == "CalRGB":
            return ("DeviceRGB", tuple(clamp(x) for x in c))
        if kind == "Lab":
            lightness = clamp(c[0] / LAB_WHITE_L)
            if c[1] != 0.0 or c[2] != 0.0:
                lightness = min(lightness, _LAB_CHROMA_CAP)
            return ("DeviceGray", (lightness,))
        if kind == "Indexed":
            return self._indexed(c[0])
        if kind in {"Separation", "DeviceN"}:
            return self._tinted(c)
        return None

    def _indexed(self, value: float) -> Colour | None:
        base = self.base
        if base is None:
            return None
        index = min(self.hival, max(0, round(value)))
        size = base.ncomponents
        entry = self.lookup[index * size : (index + 1) * size]
        if len(entry) != size:
            return None
        if base.kind == "Lab" and len(self.ranges) == 4:  # noqa: PLR2004
            a0, a1, b0, b1 = self.ranges
            lab = (
                entry[0] / 255 * LAB_WHITE_L,
                a0 + entry[1] / 255 * (a1 - a0),
                b0 + entry[2] / 255 * (b1 - b0),
            )
            return base.resolve(lab)
        return base.resolve([byte / 255 for byte in entry])

    def _tinted(self, tints: tuple[float, ...]) -> Colour | None:
        if self.no_colorant:
            return None
        if all(t == 0.0 for t in tints):
            return ("DeviceGray", (1.0,))  # no ink
        if self.tint is None or self.base is None or len(tints) != 1:
            return None
        out = self.tint(tints[0])
        return None if out is None else self.base.resolve(out)


DEVICE_GRAY: Final = ColourSpace("DeviceGray", 1)
DEVICE_RGB: Final = ColourSpace("DeviceRGB", 3)
DEVICE_CMYK: Final = ColourSpace("DeviceCMYK", 4)
PATTERN: Final = ColourSpace("Pattern", 1)
_DEVICE_SPACES: Final = {s.kind: s for s in (DEVICE_GRAY, DEVICE_RGB, DEVICE_CMYK)}


def unknown_space(ncomponents: int) -> ColourSpace:
    return ColourSpace("Unknown", ncomponents)


def _lookup_bytes(value: object) -> bytes | None:
    value = resolve1(value)
    if isinstance(value, PDFStream):
        value = value.get_data()
    return value if isinstance(value, bytes) else None


def parse_colour_space(  # noqa: PLR0911, PLR0912
    spec: object, named: dict[str, object] | None = None, depth: int = 0
) -> ColourSpace | None:
    """The colour space of ``spec`` (a name or an array), or ``None`` (unknown).

    ``named`` holds the ``/ColorSpace`` resources for names that are not families.
    """
    if depth > MAX_SPACE_DEPTH:
        return None
    spec = resolve1(spec)
    if isinstance(spec, PSLiteral):
        name = literal_name(spec)
        name = _DEVICE_ALIASES.get(name, name)
        if name in _DEVICE_SPACES:
            return _DEVICE_SPACES[name]
        if name == "Pattern":
            return PATTERN
        if named is not None and name in named:
            return parse_colour_space(named[name], None, depth + 1)
        return None
    if not isinstance(spec, list) or not spec:
        return None
    family = resolve1(spec[0])
    if not isinstance(family, PSLiteral):
        return None
    name = literal_name(family)
    args = [resolve1(item) for item in spec[1:]]
    if name in _DEVICE_SPACES or name == "Pattern":
        return _DEVICE_SPACES.get(name, PATTERN)
    if name == "CalGray":
        return ColourSpace("CalGray", 1)
    if name == "CalRGB":
        return ColourSpace("CalRGB", 3)
    if name == "Lab":
        ranges: tuple[float, ...] = (-100.0, 100.0, -100.0, 100.0)
        params = args[0] if args else None
        if isinstance(params, dict) and "Range" in params:
            ranges = _numbers(params["Range"], 4) or ranges
        return ColourSpace("Lab", 3, ranges=ranges)
    if name == "ICCBased":
        stream = args[0] if args else None
        count = _number(stream.get("N")) if isinstance(stream, PDFStream) else None
        if count is None or int(count) not in _ICC_SPACES or count != int(count):
            return None
        return ColourSpace("ICCBased", int(count))
    if name == "Indexed":
        return _indexed(args, depth)
    if name in {"Separation", "DeviceN"}:
        return _tinted(name, args, depth)
    return None


def _indexed(args: list[object], depth: int) -> ColourSpace | None:
    if len(args) < 3:  # noqa: PLR2004
        return None
    base = parse_colour_space(args[0], None, depth + 1)
    hival = _number(args[1])
    lookup = _lookup_bytes(args[2])
    if base is None or hival is None or lookup is None or base.kind in {"Pattern", "Indexed"}:
        return None
    if hival != int(hival) or not 0 <= hival <= MAX_HIVAL:
        return None
    return ColourSpace("Indexed", 1, base=base, lookup=lookup, hival=int(hival), ranges=base.ranges)


def _tinted(name: str, args: list[object], depth: int) -> ColourSpace | None:
    if len(args) < 3:  # noqa: PLR2004
        return None
    names = args[0]
    if name == "Separation":
        colorants = [names] if isinstance(names, PSLiteral) else []
    else:
        colorants = [resolve1(n) for n in names] if isinstance(names, list) else []
    if not colorants or len(colorants) > MAX_COMPONENTS:
        return None
    if not all(isinstance(c, PSLiteral) for c in colorants):
        return None
    base = parse_colour_space(args[1], None, depth + 1)
    if base is None or base.kind in {"Pattern", "Indexed", "Separation", "DeviceN"}:
        base = None
    tint = _tint_function(args[2], base.ncomponents) if base is not None else None
    no_colorant = all(literal_name(c) == "None" for c in colorants)
    return ColourSpace(name, len(colorants), base=base, tint=tint, no_colorant=no_colorant)


def luminance(colour: Colour) -> float:
    name, c = colour
    if name == "DeviceGray":
        r = g = b = c[0]
    elif name == "DeviceRGB":
        r, g, b = c
    else:
        cyan, magenta, yellow, black = c
        r, g, b = ((1 - x) * (1 - black) for x in (cyan, magenta, yellow))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def is_white(colour: Colour) -> bool:
    name, c = colour
    if name == "DeviceCMYK":
        return all(x == 0.0 for x in c)
    return all(x == 1.0 for x in c)
