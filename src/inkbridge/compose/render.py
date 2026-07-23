"""Row-grid renderer: block IR → PDF + manifest cells (Analysis 0012 F8–F9).

A single imperative pass deals blocks onto uniform 80 px rows top-to-bottom,
drawing content and the footer command strip together and recording every
input-area bbox as row arithmetic. Greedy word-wrap uses the pinned embedded
font's own metrics (fonts.py), so measurement and drawing can never drift
apart. The canvas is opened with invariant=1: identical input produces
byte-identical PDFs.

All geometry comes from the DeviceProfile handed to the Renderer (Manta by
default); the wrap helpers below are profile-free — they only see widths.
"""

from __future__ import annotations

import re
from pathlib import Path

from reportlab.pdfgen import canvas as rl_canvas

from .fonts import BODY, BOLD, BOLDITALIC, ITALIC, MONO, register_fonts, width_px
from .geometry import BLACK, FAINT, GRAY, MANTA, ROW, DeviceProfile, Px
from .parser import (
    Ack,
    Capture,
    Checkbox,
    Choice,
    CodeBlock,
    Comb,
    Heading,
    ListItem,
    Paragraph,
    Placeholder,
    Quote,
    Rule,
    Table,
)

# level -> (size_pt, rows, underline); all headings render bold.
_HEADING_STYLE = {1: (22.0, 2, True), 2: (15.0, 2, False), 3: (12.5, 1, False)}

# Inline-style name (parser.Segment) -> pinned font, per context. Quotes
# render body text italic, so bold inside a quote becomes bold-italic.
_FONTS = {"body": BODY, "bold": BOLD, "italic": ITALIC,
          "bolditalic": BOLDITALIC, "code": MONO}
_QUOTE_FONTS = {**_FONTS, "body": ITALIC, "bold": BOLDITALIC}


def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return (s or "x")[:24]


def _fit(text: str, font: str, size_pt: float, max_px: float) -> str:
    if width_px(text, font, size_pt) <= max_px:
        return text
    while text and width_px(text + "...", font, size_pt) > max_px:
        text = text[:-1]
    return text + "..." if text else "..."


def _char_wrap(s: str, font: str, size_pt: float, max_px: float) -> list[str]:
    if not s:
        return [""]
    lines, cur = [], ""
    for ch in s:
        if cur and width_px(cur + ch, font, size_pt) > max_px:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    lines.append(cur)
    return lines


