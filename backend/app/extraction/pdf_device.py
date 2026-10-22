"""The render-mode device of the PDF extractor (S3-T3 AC4; ADR 0009 Layer 0).

Runs inside the parsing child (ADR 0011).

``StateInterpreter`` is a pdfminer page interpreter that also tracks what
pdfminer ignores:

- colours: every colour operator is resolved through the parsed colour space
  (``app.extraction.pdf_colour``) into ``StateGraphics.fill`` / ``stroke``
  (``None`` when the colour cannot be resolved exactly);
- ExtGState (``gs``): fill alpha ``ca``, stroke alpha ``CA``, ``/Font``; a blend
  mode other than ``Normal``/``Compatible`` or a soft mask marks the state as
  *exotic* (colour rules cannot be resolved exactly);
- the clip: the bounding box of every clipping path (``W``, ``W*``) and of every
  Form XObject ``BBox``, intersected, in device space (a superset of the real
  clip; a zero-area clip hides everything);
- optional content: marked content ``/OC`` and Form XObjects with ``/OC`` whose
  group is off (``app.extraction.pdf_content.OptionalContent``);
- a Form XObject starts with the graphics and text state of its ``Do`` (pdfminer
  resets them) and runs also without a ``BBox`` (pdfminer skips it); the device
  CTM is restored after ``Do``;
- content pdfminer does not run: a tiling pattern whose cell shows text
  (``not_read_pattern``), glyphs of a Type3 font without ``ToUnicode``
  (``not_read_type3``).

``RecordingDevice`` records, per page and in paint order:

- every glyph (``Glyph``): text, box, render mode (``Tr``), its paint (``Style``:
  fill and stroke colour, alphas, exotic flag, clip, optional content) and the em
  size along both axes (Type3 fonts through their ``FontMatrix``);
- every filled or stroked path and every ``sh`` shading (``Fill``): box (strokes
  widened by half the line width), colour (``None`` when it cannot be compared:
  patterns, shadings, unresolved colours) and whether it is a stroke;
- every image (``Paint``): box (image XObjects and inline images);
- the crop box (intersected with the media box) in device space;
- the material warnings found while running the page (``PageRecord.flags``).

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
from pdfminer.pdffont import PDFFont, PDFType3Font, PDFUnicodeNotDefined
from pdfminer.pdfinterp import (
    LITERAL_FORM,
    PDFGraphicState,
    PDFPageInterpreter,
    PDFResourceManager,
    PDFStackT,
    PDFTextState,
)
from pdfminer.pdfpage import PDFPage
from pdfminer.pdftypes import PDFObjRef, PDFStream, dict_value, list_value, resolve1
from pdfminer.psparser import PSLiteral, literal_name
from pdfminer.utils import (
    MATRIX_IDENTITY,
    Matrix,
    PathSegment,
    Rect,
    apply_matrix_pt,
    apply_matrix_rect,
    mult_matrix,
)

from app.extraction.model import TOO_MUCH_TEXT, ExtractionError
from app.extraction.pdf_colour import (
    DEVICE_CMYK,
    DEVICE_GRAY,
    DEVICE_RGB,
    Colour,
    ColourSpace,
    clamp,
    parse_colour_space,
    unknown_space,
)
from app.extraction.pdf_content import OptionalContent, tiling_runs_text

# Filled or stroked paths recorded per page; more → colour rules on that page are
# unresolved.
MAX_FILLS: Final = 20_000
UNDEFINED_GLYPH: Final = "�"
NOT_READ_PATTERN: Final = "not_read_pattern"
NOT_READ_TYPE3: Final = "not_read_type3"
_NORMAL_BLEND: Final = frozenset({"Normal", "Compatible"})
_UNIT_RECT: Final = (0.0, 0.0, 1.0, 1.0)
# A clip that hides everything.
EMPTY_CLIP: Final = (0.0, 0.0, 0.0, 0.0)
# Type3 glyph space: an em of 1000 units, like the standard 0.001 FontMatrix.
_EM_UNITS: Final = 1000.0
_BLACK: Final = ("DeviceGray", (0.0,))


def _finite(value: object) -> float | None:
    value = resolve1(value)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def intersect(a: Rect, b: Rect) -> Rect | None:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x0 >= x1 or y0 >= y1:
        return None
    return (x0, y0, x1, y1)


def clip_hides(clip: Rect | None, box: Rect) -> bool:
    """The clip (a bounding box) leaves nothing of ``box`` visible."""
    if clip is None:
        return False
    if clip[0] >= clip[2] or clip[1] >= clip[3]:
        return True  # a zero-area clip
    return box[2] < clip[0] or box[0] > clip[2] or box[3] < clip[1] or box[1] > clip[3]


def _narrow(clip: Rect | None, box: Rect | None) -> Rect:
    """The clip after intersecting it with ``box`` (``None`` box: an empty path)."""
    if box is None:
        return EMPTY_CLIP
    if clip is None:
        return box
    return intersect(clip, box) or EMPTY_CLIP


def path_bbox(ctm: Matrix, path: Sequence[PathSegment]) -> Rect | None:
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


class StateGraphics(PDFGraphicState):
    """pdfminer's graphics state plus resolved colours, alpha, clip and layers."""

    def __init__(self) -> None:
        super().__init__()
        self.fill_alpha = 1.0
        self.stroke_alpha = 1.0
        self.exotic = False
        self.fill_space: ColourSpace = DEVICE_GRAY
        self.stroke_space: ColourSpace = DEVICE_GRAY
        self.fill: Colour | None = _BLACK
        self.stroke: Colour | None = _BLACK
        self.clip: Rect | None = None
        self.layer_off = False

    def copy(self) -> StateGraphics:
        obj = StateGraphics()
        obj.__dict__.update(self.__dict__)
        return obj


