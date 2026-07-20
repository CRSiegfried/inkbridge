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

from .fonts import BODY, BOLD, ITALIC, register_fonts, width_px
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
    Heading,
    ListItem,
    Paragraph,
    Placeholder,
    Quote,
    Rule,
)

# level -> (size_pt, rows, underline); all headings render bold.
_HEADING_STYLE = {1: (22.0, 2, True), 2: (15.0, 2, False), 3: (12.5, 1, False)}


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
        p = self.px
        p.line(CONTENT_X0, STRIP_TOP, CONTENT_X1, STRIP_TOP, lw=2.0, stroke=GRAY)
        p.text(TRIGGER_X0, STRIP_TOP - 14, "command strip", 7.0, BODY, fill=GRAY)
        p.text(CONTENT_X1 - 60, STRIP_TOP - 14, f"p{self.page}", 7.0, BODY, fill=GRAY)

        # Positional fiducial: page k's trigger box occupies slot k. Pages
        # beyond capacity share the last slot (fiducial_unique=false) and
        # fall back to the observed-ordering assumption (0012 finding 4).
        slot = min(self.page - 1, TRIGGER_SLOTS - 1)
        tx, ty = TRIGGER_X0 + slot * TRIGGER_PITCH, STRIP_TOP + 24
        p.rect(tx, ty, TRIGGER_BOX, TRIGGER_BOX, lw=4.0)
        p.text(tx, STRIP_TOP + 112, "capture pg", 7.0, BODY, fill=GRAY)
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
            p.text(bx, STRIP_TOP + 112, name, 7.0, BODY, fill=GRAY)
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
                self._para_lines(_wrap(b.text, BODY, 11.0, CONTENT_W - 60), CONTENT_X0 + 30)
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
            elif isinstance(b, CodeBlock):
                self._code(b)
            elif isinstance(b, Quote):
                self._para_lines(
                    _wrap(b.text, ITALIC, 11.0, CONTENT_W - 160),
                    CONTENT_X0 + 100, font=ITALIC, bar=True,
                )
            elif isinstance(b, Rule):
                self._rule()
            elif isinstance(b, Placeholder):
                self._placeholder(b)
            self.prev = b
        self._finish_page()
        self.c.save()

    def _para_lines(self, lines, x, size=11.0, font=BODY, fill=BLACK, bar=False) -> None:
        for ln in lines:
            self._ensure(1)
            top = self._y()
            if bar:
                self.px.line(CONTENT_X0 + 16, top, CONTENT_X0 + 16, top + ROW, lw=4.0, stroke=GRAY)
            self.px.text(x, top + 56, ln, size, font, fill=fill)
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
        lines = _wrap(b.text, BODY, 11.0, CONTENT_X1 - 30 - tx)
        first = True
        for ln in lines:
            self._ensure(1)
            top = self._y()
            if first and b.marker:
                self.px.text(mx, top + 56, b.marker, 11.0, BODY)
            self.px.text(tx, top + 56, ln, 11.0, BODY)
            first = False
            self.row += 1

    def _checkbox(self, label: str, depth: int, ctype: str) -> None:
        self._ensure(2)
        top = self._y()
        x0 = CONTENT_X0 + min(depth, 2) * 60
        gx, gy, gs = x0 + 40, top + 35, 90
        self.px.rect(gx, gy, gs, gs, lw=4.0)
        self.px.line(x0, top + 160, CONTENT_X1, top + 160, lw=1.5, stroke=FAINT)
        self.px.text(
            gx + 130, top + 98,
            _fit(label, BODY, 15.0, CONTENT_X1 - (gx + 130) - 30), 15.0, BODY,
        )
        self._add_cell(ctype, label, x0, top, CHECK_CELL_W, 2 * ROW)
        self.row += 2

    def _choice(self, b: Choice) -> None:
        chunks = [b.options[i : i + 4] for i in range(0, len(b.options), 4)]
        slot_w = CONTENT_W // min(len(b.options), 4)
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
                    sx + 150, top + 98, _fit(opt, BODY, 13.0, slot_w - 200), 13.0, BODY
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
            for ln in _char_wrap(raw, BODY, 9.5, CONTENT_W - 140):
                self._ensure(1)
                top = self._y()
                self.px.line(CONTENT_X0 + 16, top, CONTENT_X0 + 16, top + ROW, lw=4.0, stroke=FAINT)
                self.px.text(CONTENT_X0 + 70, top + 52, ln, 9.5, BODY)
                self.row += 1

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
