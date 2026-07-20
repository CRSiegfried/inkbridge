"""Row-grid page geometry for the compose renderer (Analysis 0012 finding 8).

Everything is drawn in device-pixel, top-left-origin coordinates on the
Manta's hardware-confirmed 1920x2560 note canvas; the PDF page is the same
sheet at 1 pt = 4 device px (480x640 pt, 3:4 aspect). Input-area bboxes are
arithmetic over these constants — coordinates are inputs to the renderer,
never recovered from layout output — so a manifest bbox is correct by
construction once the raster round-trip test pins the page-to-canvas scale.
"""

from __future__ import annotations

from reportlab.lib.colors import Color, black

CANVAS_W, CANVAS_H = 1920, 2560
SCALE = 0.25  # 1 pt = 4 device px
PAGE_W_PT, PAGE_H_PT = CANVAS_W * SCALE, CANVAS_H * SCALE

ROW = 80  # base grid row height, device px

CONTENT_X0 = 130
CONTENT_X1 = CANVAS_W - 130
CONTENT_W = CONTENT_X1 - CONTENT_X0  # 1660
CONTENT_TOP = 160

# Footer command strip (Analysis 0012 finding 4). Content stops 40 px above.
STRIP_TOP = 2360
ROWS_PER_PAGE = (STRIP_TOP - 40 - CONTENT_TOP) // ROW  # 27

# Checkbox/ack cell: generous fixed geometry so the coverage threshold is
# calibrated once per template, not per document (0012 finding 8).
CHECK_CELL_W = 400

# Trigger slots: page k's "capture this page" box sits at slot k — the
# positional page-identity fiducial. Fixed command boxes live at the right.
TRIGGER_X0 = 160
TRIGGER_PITCH = 96
TRIGGER_BOX = 64
CMD_X0 = 1400
CMD_PITCH = 160
TRIGGER_SLOTS = (CMD_X0 - 60 - TRIGGER_X0 - TRIGGER_BOX) // TRIGGER_PITCH + 1  # 12

BLACK = black
GRAY = Color(0.55, 0.55, 0.55)
FAINT = Color(0.78, 0.78, 0.78)


def norm(x: float, y: float, w: float, h: float) -> list[float]:
    """Normalized top-left [x, y, w, h] bbox — the convert.targeted contract."""
    return [
        round(x / CANVAS_W, 6),
        round(y / CANVAS_H, 6),
        round(w / CANVAS_W, 6),
        round(h / CANVAS_H, 6),
    ]


class Px:
    """Draw in device-pixel, top-left-origin coordinates on a pt canvas."""

    def __init__(self, c):
        self.c = c

    def rect(self, x, y, w, h, lw=3.0, stroke=BLACK):
        self.c.setLineWidth(lw * SCALE)
        self.c.setStrokeColor(stroke)
        self.c.rect(x * SCALE, (CANVAS_H - y - h) * SCALE, w * SCALE, h * SCALE, stroke=1, fill=0)

    def line(self, x0, y0, x1, y1, lw=2.0, stroke=BLACK, dash=None):
        self.c.setLineWidth(lw * SCALE)
        self.c.setStrokeColor(stroke)
        self.c.setDash(*dash) if dash else self.c.setDash()
        self.c.line(x0 * SCALE, (CANVAS_H - y0) * SCALE, x1 * SCALE, (CANVAS_H - y1) * SCALE)
        self.c.setDash()

    def text(self, x, baseline_y, s, size_pt, font, fill=BLACK):
        self.c.setFont(font, size_pt)
        self.c.setFillColor(fill)
        self.c.drawString(x * SCALE, (CANVAS_H - baseline_y) * SCALE, s)

    def bracket(self, x, y, dx, dy, arm=60, lw=4.0):
        """L-bracket at corner (x, y); dx/dy = +1/-1 point the arms inward."""
        self.line(x, y, x + dx * arm, y, lw=lw)
        self.line(x, y, x, y + dy * arm, lw=lw)