def _wrap(text: str, font: str, size_pt: float, max_px: float) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines, cur = [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if width_px(trial, font, size_pt) <= max_px:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            if width_px(w, font, size_pt) <= max_px:
                cur = w
            else:
                segs = _char_wrap(w, font, size_pt, max_px)
                lines.extend(segs[:-1])
                cur = segs[-1]
    lines.append(cur)
    return lines


# -- styled-segment wrap (0012 finding 9.1) --------------------------------
# A "run" is a (text, font) pair; a wrapped line is a list of runs drawn
# left-to-right. A "word" may span style boundaries (e.g. un**bold**ed), so
# words are lists of runs too, split on whitespace across all segments.

Run = tuple[str, str]


def _segment_words(segments, fonts: dict[str, str]) -> list[list[Run]]:
    words: list[list[Run]] = []
    cur: list[Run] = []
    for text, style in segments:
        font = fonts.get(style, fonts["body"])
        for piece in re.split(r"(\s+)", text):
            if not piece:
                continue
            if piece.isspace():
                if cur:
                    words.append(cur)
                    cur = []
            elif cur and cur[-1][1] == font:
                cur[-1] = (cur[-1][0] + piece, font)
            else:
                cur.append((piece, font))
    if cur:
        words.append(cur)
    return words


def _runs_width(runs: list[Run], size_pt: float) -> float:
    return sum(width_px(text, font, size_pt) for text, font in runs)


def _char_wrap_runs(word: list[Run], size_pt: float, max_px: float) -> list[list[Run]]:
    lines: list[list[Run]] = []
    cur: list[Run] = []
    cur_w = 0.0
    for text, font in word:
        for ch in text:
            cw = width_px(ch, font, size_pt)
            if cur and cur_w + cw > max_px:
                lines.append(cur)
                cur, cur_w = [], 0.0
            if cur and cur[-1][1] == font:
                cur[-1] = (cur[-1][0] + ch, font)
            else:
                cur.append((ch, font))
            cur_w += cw
    lines.append(cur or [("", BODY)])
    return lines


def wrap_runs(segments, size_pt: float, max_px: float,
              fonts: dict[str, str] = _FONTS) -> list[list[Run]]:
    """Greedy word-wrap over styled segments; returns lines of draw runs.
    The same metrics measure and draw, so wrapping cannot drift from the
    manifest (0012 finding 9)."""
    words = _segment_words(segments, fonts)
    if not words:
        return [[("", fonts["body"])]]
    space_w = width_px(" ", fonts["body"], size_pt)
    lines: list[list[Run]] = []
    cur: list[Run] = []
    cur_w = 0.0

    def flush() -> None:
        nonlocal cur, cur_w
        if cur:
            lines.append(cur)
        cur, cur_w = [], 0.0

    for word in words:
        w = _runs_width(word, size_pt)
        if cur and cur_w + space_w + w > max_px:
            flush()
        if not cur and w > max_px:
            pieces = _char_wrap_runs(word, size_pt, max_px)
            lines.extend(pieces[:-1])
            cur = pieces[-1]
            cur_w = _runs_width(cur, size_pt)
            continue
        if cur:
            cur.append((" ", fonts["body"]))
            cur_w += space_w
        cur.extend(word)
        cur_w += w
    flush()
    return lines


class Renderer:
    def __init__(self, pdf_path: Path, profile: DeviceProfile = MANTA,
                 scale: float = 1.0):
        register_fonts()
        self.g = profile
        # Density scale: <1.0 packs content tighter. It multiplies every
        # content design constant uniformly — fonts, the row height, glyph
        # boxes, and every baseline/inset offset — so the layout stays
        # arithmetically self-consistent and the manifest bboxes remain
        # correct by construction (geometry.py). The canvas, margins, and
        # chrome envelope are device-physical and never scale. Because the
        # tickable glyph boxes shrink too, a new scale wants an on-device
        # preview to confirm pen ergonomics and ink isolation (glyph_pad).
        self.s = scale
        self.row_h = ROW * scale
        self.content_top = profile.content_top * scale
        self.glyph_box = profile.glyph_box * scale
        self.glyph_pad = profile.glyph_pad * scale
        self.trigger_box = profile.trigger_box * scale
        self.rows_per_page = int(
            (profile.strip_top - self.u(40) - self.content_top) // self.row_h
        )
        self.c = rl_canvas.Canvas(
            str(pdf_path), pagesize=(profile.page_w_pt, profile.page_h_pt), invariant=1
        )
        self.px = Px(self.c, profile)
        self.cells: list[dict] = []
        self._ids: set[str] = set()
        self._groups: set[str] = set()
        self.page = 0
        self.row = 0
        self.prev = None
        self._start_page()

    def u(self, v: float) -> float:
        """Scale a design constant by the density factor. Applies to both
        px offsets and font sizes — content scales uniformly (see __init__)."""
        return v * self.s

    # -- page machinery ----------------------------------------------------

    def _y(self, row: int | None = None) -> float:
        return self.content_top + (self.row if row is None else row) * self.row_h

    def _start_page(self) -> None:
        self.page += 1
        self.row = 0
        # Corner registration ticks — compositing/alignment aid.
        for cx, dx in ((40, 1), (self.g.canvas_w - 40, -1)):
            for cy, dy in ((40, 1), (self.g.canvas_h - 40, -1)):
                self.px.bracket(cx, cy, dx, dy, arm=40, lw=3.0)

    def _finish_page(self) -> None:
        self._draw_strip()
        self.c.showPage()

    def _ensure(self, rows: int) -> None:
        if self.rows_per_page - self.row < rows:
            self._finish_page()
            self._start_page()

    def _gap(self, block) -> None:
        if self.row == 0 or self.prev is None:
            return
        if type(block) is type(self.prev) and isinstance(
            block, (ListItem, Checkbox, Quote)
        ):
            return
        self.row += 1

    def _add_cell(self, ctype, label, x, y, w, h, id_=None, **extra) -> None:
        cid = id_ or f"{ctype}.{_slug(label)}"
        base, n = cid, 2
        while cid in self._ids:
            cid = f"{base}.{n}"
            n += 1
        self._ids.add(cid)
        self.cells.append(
            {
                "id": cid,
                "page": self.page,
                "type": ctype,
                "label": label,
                "bbox_norm": self.g.norm(x, y, w, h),
                **extra,
            }
        )

    def _draw_strip(self) -> None:
        # The reader UI clips the bottom corners but not the center band
        # (measured 2026-07-20 on the Manta, assumed elsewhere — see
        # geometry profile notes): side content stays high; the trigger
        # box row sits lower, inside the center-visible band.
        g, p = self.g, self.px
        p.line(g.content_x0, g.strip_top, g.content_x1, g.strip_top, lw=2.0, stroke=GRAY)
        p.text(g.content_x0 + self.u(30), g.strip_top - self.u(14),
               "command strip", self.u(7.0), BODY, fill=GRAY)
        p.text(g.content_x1 - self.u(60), g.strip_top - self.u(14),
               f"p{self.page}", self.u(7.0), BODY, fill=GRAY)

        # Page-level AI-parse trigger: one centered box per page. It is a
        # pure trigger and carries no page identity — mark-page↔compose-page
        # mapping is positional (the device never modifies a pushed PDF,
        # 0014 F3), and a positional/printed fiducial could not confirm it
        # anyway: the isolated-ink readback never sees printed content
        # (composite.py; 0009 F3). The box sits in the center-visible band.
        tx = (g.canvas_w - self.trigger_box) / 2
        ty = g.strip_top + self.u(70)
        label = "capture pg"
        label_x = tx + (self.trigger_box - width_px(label, BODY, self.u(7.0))) / 2
        p.text(label_x, g.strip_top + self.u(56), label, self.u(7.0), BODY, fill=GRAY)
        p.rect(tx, ty, self.trigger_box, self.trigger_box, lw=4.0)
        self._add_cell(
            "capture_trigger",
            f"capture page {self.page}",
            tx - self.u(16), ty - self.u(16),
            self.trigger_box + self.u(32), self.trigger_box + self.u(32),
            id_=f"cmd.capture.p{self.page}",
        )

    # -- block renderers ---------------------------------------------------

    def render(self, blocks: list) -> None:
        g = self.g
        for b in blocks:
            self._gap(b)
            if isinstance(b, Heading):
                self._heading(b)
            elif isinstance(b, Paragraph):
                self._para_lines(
                    wrap_runs(b.segments, self.u(11.0), g.content_w - self.u(60)),
                    g.content_x0 + self.u(30), size=self.u(11.0))
            elif isinstance(b, ListItem):
                self._list_item(b)
            elif isinstance(b, Checkbox):
                self._checkbox(b.label, b.depth, "checkbox")
            elif isinstance(b, Ack):
                self._checkbox(b.label, 0, "ack")
            elif isinstance(b, Choice):
                self._choice(b)
            elif isinstance(b, Capture):
                self._capture(b)
            elif isinstance(b, Comb):
                self._comb(b)
            elif isinstance(b, CodeBlock):
                self._code(b)
            elif isinstance(b, Table):
                self._table(b)
            elif isinstance(b, Quote):
                self._para_lines(
                    wrap_runs(b.segments, self.u(11.0), g.content_w - self.u(160),
                              _QUOTE_FONTS),
                    g.content_x0 + self.u(100), size=self.u(11.0), bar=True,
                )
            elif isinstance(b, Rule):
                self._rule()
            elif isinstance(b, Placeholder):
                self._placeholder(b)
            self.prev = b
        self._finish_page()
        self.c.save()

    def _draw_runs(self, x: float, baseline: float, runs, size: float,
                   fill=BLACK) -> None:
        for text, font in runs:
            self.px.text(x, baseline, text, size, font, fill=fill)
            x += width_px(text, font, size)

    def _para_lines(self, lines, x, size=11.0, fill=BLACK, bar=False) -> None:
        """Deal wrapped lines of draw runs onto rows. `size` must match the
        size the runs were wrapped at, or drawing drifts from wrapping."""
        for runs in lines:
            self._ensure(1)
            top = self._y()
            if bar:
                self.px.line(self.g.content_x0 + 16, top, self.g.content_x0 + 16,
                             top + self.row_h, lw=4.0, stroke=GRAY)
            self._draw_runs(x, top + self.u(56), runs, size, fill=fill)
            self.row += 1

    def _heading(self, b: Heading) -> None:
        g = self.g
        size, rows, underline = _HEADING_STYLE[min(b.level, 3)]
        size = self.u(size)
        self._ensure(rows)
        top = self._y()
        baseline = top + (self.u(105) if rows == 2 else self.u(56))
        self.px.text(g.content_x0 + self.u(30), baseline,
                     _fit(b.text, BOLD, size, g.content_w - self.u(60)), size, BOLD)
        if underline:
            self.px.line(g.content_x0 + self.u(30), top + self.u(140),
                         g.content_x1 - self.u(30), top + self.u(140), lw=3.0)
        self.row += rows

    def _list_item(self, b: ListItem) -> None:
        g = self.g
        indent = min(b.depth, 2) * self.u(60)
        mx = g.content_x0 + self.u(30) + indent
        tx = mx + self.u(70)
        lines = wrap_runs(b.segments, self.u(11.0), g.content_x1 - self.u(30) - tx)
        first = True
        for runs in lines:
            self._ensure(1)
            top = self._y()
            if first and b.marker:
                self.px.text(mx, top + self.u(56), b.marker, self.u(11.0), BODY)
            self._draw_runs(tx, top + self.u(56), runs, self.u(11.0))
            first = False
            self.row += 1

    def _checkbox(self, label: str, depth: int, ctype: str) -> None:
        g = self.g
        self._ensure(2)
        top = self._y()
        x0 = g.content_x0 + min(depth, 2) * self.u(60)
        gx, gy, gs = x0 + self.u(40), top + self.u(35), self.glyph_box
        self.px.rect(gx, gy, gs, gs, lw=4.0)
        self.px.line(x0, top + self.u(160), g.content_x1, top + self.u(160),
                     lw=1.5, stroke=FAINT)
        # Long labels wrap onto a second line inside the same 2-row cell;
        # only past two lines does ellipsis truncation kick in.
        tx = gx + self.u(130)
        max_w = g.content_x1 - tx - self.u(30)
        lines = _wrap(label, BODY, self.u(15.0), max_w)
        if len(lines) == 1:
            self.px.text(tx, top + self.u(98), lines[0], self.u(15.0), BODY)
        else:
            if len(lines) > 2:
                lines = [lines[0], _fit(" ".join(lines[1:]), BODY, self.u(15.0), max_w)]
            self.px.text(tx, top + self.u(68), lines[0], self.u(15.0), BODY)
            self.px.text(tx, top + self.u(132), lines[1], self.u(15.0), BODY)
        # Cell = padded glyph box, not the label band: ink from a neighbor
        # row's exuberant checkmark must not read as this cell's answer
        # (device-calibrated 2026-07-20, see DeviceProfile.glyph_pad).
        self._add_cell(
            ctype, label,
            gx - self.glyph_pad, gy - self.glyph_pad,
            self.glyph_box + 2 * self.glyph_pad, self.glyph_box + 2 * self.glyph_pad,
        )
        self.row += 2

    def _choice(self, b: Choice) -> None:
        g = self.g
        # One explicit group id for the whole question (G4), stamped onto every
        # option cell so readback groups on it — not on a parsed label — even
        # when the options straddle a page break below. De-duplicated so two
        # questions sharing a label get distinct groups.
        group = base = f"choice.{_slug(b.label)}"
        n = 2
        while group in self._groups:
            group = f"{base}.{n}"
            n += 1
        self._groups.add(group)
        # Column count follows the widest option (box + gaps + label + pad),
        # so long options get fewer, wider slots instead of ellipses.
        widest = max(width_px(o, BODY, self.u(13.0)) for o in b.options)
        cols = max(1, min(4, len(b.options), int(g.content_w // (widest + self.u(220)))))
        chunks = [b.options[i : i + cols] for i in range(0, len(b.options), cols)]
        slot_w = g.content_w // cols
        self._ensure(min(1 + 2 * len(chunks), self.rows_per_page))
        top = self._y()
        self.px.text(
            g.content_x0 + self.u(30), top + self.u(52),
            _fit(b.label + ":", BODY, self.u(11.0), g.content_w - self.u(60)),
            self.u(11.0), BODY, fill=GRAY,
        )
        self.row += 1
        for chunk in chunks:
            self._ensure(2)
            top = self._y()
            for j, opt in enumerate(chunk):
                sx = g.content_x0 + j * slot_w
                bx, by = sx + self.u(30), top + self.u(35)
                self.px.rect(bx, by, self.glyph_box, self.glyph_box, lw=4.0)
                self.px.text(
                    sx + self.u(150), top + self.u(98),
                    _fit(opt, BODY, self.u(13.0), slot_w - self.u(190)), self.u(13.0), BODY
                )
                self._add_cell(
                    "choice", f"{b.label}: {opt}",
                    bx - self.glyph_pad, by - self.glyph_pad,
                    self.glyph_box + 2 * self.glyph_pad,
                    self.glyph_box + 2 * self.glyph_pad,
                    id_=f"choice.{_slug(b.label)}.{_slug(opt)}",
                    group=group,
                )
            self.row += 2

    def _capture(self, b: Capture) -> None:
        g = self.g
        k = max(2, min(b.rows, self.rows_per_page - 2))
        self._ensure(1 + k)
        top = self._y()
        self.px.text(
            g.content_x0 + self.u(30), top + self.u(52),
            _fit(f"CAPTURE - {b.label} (draw or write below)", BODY, self.u(10.0),
                 g.content_w - self.u(60)),
            self.u(10.0), BODY, fill=GRAY,
        )
        self.row += 1
        capx, capy, capw, caph = g.content_x0, self._y(), g.content_w, k * self.row_h - self.u(20)
        step = max(1, int(self.u(120)))
        for yy in range(int(capy + self.u(120)), int(capy + caph - self.u(30)), step):
            self.px.line(capx + 40, yy, capx + capw - 40, yy, lw=1.5, stroke=FAINT, dash=(2, 4))
        for cx, dx in ((capx, 1), (capx + capw, -1)):
            for cy, dy in ((capy, 1), (capy + caph, -1)):
                self.px.bracket(cx, cy, dx, dy)
        self._add_cell("capture", b.label, capx, capy, capw, caph, id_=f"capture.{_slug(b.label)}")
        self.row += k

    def _code(self, b: CodeBlock) -> None:
        g = self.g
        for raw in b.lines or [""]:
            for ln in _char_wrap(raw, MONO, self.u(9.5), g.content_w - self.u(140)):
                self._ensure(1)
                top = self._y()
                self.px.line(g.content_x0 + 16, top, g.content_x0 + 16, top + self.row_h,
                             lw=4.0, stroke=FAINT)
                self.px.text(g.content_x0 + self.u(70), top + self.u(52), ln, self.u(9.5), MONO)
                self.row += 1

    def _table(self, b: Table) -> None:
        """Column-padded monospace rows; the mono font makes space-padding
        line columns up. Header (first row) gets an underline. Static
        content — no manifest cells."""
        g = self.g
        rows = [r for r in b.rows if r]
        if not rows:
            return
        ncols = max(len(r) for r in rows)
        widths = [0] * ncols
        for r in rows:
            for j, cell in enumerate(r):
                widths[j] = max(widths[j], len(cell))
        for idx, r in enumerate(rows):
            text = "  ".join(
                (r[j] if j < len(r) else "").ljust(widths[j]) for j in range(ncols)
            ).rstrip()
            for ln in _char_wrap(text, MONO, self.u(9.5), g.content_w - self.u(100)):
                self._ensure(1)
                top = self._y()
                self.px.text(g.content_x0 + self.u(50), top + self.u(52), ln, self.u(9.5), MONO)
                if idx == 0:
                    self.px.line(
                        g.content_x0 + self.u(50), top + self.u(66),
                        g.content_x0 + self.u(50) + width_px(ln, MONO, self.u(9.5)),
                        top + self.u(66),
                        lw=1.5, stroke=GRAY,
                    )
                self.row += 1

    def _comb(self, b: Comb) -> None:
        """Comb boxes (0012 F3): n joined character cells. Segmentation
        raises later HWR accuracy; the manifest carries each box's bbox."""
        g = self.g
        box_w, box_h = self.u(110), self.u(130)
        n = max(1, min(b.n, int((g.content_w - self.u(80)) // box_w)))
        self._ensure(3)
        top = self._y()
        self.px.text(
            g.content_x0 + self.u(30), top + self.u(52),
            _fit(b.label + ":", BODY, self.u(11.0), g.content_w - self.u(60)),
            self.u(11.0), BODY, fill=GRAY,
        )
        self.row += 1
        top = self._y()
        cx, cy = g.content_x0 + self.u(40), top + self.u(15)
        self.px.rect(cx, cy, n * box_w, box_h, lw=4.0)
        for j in range(1, n):
            self.px.line(cx + j * box_w, cy, cx + j * box_w, cy + box_h, lw=2.0)
        boxes = [g.norm(cx + j * box_w, cy, box_w, box_h) for j in range(n)]
        self._add_cell(
            "comb", b.label,
            cx - self.u(20), cy - self.u(20), n * box_w + self.u(40), box_h + self.u(40),
            id_=f"comb.{_slug(b.label)}",
            n=n,
            boxes_norm=boxes,
        )
        self.row += 2

    def _rule(self) -> None:
        g = self.g
        self._ensure(1)
        top = self._y()
        self.px.line(g.content_x0 + self.u(30), top + self.u(40),
                     g.content_x1 - self.u(30), top + self.u(40), lw=2.0, stroke=GRAY)
        self.row += 1

    def _placeholder(self, b: Placeholder) -> None:
        g = self.g
        self._ensure(2)
        top = self._y()
        self.px.rect(g.content_x0 + self.u(20), top + self.u(15),
                     g.content_w - self.u(40), self.u(130), lw=2.0, stroke=FAINT)
        self.px.text(g.content_x0 + self.u(60), top + self.u(90),
                     _fit(f"[{b.detail}]", BODY, self.u(10.0), g.content_w - self.u(120)),
                     self.u(10.0), BODY, fill=GRAY)
        self.row += 2
