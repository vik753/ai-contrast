"""The render-mode device of the PDF extractor (S3-T3 AC4; ADR 0009 Layer 0).

Runs inside the parsing child (ADR 0011).

``StateInterpreter`` is a pdfminer page interpreter that also tracks what
pdfminer ignores:

- ExtGState (``gs``): fill alpha ``ca``, stroke alpha ``CA``; a blend mode other
  than ``Normal``/``Compatible`` or a soft mask marks the state as *exotic* (colour
  rules cannot be resolved exactly);
- a Form XObject starts with the graphics and text state of its ``Do`` (pdfminer
  resets them), and the device CTM is restored after ``Do``.

``RecordingDevice`` records, per page and in paint order:

- every glyph (``Glyph``): text, box, render mode (``Tr``), fill and stroke colour
  with their colour spaces, alpha, exotic flag, and the em size along both axes;
- every filled path (``Fill``): box and colour (``None`` when the colour cannot be
  compared: patterns, shadings, indexed or spot colours);
- every image (``Paint``): box (image XObjects and inline images);
- the crop box (intersected with the media box) in device space.

At the end of each page it hands a ``PageRecord`` to a callback and forgets it, so
memory holds one page at a time. Glyphs on all pages together are capped
(``max_glyphs`` → ``too_much_text``); fills per page are capped (``MAX_FILLS``;
the page is then marked ``fills_overflow``, which makes colour rules unresolved).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Final

from pdfminer.layout import LTChar
from pdfminer.pdfcolor import PDFColorSpace
from pdfminer.pdfdevice import PDFTextDevice, PDFTextSeq
from pdfminer.pdffont import PDFFont, PDFUnicodeNotDefined
from pdfminer.pdfinterp import (
    PDFGraphicState,
    PDFPageInterpreter,
    PDFResourceManager,
    PDFStackT,
    PDFTextState,
)
from pdfminer.pdfpage import PDFPage
from pdfminer.pdftypes import PDFStream, dict_value, list_value, resolve1
from pdfminer.psparser import PSLiteral, literal_name
from pdfminer.utils import Matrix, PathSegment, Rect, apply_matrix_pt, apply_matrix_rect

from app.extraction.model import TOO_MUCH_TEXT, ExtractionError

# Filled paths recorded per page; more → colour rules on that page are unresolved.
MAX_FILLS: Final = 20_000
UNDEFINED_GLYPH: Final = "�"
_NORMAL_BLEND: Final = frozenset({"Normal", "Compatible"})
_UNIT_RECT: Final = (0.0, 0.0, 1.0, 1.0)

# A colour in device space: (colour space name, components in 0..1).
Colour = tuple[str, tuple[float, ...]]
_DEVICE_COMPONENTS: Final = {"DeviceGray": 1, "DeviceRGB": 3, "DeviceCMYK": 4}
# ICC-based colours are compared only for the borderline rules, never removed.
_APPROX_SPACES: Final = {"ICCBased": {1: "DeviceGray", 3: "DeviceRGB", 4: "DeviceCMYK"}}


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))


def device_colour(space: PDFColorSpace, value: object) -> tuple[Colour | None, bool]:
    """The colour as ``(space, components)``, and whether it is exact.

    Exact: DeviceGray, DeviceRGB, DeviceCMYK. Approximate: ICCBased with 1, 3 or 4
    components (treated as the device space of that size). Anything else → ``None``.
    """
    name = space.name
    exact = name in _DEVICE_COMPONENTS
    if not exact:
        mapped = _APPROX_SPACES.get(name, {}).get(space.ncomponents)
        if mapped is None:
            return None, False
        name = mapped
    components: tuple[object, ...] = value if isinstance(value, tuple) else (value,)
    if len(components) != _DEVICE_COMPONENTS[name] or not all(
        isinstance(c, (int, float)) and math.isfinite(c) for c in components
    ):
        return None, False
    return (name, tuple(_clamp(float(c)) for c in components)), exact  # type: ignore[arg-type]


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


class StateGraphics(PDFGraphicState):
    """pdfminer's graphics state plus alpha and the exotic flag."""

    def __init__(self) -> None:
        super().__init__()
        self.fill_alpha = 1.0
        self.stroke_alpha = 1.0
        self.exotic = False

    def copy(self) -> StateGraphics:
        obj = StateGraphics()
        obj.__dict__.update(self.__dict__)
        return obj