@dataclass(frozen=True, slots=True)
class Style:
    """The paint of the glyphs of one text-showing operator."""

    fill: Colour | None
    stroke: Colour | None
    fill_alpha: float
    stroke_alpha: float
    exotic: bool
    clip: Rect | None
    layer_off: bool


_DEFAULT_STYLE: Final = Style(
    fill=_BLACK,
    stroke=_BLACK,
    fill_alpha=1.0,
    stroke_alpha=1.0,
    exotic=False,
    clip=None,
    layer_off=False,
)


@dataclass(slots=True)
class Glyph:
    char: LTChar
    text: str
    seq: int
    run: int
    render: int
    style: Style
    em_x: float
    em_y: float

    @property
    def bbox(self) -> Rect:
        return self.char.bbox


@dataclass(slots=True)
class Fill:
    bbox: Rect
    seq: int
    colour: Colour | None  # None: cannot be compared
    stroke: bool = False  # a stroke: the box is only an upper bound of the paint


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
    flags: set[str] = field(default_factory=set)
    fills_overflow: bool = False


class StateInterpreter(PDFPageInterpreter):
    """Tracks what pdfminer ignores (see the module doc)."""

    def __init__(
        self,
        rsrcmgr: PDFResourceManager,
        device: RecordingDevice,
        layers: OptionalContent,
    ) -> None:
        super().__init__(rsrcmgr, device)
        self.recorder = device
        self.layers = layers
        self._inherited: tuple[PDFTextState, StateGraphics] | None = None
        self._layer_base = False
        self._marked: list[bool] = []
        self._spaces: dict[str, object] = {}
        self._patterns: dict[str, object] = {}
        self._properties: dict[str, object] = {}

    def dup(self) -> StateInterpreter:
        return StateInterpreter(self.rsrcmgr, self.recorder, self.layers)

    def _graphics(self) -> StateGraphics:
        state = self.graphicstate
        if not isinstance(state, StateGraphics):  # pragma: no cover - set in init_state
            raise TypeError
        return state

    def _layer_off(self) -> bool:
        return self._layer_base or any(self._marked)

    def subinterp(self) -> PDFPageInterpreter:
        interp = super().subinterp()
        if isinstance(interp, StateInterpreter):
            interp._inherited = (self.textstate.copy(), self._graphics().copy())
            interp._layer_base = self._layer_off()
        return interp

    def init_resources(self, resources: dict[object, object]) -> None:
        super().init_resources(resources)
        res = dict_value(resources) if resources else {}
        self._spaces = _str_dict(res.get("ColorSpace"))
        self._patterns = _str_dict(res.get("Pattern"))
        self._properties = _str_dict(res.get("Properties"))

    def init_state(self, ctm: Matrix) -> None:
        super().init_state(ctm)
        self._marked = []
        if self._inherited is None:
            self.graphicstate = StateGraphics()
        else:
            text, graphics = self._inherited
            self.textstate = text.copy()
            self.graphicstate = graphics.copy()

    # --- Colours ---------------------------------------------------------------------------

    def _space(self, name: PDFStackT) -> ColourSpace:
        if not isinstance(name, PSLiteral):
            return unknown_space(1)
        space = parse_colour_space(name, self._spaces)
        return space if space is not None else unknown_space(1)

    def do_CS(self, name: PDFStackT) -> None:  # noqa: N802 - pdfminer operator name
        super().do_CS(name)
        state = self._graphics()
        state.stroke_space = self._space(name)
        state.stroke = state.stroke_space.initial()

    def do_cs(self, name: PDFStackT) -> None:
        super().do_cs(name)
        state = self._graphics()
        state.fill_space = self._space(name)
        state.fill = state.fill_space.initial()

    def _set_colour(self, *, stroke: bool) -> None:
        """``sc``/``scn`` (``SC``/``SCN``): read the operands before pdfminer pops them."""
        state = self._graphics()
        space = state.stroke_space if stroke else state.fill_space
        if space.kind == "Pattern":
            colour = None
            if self.argstack and isinstance(self.argstack[-1], PSLiteral):
                pattern = self._patterns.get(literal_name(self.argstack[-1]))
                if pattern is not None and tiling_runs_text(pattern):
                    self.recorder.flag(NOT_READ_PATTERN)
        elif space.kind == "Unknown":
            colour = None
        else:
            n = space.ncomponents
            if len(self.argstack) < n:
                return
            colour = space.resolve(self.argstack[-n:])
        if stroke:
            state.stroke = colour
        else:
            state.fill = colour

    def do_SCN(self) -> None:  # noqa: N802 - pdfminer operator name
        self._set_colour(stroke=True)
        super().do_SCN()

    def do_scn(self) -> None:
        self._set_colour(stroke=False)
        super().do_scn()

    def do_SC(self) -> None:  # noqa: N802 - pdfminer operator name
        self.do_SCN()

    def do_sc(self) -> None:
        self.do_scn()

    def _device(self, space: ColourSpace, values: Sequence[object], *, stroke: bool) -> None:
        state = self._graphics()
        colour = space.resolve(values)
        if stroke:
            state.stroke_space, state.stroke = space, colour
        else:
            state.fill_space, state.fill = space, colour

    def do_G(self, gray: PDFStackT) -> None:  # noqa: N802 - pdfminer operator name
        super().do_G(gray)
        self._device(DEVICE_GRAY, (gray,), stroke=True)

    def do_g(self, gray: PDFStackT) -> None:
        super().do_g(gray)
        self._device(DEVICE_GRAY, (gray,), stroke=False)

    def do_RG(self, r: PDFStackT, g: PDFStackT, b: PDFStackT) -> None:  # noqa: N802
        super().do_RG(r, g, b)
        self._device(DEVICE_RGB, (r, g, b), stroke=True)

    def do_rg(self, r: PDFStackT, g: PDFStackT, b: PDFStackT) -> None:
        super().do_rg(r, g, b)
        self._device(DEVICE_RGB, (r, g, b), stroke=False)

    def do_K(self, c: PDFStackT, m: PDFStackT, y: PDFStackT, k: PDFStackT) -> None:  # noqa: N802
        super().do_K(c, m, y, k)
        self._device(DEVICE_CMYK, (c, m, y, k), stroke=True)

    def do_k(self, c: PDFStackT, m: PDFStackT, y: PDFStackT, k: PDFStackT) -> None:
        super().do_k(c, m, y, k)
        self._device(DEVICE_CMYK, (c, m, y, k), stroke=False)

    # --- Graphics state, clip, shadings ----------------------------------------------------

    def do_gs(self, name: PDFStackT) -> None:
        state = self._graphics()
        resources = dict_value(self.resources) if self.resources else {}
        params = dict_value(dict_value(resources.get("ExtGState")).get(literal_name(name)))
        for key, attr in (("ca", "fill_alpha"), ("CA", "stroke_alpha")):
            value = _finite(params.get(key))
            if value is not None:
                setattr(state, attr, clamp(value))
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
        if "Font" in params:
            self._set_font(params["Font"])

    def _set_font(self, value: object) -> None:
        """``/Font [font size]`` of an ExtGState (ISO 32000-1, table 58)."""
        items = list_value(resolve1(value))
        size = _finite(items[1]) if len(items) == 2 else None  # noqa: PLR2004
        if size is None:
            return
        ref = items[0]
        spec = dict_value(ref)
        objid = ref.objid if isinstance(ref, PDFObjRef) else None
        self.textstate.font = self.rsrcmgr.get_font(objid, spec)
        self.textstate.fontsize = size

    def _clip(self) -> None:
        state = self._graphics()
        state.clip = _narrow(state.clip, path_bbox(self.ctm, self.curpath))

    def do_W(self) -> None:  # noqa: N802 - pdfminer operator name
        self._clip()

    def do_W_a(self) -> None:  # noqa: N802 - pdfminer operator name
        self._clip()

    def do_sh(self, name: object) -> None:
        self.recorder.paint_shading(self._graphics().clip)

    # --- Optional content ------------------------------------------------------------------

    def do_BMC(self, tag: PDFStackT) -> None:  # noqa: N802 - pdfminer operator name
        self._marked.append(False)
        super().do_BMC(tag)

    def do_BDC(self, tag: PDFStackT, props: PDFStackT) -> None:  # noqa: N802
        off = False
        if isinstance(tag, PSLiteral) and literal_name(tag) == "OC":
            ref = (
                self._properties.get(literal_name(props)) if isinstance(props, PSLiteral) else props
            )
            off = self.layers.is_off(ref)
        self._marked.append(off)
        super().do_BDC(tag, props)

    def do_EMC(self) -> None:  # noqa: N802 - pdfminer operator name
        if self._marked:
            self._marked.pop()
        super().do_EMC()

    def do_TJ(self, seq: PDFStackT) -> None:  # noqa: N802 - pdfminer operator name
        self._graphics().layer_off = self._layer_off()
        super().do_TJ(seq)

    # --- XObjects --------------------------------------------------------------------------

    def do_Do(self, xobjid_arg: PDFStackT) -> None:  # noqa: N802 - pdfminer operator name
        xobjid = literal_name(xobjid_arg)
        xobj = resolve1(self.xobjmap.get(xobjid))
        if not isinstance(xobj, PDFStream) or xobj.get("Subtype") is not LITERAL_FORM:
            super().do_Do(xobjid_arg)
            self.device.set_ctm(self.ctm)
            return
        # A Form XObject, with or without BBox (pdfminer skips forms without one).
        matrix = _matrix(xobj.get("Matrix"))
        ctm = mult_matrix(matrix, self.ctm)
        interpreter = self.subinterp()
        if isinstance(interpreter, StateInterpreter) and interpreter._inherited is not None:
            graphics = interpreter._inherited[1]
            bbox = _rect(xobj.get("BBox"))
            if bbox is not None:
                graphics.clip = _narrow(graphics.clip, apply_matrix_rect(ctm, bbox))
            if "OC" in xobj and self.layers.is_off(xobj["OC"]):
                interpreter._layer_base = True
        xobjres = xobj.get("Resources")
        resources = dict_value(xobjres) if xobjres else self.resources.copy()
        interpreter.render_contents(resources, [xobj], ctm=ctm)
        self.device.set_ctm(self.ctm)


