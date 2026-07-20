"""Row-grid renderer: block IR → PDF + manifest cells (Analysis 0012 F8–F9).

A single imperative pass deals blocks onto uniform 80 px rows top-to-bottom,
drawing content and the footer command strip together and recording every
input-area bbox as row arithmetic. Greedy word-wrap uses the pinned embedded
font's own metrics (fonts.py), so measurement and drawing can never drift
apart. The canvas is opened with invariant=1: identical input produces
byte-identical PDFs.
"""

from __future__ import annotations

import re
from pathlib import Path

from reportlab.pdfgen import canvas as rl_canvas

from .fonts import BODY, BOLD, BOLDITALIC, ITALIC, MONO, register_fonts, width_px
from .geometry import (
    BLACK,
    CANVAS_H,
    CANVAS_W,
    CHECK_CELL_W,
    CMD_PITCH,
    CMD_X0,
    CONTENT_TOP,
    CONTENT_W,
    CONTENT_X0,
    CONTENT_X1,
    FAINT,
    GRAY,
    PAGE_H_PT,
    PAGE_W_PT,
    ROW,
    ROWS_PER_PAGE,
    STRIP_TOP,
    TRIGGER_BOX,
    TRIGGER_PITCH,
    TRIGGER_SLOTS,
    TRIGGER_X0,
    Px,
    norm,
)
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
    Slider,
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
    def __init__(self, pdf_path: Path):
        register_fonts()
        self.c = rl_canvas.Canvas(
            str(pdf_path), pagesize=(PAGE_W_PT, PAGE_H_PT), invariant=1
        )
        self.px = Px(self.c)
        self.cells: list[dict] = []
        self._ids: set[str] = set()
        self.page = 0
        self.row = 0
        self.prev = None
        self._start_page()

    # -- page machinery ----------------------------------------------------

    def _y(self, row: int | None = None) -> int:
        return CONTENT_TOP + (self.row if row is None else row) * ROW

    def _start_page(self) -> None:
        self.page += 1
        self.row = 0
        # Corner registration ticks — compositing/alignment aid.
        for cx, dx in ((40, 1), (CANVAS_W - 40, -1)):
            for cy, dy in ((40, 1), (CANVAS_H - 40, -1)):
                self.px.bracket(cx, cy, dx, dy, arm=40, lw=3.0)

    def _finish_page(self) -> None:
        self._draw_strip()
        self.c.showPage()

    def _ensure(self, rows: int) -> None:
        if ROWS_PER_PAGE - self.row < rows:
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
                "bbox_norm": norm(x, y, w, h),
                **extra,
            }
        )

    def _draw_strip(self) -> None:
        # Everything (labels above the boxes, then the boxes) must clear
        # STRIP_SAFE_BOTTOM: the device reader UI covers the canvas below
        # it, which hid the old under-box labels entirely.
        p = self.px
        p.line(CONTENT_X0, STRIP_TOP, CONTENT_X1, STRIP_TOP, lw=2.0, stroke=GRAY)
        p.text(TRIGGER_X0, STRIP_TOP - 14, "command strip", 7.0, BODY, fill=GRAY)
        p.text(CONTENT_X1 - 60, STRIP_TOP - 14, f"p{self.page}", 7.0, BODY, fill=GRAY)
        label_y = STRIP_TOP + 38
        ty = STRIP_TOP + 52

        # Positional fiducial: page k's trigger box occupies slot k. Pages
        # beyond capacity share the last slot (fiducial_unique=false) and
        # fall back to the observed-ordering assumption (0012 finding 4).
        slot = min(self.page - 1, TRIGGER_SLOTS - 1)
        tx = TRIGGER_X0 + slot * TRIGGER_PITCH
        p.rect(tx, ty, TRIGGER_BOX, TRIGGER_BOX, lw=4.0)
        p.text(tx, label_y, "capture pg", 7.0, BODY, fill=GRAY)
        self._add_cell(
            "capture_trigger",
            f"capture page {self.page}",
            tx - 16, ty - 16, TRIGGER_BOX + 32, TRIGGER_BOX + 32,
            id_=f"cmd.capture.p{self.page}",
            slot=slot,
            fiducial_unique=self.page <= TRIGGER_SLOTS,
        )
        for j, name in enumerate(("done", "remind", "archive")):
            bx = CMD_X0 + j * CMD_PITCH
            p.rect(bx, ty, TRIGGER_BOX, TRIGGER_BOX, lw=4.0)
            p.text(bx, label_y, name, 7.0, BODY, fill=GRAY)
            self._add_cell(
                "command", name,
                bx - 16, ty - 16, TRIGGER_BOX + 32, TRIGGER_BOX + 32,
                id_=f"cmd.{name}.p{self.page}",
            )

    # -- block renderers ---------------------------------------------------

    def render(self, blocks: list) -> None:
        for b in blocks:
            self._gap(b)
            if isinstance(b, Heading):
                self._heading(b)
            elif isinstance(b, Paragraph):
                self._para_lines(
                    wrap_runs(b.segments, 11.0, CONTENT_W - 60), CONTENT_X0 + 30)
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
            elif isinstance(b, Slider):
                self._slider(b)
            elif isinstance(b, Comb):
                self._comb(b)
            elif isinstance(b, CodeBlock):
                self._code(b)
            elif isinstance(b, Table):
                self._table(b)
            elif isinstance(b, Quote):
                self._para_lines(
                    wrap_runs(b.segments, 11.0, CONTENT_W - 160, _QUOTE_FONTS),
                    CONTENT_X0 + 100, bar=True,
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
        """Deal wrapped lines of draw runs onto rows."""
        for runs in lines:
            self._ensure(1)
            top = self._y()
            if bar:
                self.px.line(CONTENT_X0 + 16, top, CONTENT_X0 + 16, top + ROW, lw=4.0, stroke=GRAY)
            self._draw_runs(x, top + 56, runs, size, fill=fill)
            self.row += 1

    def _heading(self, b: Heading) -> None:
        size, rows, underline = _HEADING_STYLE[min(b.level, 3)]
        self._ensure(rows)
        top = self._y()
        baseline = top + (105 if rows == 2 else 56)
        self.px.text(CONTENT_X0 + 30, baseline, _fit(b.text, BOLD, size, CONTENT_W - 60), size, BOLD)
        if underline:
            self.px.line(CONTENT_X0 + 30, top + 140, CONTENT_X1 - 30, top + 140, lw=3.0)
        self.row += rows

    def _list_item(self, b: ListItem) -> None:
        indent = min(b.depth, 2) * 60
        mx = CONTENT_X0 + 30 + indent
        tx = mx + 70
        lines = wrap_runs(b.segments, 11.0, CONTENT_X1 - 30 - tx)
        first = True
        for runs in lines:
            self._ensure(1)
            top = self._y()
            if first and b.marker:
                self.px.text(mx, top + 56, b.marker, 11.0, BODY)
            self._draw_runs(tx, top + 56, runs, 11.0)
            first = False
            self.row += 1

    def _checkbox(self, label: str, depth: int, ctype: str) -> None:
        self._ensure(2)
        top = self._y()
        x0 = CONTENT_X0 + min(depth, 2) * 60
        gx, gy, gs = x0 + 40, top + 35, 90
        self.px.rect(gx, gy, gs, gs, lw=4.0)
        self.px.line(x0, top + 160, CONTENT_X1, top + 160, lw=1.5, stroke=FAINT)
        # Long labels wrap onto a second line inside the same 2-row cell;
        # only past two lines does ellipsis truncation kick in.
        tx = gx + 130
        max_w = CONTENT_X1 - tx - 30
        lines = _wrap(label, BODY, 15.0, max_w)
        if len(lines) == 1:
            self.px.text(tx, top + 98, lines[0], 15.0, BODY)
        else:
            if len(lines) > 2:
                lines = [lines[0], _fit(" ".join(lines[1:]), BODY, 15.0, max_w)]
            self.px.text(tx, top + 68, lines[0], 15.0, BODY)
            self.px.text(tx, top + 132, lines[1], 15.0, BODY)
        self._add_cell(ctype, label, x0, top, CHECK_CELL_W, 2 * ROW)
        self.row += 2

    def _choice(self, b: Choice) -> None:
        # Column count follows the widest option (box + gaps + label + pad),
        # so long options get fewer, wider slots instead of ellipses.
        widest = max(width_px(o, BODY, 13.0) for o in b.options)
        cols = max(1, min(4, len(b.options), int(CONTENT_W // (widest + 220))))
        chunks = [b.options[i : i + cols] for i in range(0, len(b.options), cols)]
        slot_w = CONTENT_W // cols
        self._ensure(min(1 + 2 * len(chunks), ROWS_PER_PAGE))
        top = self._y()
        self.px.text(
            CONTENT_X0 + 30, top + 52,
            _fit(b.label + ":", BODY, 11.0, CONTENT_W - 60), 11.0, BODY, fill=GRAY,
        )
        self.row += 1
        for chunk in chunks:
            self._ensure(2)
            top = self._y()
            for j, opt in enumerate(chunk):
                sx = CONTENT_X0 + j * slot_w
                self.px.rect(sx + 30, top + 35, 90, 90, lw=4.0)
                self.px.text(
                    sx + 150, top + 98, _fit(opt, BODY, 13.0, slot_w - 190), 13.0, BODY
                )
                self._add_cell(
                    "choice", f"{b.label}: {opt}",
                    sx + 10, top + 5, slot_w - 40, 150,
                    id_=f"choice.{_slug(b.label)}.{_slug(opt)}",
                )
            self.row += 2

    def _capture(self, b: Capture) -> None:
        k = max(2, min(b.rows, ROWS_PER_PAGE - 2))
        self._ensure(1 + k)
        top = self._y()
        self.px.text(
            CONTENT_X0 + 30, top + 52,
            _fit(f"CAPTURE - {b.label} (draw or write below)", BODY, 10.0, CONTENT_W - 60),
            10.0, BODY, fill=GRAY,
        )
        self.row += 1
        capx, capy, capw, caph = CONTENT_X0, self._y(), CONTENT_W, k * ROW - 20
        for yy in range(capy + 120, capy + caph - 30, 120):
            self.px.line(capx + 40, yy, capx + capw - 40, yy, lw=1.5, stroke=FAINT, dash=(2, 4))
        for cx, dx in ((capx, 1), (capx + capw, -1)):
            for cy, dy in ((capy, 1), (capy + caph, -1)):
                self.px.bracket(cx, cy, dx, dy)
        self._add_cell("capture", b.label, capx, capy, capw, caph, id_=f"capture.{_slug(b.label)}")
        self.row += k

    def _code(self, b: CodeBlock) -> None:
        for raw in b.lines or [""]:
            for ln in _char_wrap(raw, MONO, 9.5, CONTENT_W - 140):
                self._ensure(1)
                top = self._y()
                self.px.line(CONTENT_X0 + 16, top, CONTENT_X0 + 16, top + ROW, lw=4.0, stroke=FAINT)
                self.px.text(CONTENT_X0 + 70, top + 52, ln, 9.5, MONO)
                self.row += 1

    def _table(self, b: Table) -> None:
        """Column-padded monospace rows; the mono font makes space-padding
        line columns up. Header (first row) gets an underline. Static
        content — no manifest cells."""
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
            for ln in _char_wrap(text, MONO, 9.5, CONTENT_W - 100):
                self._ensure(1)
                top = self._y()
                self.px.text(CONTENT_X0 + 50, top + 52, ln, 9.5, MONO)
                if idx == 0:
                    self.px.line(
                        CONTENT_X0 + 50, top + 66,
                        CONTENT_X0 + 50 + width_px(ln, MONO, 9.5), top + 66,
                        lw=1.5, stroke=GRAY,
                    )
                self.row += 1

    def _slider(self, b: Slider) -> None:
        """Analog slider (0012 F3, geometric tier): a printed track line;
        readback maps the ink centroid's x-position along the track to a
        continuous 0..1 value. The manifest cell carries the track span."""
        self._ensure(3)
        top = self._y()
        self.px.text(
            CONTENT_X0 + 30, top + 52,
            _fit(b.label + ":", BODY, 11.0, CONTENT_W - 60), 11.0, BODY, fill=GRAY,
        )
        self.row += 1
        top = self._y()
        tx0, tx1 = CONTENT_X0 + 80, CONTENT_X1 - 80
        ty = top + 70
        self.px.line(tx0, ty, tx1, ty, lw=3.0)
        for x in (tx0, tx1):
            self.px.line(x, ty - 30, x, ty + 30, lw=3.0)
        if b.left:
            self.px.text(tx0, top + 145, _fit(b.left, BODY, 8.5, 400), 8.5, BODY, fill=GRAY)
        if b.right:
            right = _fit(b.right, BODY, 8.5, 400)
            self.px.text(
                tx1 - width_px(right, BODY, 8.5), top + 145, right, 8.5, BODY, fill=GRAY)
        self._add_cell(
            "slider", b.label,
            CONTENT_X0, top, CONTENT_W, 2 * ROW,
            id_=f"slider.{_slug(b.label)}",
            track_norm={
                "x0": round(tx0 / CANVAS_W, 6),
                "x1": round(tx1 / CANVAS_W, 6),
                "y": round(ty / CANVAS_H, 6),
            },
        )
        self.row += 2

    def _comb(self, b: Comb) -> None:
        """Comb boxes (0012 F3): n joined character cells. Segmentation
        raises later HWR accuracy; the manifest carries each box's bbox."""
        box_w, box_h = 110, 130
        n = max(1, min(b.n, (CONTENT_W - 80) // box_w))
        self._ensure(3)
        top = self._y()
        self.px.text(
            CONTENT_X0 + 30, top + 52,
            _fit(b.label + ":", BODY, 11.0, CONTENT_W - 60), 11.0, BODY, fill=GRAY,
        )
        self.row += 1
        top = self._y()
        cx, cy = CONTENT_X0 + 40, top + 15
        self.px.rect(cx, cy, n * box_w, box_h, lw=4.0)
        for j in range(1, n):
            self.px.line(cx + j * box_w, cy, cx + j * box_w, cy + box_h, lw=2.0)
        boxes = [norm(cx + j * box_w, cy, box_w, box_h) for j in range(n)]
        self._add_cell(
            "comb", b.label,
            cx - 20, cy - 20, n * box_w + 40, box_h + 40,
            id_=f"comb.{_slug(b.label)}",
            n=n,
            boxes_norm=boxes,
        )
        self.row += 2

    def _rule(self) -> None:
        self._ensure(1)
        top = self._y()
        self.px.line(CONTENT_X0 + 30, top + 40, CONTENT_X1 - 30, top + 40, lw=2.0, stroke=GRAY)
        self.row += 1

    def _placeholder(self, b: Placeholder) -> None:
        self._ensure(2)
        top = self._y()
        self.px.rect(CONTENT_X0 + 20, top + 15, CONTENT_W - 40, 130, lw=2.0, stroke=FAINT)
        self.px.text(CONTENT_X0 + 60, top + 90, _fit(f"[{b.detail}]", BODY, 10.0, CONTENT_W - 120), 10.0, BODY, fill=GRAY)
        self.row += 2