class StateInterpreter(PDFPageInterpreter):
    """Tracks ExtGState alpha and inherits state into Form XObjects."""

    def __init__(self, rsrcmgr: PDFResourceManager, device: RecordingDevice) -> None:
        super().__init__(rsrcmgr, device)
        self._inherited: tuple[PDFTextState, StateGraphics] | None = None

    def _graphics(self) -> StateGraphics:
        state = self.graphicstate
        if not isinstance(state, StateGraphics):  # pragma: no cover - set in init_state
            raise TypeError
        return state

    def subinterp(self) -> PDFPageInterpreter:
        interp = super().subinterp()
        if isinstance(interp, StateInterpreter):
            interp._inherited = (self.textstate.copy(), self._graphics().copy())
        return interp

    def init_state(self, ctm: Matrix) -> None:
        super().init_state(ctm)
        if self._inherited is None:
            self.graphicstate = StateGraphics()
        else:
            text, graphics = self._inherited
            self.textstate = text.copy()
            self.graphicstate = graphics.copy()

    def do_gs(self, name: PDFStackT) -> None:
        state = self._graphics()
        resources = dict_value(self.resources) if self.resources else {}
        params = dict_value(dict_value(resources.get("ExtGState")).get(literal_name(name)))
        for key, attr in (("ca", "fill_alpha"), ("CA", "stroke_alpha")):
            value = resolve1(params.get(key))
            if isinstance(value, (int, float)) and math.isfinite(value):
                setattr(state, attr, _clamp(float(value)))
        blend = resolve1(params.get("BM"))
        if isinstance(blend, list) and blend:
            blend = resolve1(blend[0])
        if blend is not None and (
            not isinstance(blend, PSLiteral) or literal_name(blend) not in _NORMAL_BLEND
        ):
            state.exotic = True
        mask = resolve1(params.get("SMask"))
        if mask is not None and not (isinstance(mask, PSLiteral) and literal_name(mask) == "None"):
            state.exotic = True

    def do_Do(self, xobjid_arg: PDFStackT) -> None:  # noqa: N802 - pdfminer operator name
        super().do_Do(xobjid_arg)
        # pdfminer leaves the Form XObject's CTM on the device.
        self.device.set_ctm(self.ctm)


@dataclass(frozen=True, slots=True)
class _Style:
    """The paint of the glyphs of one text-showing operator."""

    fill: Colour | None
    fill_exact: bool
    stroke: Colour | None
    stroke_exact: bool
    fill_alpha: float
    stroke_alpha: float
    exotic: bool


_DEFAULT_STYLE: Final = _Style(
    fill=("DeviceGray", (0.0,)),
    fill_exact=True,
    stroke=("DeviceGray", (0.0,)),
    stroke_exact=True,
    fill_alpha=1.0,
    stroke_alpha=1.0,
    exotic=False,
)


@dataclass(slots=True)
class Glyph:
    char: LTChar
    text: str
    seq: int
    run: int
    render: int
    style: _Style
    em_x: float
    em_y: float

    @property
    def fill(self) -> Colour | None:
        return self.style.fill

    @property
    def fill_exact(self) -> bool:
        return self.style.fill_exact

    @property
    def stroke(self) -> Colour | None:
        return self.style.stroke

    @property
    def stroke_exact(self) -> bool:
        return self.style.stroke_exact

    @property
    def fill_alpha(self) -> float:
        return self.style.fill_alpha

    @property
    def stroke_alpha(self) -> float:
        return self.style.stroke_alpha

    @property
    def exotic(self) -> bool:
        return self.style.exotic

    @property
    def bbox(self) -> Rect:
        return self.char.bbox


@dataclass(slots=True)
class Fill:
    bbox: Rect
    seq: int
    colour: Colour | None  # None: cannot be compared


@dataclass(slots=True)
class Paint:
    bbox: Rect
    seq: int


@dataclass
class PageRecord:
    number: int
    crop: Rect
    glyphs: list[Glyph] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    images: list[Paint] = field(default_factory=list)
    fills_overflow: bool = False


def _path_bbox(ctm: Matrix, path: Sequence[PathSegment]) -> Rect | None:
    xs: list[float] = []
    ys: list[float] = []
    for segment in path:
        numbers = [v for v in segment[1:] if isinstance(v, (int, float))]
        for i in range(0, len(numbers) - 1, 2):
            x, y = apply_matrix_pt(ctm, (float(numbers[i]), float(numbers[i + 1])))
            xs.append(x)
            ys.append(y)
    if not xs:
        return None
    return (min(xs), min(ys), max(xs), max(ys))


def intersect(a: Rect, b: Rect) -> Rect | None:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x0 >= x1 or y0 >= y1:
        return None
    return (x0, y0, x1, y1)