def _str_dict(value: object) -> dict[str, object]:
    found = resolve1(value)
    if not isinstance(found, dict):
        return {}
    return {str(key): item for key, item in found.items()}


def _matrix(value: object) -> Matrix:
    items = resolve1(value)
    if not isinstance(items, list) or len(items) != 6:  # noqa: PLR2004
        return MATRIX_IDENTITY
    numbers = [_finite(item) for item in items]
    if any(n is None for n in numbers):
        return MATRIX_IDENTITY
    a, b, c, d, e, f = (n for n in numbers if n is not None)
    return (a, b, c, d, e, f)


def _rect(value: object) -> Rect | None:
    items = resolve1(value)
    if not isinstance(items, list) or len(items) != 4:  # noqa: PLR2004
        return None
    numbers = [_finite(item) for item in items]
    if any(n is None for n in numbers):
        return None
    x0, y0, x1, y1 = (n for n in numbers if n is not None)
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _type3_scale(font: PDFFont) -> tuple[float, float]:
    """The em scale of a Type3 font along x and y (1 for other fonts)."""
    if not isinstance(font, PDFType3Font):
        return (1.0, 1.0)
    numbers = [_finite(v) for v in font.matrix] if len(font.matrix) == 6 else []  # noqa: PLR2004
    if len(numbers) != 6 or any(n is None for n in numbers):  # noqa: PLR2004
        return (0.0, 0.0)  # unusable FontMatrix: the glyphs are treated as tiny
    a, b, c, d = (n or 0.0 for n in numbers[:4])
    return (math.hypot(a, b) * _EM_UNITS, math.hypot(c, d) * _EM_UNITS)


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
        self._em_scale = (1.0, 1.0)
        self._type3_unread = False

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

    def flag(self, code: str) -> None:
        self._current().flags.add(code)

    def begin_page(self, page: PDFPage, ctm: Matrix) -> None:
        self._number += 1
        media = apply_matrix_rect(ctm, page.mediabox)
        crop = intersect(apply_matrix_rect(ctm, page.cropbox), media)
        self._page = PageRecord(number=self._number, crop=crop or EMPTY_CLIP)
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

    def _record_fill(self, bbox: Rect | None, colour: Colour | None, *, stroke: bool) -> None:
        record = self._current()
        if record.fills_overflow:
            return
        if len(record.fills) >= MAX_FILLS:
            record.fills_overflow = True
            return
        if bbox is None or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
            return
        record.fills.append(Fill(bbox=bbox, seq=self._next_seq(), colour=colour, stroke=stroke))

    def paint_path(
        self,
        gstate: PDFGraphicState,
        stroke: bool,
        fill: bool,
        evenodd: bool,
        path: Sequence[PathSegment],
    ) -> None:
        state = gstate if isinstance(gstate, StateGraphics) else StateGraphics()
        ctm = self._matrix()
        bbox = path_bbox(ctm, path)
        if fill:
            self._record_fill(bbox, state.fill, stroke=False)
        if stroke and bbox is not None:
            # Half the line width in device space (at least half a point).
            width = _finite(state.linewidth) or 0.0
            half = max(abs(width) * math.sqrt(abs(ctm[0] * ctm[3] - ctm[1] * ctm[2])), 1.0) / 2
            widened = (bbox[0] - half, bbox[1] - half, bbox[2] + half, bbox[3] + half)
            self._record_fill(widened, state.stroke, stroke=True)

    def paint_shading(self, clip: Rect | None) -> None:
        """``sh``: the shading paints the clip (the whole page without a clip)."""
        record = self._current()
        self._record_fill(record.crop if clip is None else clip, None, stroke=False)

    def render_string(
        self,
        textstate: PDFTextState,
        seq: PDFTextSeq,
        ncs: PDFColorSpace,
        graphicstate: PDFGraphicState,
    ) -> None:
        font = textstate.font
        if font is None:
            return
        self._render = textstate.render
        self._run += 1
        self._em_scale = _type3_scale(font)
        self._type3_unread = isinstance(font, PDFType3Font) and font.unicode_map is None
        # The paint of one text-showing operator, computed once for all its glyphs.
        state = graphicstate if isinstance(graphicstate, StateGraphics) else StateGraphics()
        self._style = Style(
            fill=state.fill,
            stroke=state.stroke,
            fill_alpha=state.fill_alpha,
            stroke_alpha=state.stroke_alpha,
            exotic=state.exotic,
            clip=state.clip,
            layer_off=state.layer_off,
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
        if self._type3_unread:
            self.flag(NOT_READ_TYPE3)
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
        scale_x, scale_y = self._em_scale
        self._current().glyphs.append(
            Glyph(
                char=char,
                text=text,
                seq=self._next_seq(),
                run=self._run,
                render=self._render,
                style=self._style,
                em_x=abs(fontsize * scaling) * math.hypot(a, b) * scale_x,
                em_y=abs(fontsize) * math.hypot(c, d) * scale_y,
            )
        )
        return float(char.adv)


def resolved_list(value: object) -> list[object]:
    return list(list_value(resolve1(value)))
