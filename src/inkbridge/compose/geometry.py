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
# Device chrome, measured with the inked ruler fixture (2026-07-20): the
# reader UI clips the bottom *corners* — on the sides the lowest fully
# visible ruler line is y=2440 (x~460) — while the center-bottom stays
# visible to at least y=2540 (x~930). So side content must clear
# SIDE_SAFE_BOTTOM, and only the CENTER_X0..CENTER_X1 band may use the
# deeper CENTER_SAFE_BOTTOM. Corner registration ticks are exempt
# (compositing-only marks, never meant to be read on screen).
STRIP_TOP = 2340
SIDE_SAFE_BOTTOM = 2420
CENTER_SAFE_BOTTOM = 2520
CENTER_X0 = 640
CENTER_X1 = 1280
ROWS_PER_PAGE = (STRIP_TOP - 40 - CONTENT_TOP) // ROW  # 26

# Tickable glyph boxes (checkbox/ack/choice): the manifest cell is the
# printed box plus GLYPH_PAD, not the full label band. Calibrated on the
# first device sampler (2026-07-20): a flamboyant checkmark's tail sweeping
# through the *neighboring* row read 0.63% over the old full-width band (a
# false ANSWERED) but exactly 0.0000 over the padded box, while real
# in-box checks read 4-8%. The box is the affordance; ink must touch it.
GLYPH_BOX = 90
GLYPH_PAD = 20

# Trigger slots: page k's "capture this page" box sits at slot k — the
# positional page-identity fiducial. Slots are laid out CENTER-OUT within
# the measured center-visible band: slot 0 dead center (so a one-page
# document's box is centered on the page), then alternating right/left at
# TRIGGER_PITCH steps. The fixed command boxes (done/remind/archive) were
# dropped 2026-07-20 — read but unused, and the corner chrome clipped
# them. Re-add inside the center band if they ever gain behavior.
TRIGGER_PITCH = 96
TRIGGER_BOX = 64
TRIGGER_CENTER_X0 = (CANVAS_W - TRIGGER_BOX) // 2  # 928
TRIGGER_SLOTS = (CENTER_X1 - CENTER_X0 - TRIGGER_BOX) // TRIGGER_PITCH + 1  # 7


def trigger_slot_x0(slot: int) -> int:
    """Left edge of a trigger slot's box: center-out, 0,+1,-1,+2,-2,…×pitch.
    Every offset stays inside CENTER_X0..CENTER_X1 for slot < TRIGGER_SLOTS.
    """
    k = (slot + 1) // 2
    return TRIGGER_CENTER_X0 + (k if slot % 2 == 1 else -k) * TRIGGER_PITCH

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