class RecordingDevice(PDFTextDevice):
    """Records glyphs, fills and images per page (see the module doc)."""

    def __init__(
        self,
        rsrcmgr: PDFResourceManager,
        *,
        max_glyphs: int,
        on_page: Callable[[PageRecord], None],
    ) -> None:
        super().__init__(rsrcmgr)
        self._max_glyphs = max_glyphs
        self._on_page = on_page
        self._glyph_total = 0
        self._page: PageRecord | None = None
        self._number = 0
        self._seq = 0
        self._run = 0
        self._render = 0
        self._style = _DEFAULT_STYLE

    def _current(self) -> PageRecord:
        if self._page is None:
            raise ValueError
        return self._page

    def _matrix(self) -> Matrix:
        if self.ctm is None:
            raise ValueError
        return self.ctm

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def begin_page(self, page: PDFPage, ctm: Matrix) -> None:
        self._number += 1
        media = apply_matrix_rect(ctm, page.mediabox)
        crop = intersect(apply_matrix_rect(ctm, page.cropbox), media)
        self._page = PageRecord(number=self._number, crop=crop or (0.0, 0.0, 0.0, 0.0))
        self._seq = 0

    def end_page(self, page: PDFPage) -> None:
        record = self._current()
        self._page = None
        self._on_page(record)

    def begin_figure(self, name: str, bbox: Rect, matrix: Matrix) -> None:
        return

    def end_figure(self, name: str) -> None:
        return

    def render_image(self, name: str, stream: PDFStream) -> None:
        # Called between begin_figure and end_figure with the unit square mapped by
        # the current CTM (image XObjects and inline images).
        self._current().images.append(
            Paint(bbox=apply_matrix_rect(self._matrix(), _UNIT_RECT), seq=self._next_seq())
        )

    def paint_path(
        self,
        gstate: PDFGraphicState,
        stroke: bool,
        fill: bool,
        evenodd: bool,
        path: Sequence[PathSegment],
    ) -> None:
        if not fill:
            return
        record = self._current()
        if record.fills_overflow:
            return
        if len(record.fills) >= MAX_FILLS:
            record.fills_overflow = True
            return
        bbox = _path_bbox(self._matrix(), path)
        if bbox is None or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
            return
        colour, _exact = device_colour(gstate.ncs, gstate.ncolor)
        record.fills.append(Fill(bbox=bbox, seq=self._next_seq(), colour=colour))

    def render_string(
        self,
        textstate: PDFTextState,
        seq: PDFTextSeq,
        ncs: PDFColorSpace,
        graphicstate: PDFGraphicState,
    ) -> None:
        if textstate.font is None:
            return
        self._render = textstate.render
        self._run += 1
        # The paint of one text-showing operator, computed once for all its glyphs.
        fill, fill_exact = device_colour(graphicstate.ncs, graphicstate.ncolor)
        stroke, stroke_exact = device_colour(graphicstate.scs, graphicstate.scolor)
        state = graphicstate if isinstance(graphicstate, StateGraphics) else StateGraphics()
        self._style = _Style(
            fill=fill,
            fill_exact=fill_exact,
            stroke=stroke,
            stroke_exact=stroke_exact,
            fill_alpha=state.fill_alpha,
            stroke_alpha=state.stroke_alpha,
            exotic=state.exotic,
        )
        super().render_string(textstate, seq, ncs, graphicstate)

    def render_char(  # noqa: PLR0913, PLR0917 - pdfminer's signature
        self,
        matrix: Matrix,
        font: PDFFont,
        fontsize: float,
        scaling: float,
        rise: float,
        cid: int,
        ncs: PDFColorSpace,
        graphicstate: PDFGraphicState,
    ) -> float:
        self._glyph_total += 1
        if self._glyph_total > self._max_glyphs:
            raise ExtractionError(TOO_MUCH_TEXT)
        try:
            text = font.to_unichr(cid)
        except PDFUnicodeNotDefined:
            text = UNDEFINED_GLYPH
        char = LTChar(
            matrix,
            font,
            fontsize,
            scaling,
            rise,
            text,
            font.char_width(cid),
            font.char_disp(cid),
            ncs,
            graphicstate,
        )
        a, b, c, d = matrix[0], matrix[1], matrix[2], matrix[3]
        self._current().glyphs.append(
            Glyph(
                char=char,
                text=text,
                seq=self._next_seq(),
                run=self._run,
                render=self._render,
                style=self._style,
                em_x=abs(fontsize * scaling) * math.hypot(a, b),
                em_y=abs(fontsize) * math.hypot(c, d),
            )
        )
        return float(char.adv)


def resolved_list(value: object) -> list[object]:
    return list(list_value(resolve1(value)))
