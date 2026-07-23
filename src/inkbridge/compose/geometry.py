"""Row-grid page geometry for the compose renderer — the device-independent
engine. Concrete panels live in ``profiles.py``.

Everything is drawn in device-pixel, top-left-origin coordinates on the target
device's note canvas; the PDF page is the same sheet at ``pt_per_px`` pt per
device pixel (1 pt = 4 px by default), whatever the canvas aspect. Input-area
bboxes are arithmetic over the profile's fields — coordinates are inputs to the
renderer, never recovered from layout output — so a manifest bbox is correct by
construction once the raster round-trip test pins the page-to-canvas scale.

A :class:`DeviceProfile` carries the panel's canvas size, PPI, pt→px scale, and
chrome envelope; the shared design sizes (row height, glyph boxes, margins) are
physical, so they carry across ~300 PPI panels — ``row_h`` derives from a
physical millimetre target and the profile's PPI rather than a fixed pixel
count. Nothing here is Manta-specific, so a synthetic non-Manta profile
(different PPI or aspect) composes with no module constant to patch.
"""

from __future__ import annotations

from dataclasses import dataclass

from reportlab.lib.colors import Color, black

# The pt→px scale is a rendering convention (1 pt = 4 device px), not a device
# geometry constant, so it defaults the same on every profile; it lives on
# DeviceProfile (a profile could override it) with this module default reused by
# the profile-free text measurement in fonts.py.
PT_PER_PX = 0.25

# Physical millimetre target for one grid row. row_h is derived from this and
# the profile's PPI, so the row is the same physical size on any panel (~6.8 mm
# → 80 px at ~300 PPI) rather than a fixed pixel count that would shrink on a
# denser screen.
ROW_MM = 6.8
MM_PER_INCH = 25.4


@dataclass(frozen=True)
class DeviceProfile:
    """Canvas size, pixel density, and chrome envelope for one panel. Everything
    the renderer needs is derived from these fields, so a non-Manta profile
    (different PPI or aspect) composes correctly with no module-scope constant to
    patch — the concrete device instances live in ``profiles.py``."""

    name: str
    canvas_w: int
    canvas_h: int
    ppi: float  # pixel density; row height and any physical size derive from it
    # Footer command strip / chrome envelope, absolute canvas y (top-origin).
    strip_top: int
    side_safe_bottom: int
    center_safe_bottom: int
    # The center-bottom band the reader UI leaves visible below
    # side_safe_bottom; the centered trigger box must stay inside it.
    center_x0: int
    center_x1: int
    # True only when the envelope came from the on-device ruler fixture.
    chrome_calibrated: bool

    # Rendering + design constants. pt_per_px is the pt→px scale; row_mm the
    # physical row target (row_h derives from it and ppi). The glyph/margin
    # sizes are physical, ~identical across ~300 PPI panels, overridable.
    pt_per_px: float = PT_PER_PX
    row_mm: float = ROW_MM
    margin_x: int = 130
    content_top: int = 160
    glyph_box: int = 90  # tickable printed box (checkbox/ack/choice)
    glyph_pad: int = 20  # manifest cell = box + pad (first device calibration)
    trigger_box: int = 64  # page-level AI-parse trigger, centered per page

    @property
    def row_h(self) -> int:
        """Grid row height in device px, derived from the physical row target
        and this profile's PPI (so it is the same physical size on any panel)."""
        return round(self.row_mm / MM_PER_INCH * self.ppi)

    @property
    def page_w_pt(self) -> float:
        return self.canvas_w * self.pt_per_px

    @property
    def page_h_pt(self) -> float:
        return self.canvas_h * self.pt_per_px

    @property
    def content_x0(self) -> int:
        return self.margin_x

    @property
    def content_x1(self) -> int:
        return self.canvas_w - self.margin_x

    @property
    def content_w(self) -> int:
        return self.content_x1 - self.content_x0

    @property
    def rows_per_page(self) -> int:
        # Content stops 40 px above the command strip.
        return (self.strip_top - 40 - self.content_top) // self.row_h

    @property
    def trigger_center_x0(self) -> int:
        """Left edge of the trigger box, horizontally centered. The box is
        the same on every page — it carries no page identity (that is
        positional; a fiducial can't survive the isolated-ink readback)."""
        return (self.canvas_w - self.trigger_box) // 2

    def norm(self, x: float, y: float, w: float, h: float) -> list[float]:
        """Normalized top-left [x, y, w, h] bbox — the convert.targeted contract."""
        return [
            round(x / self.canvas_w, 6),
            round(y / self.canvas_h, 6),
            round(w / self.canvas_w, 6),
            round(h / self.canvas_h, 6),
        ]


BLACK = black
GRAY = Color(0.55, 0.55, 0.55)
FAINT = Color(0.78, 0.78, 0.78)


class Px:
    """Draw in device-pixel, top-left-origin coordinates on a pt canvas."""

    def __init__(self, c, profile: DeviceProfile):
        self.c = c
        self.h = profile.canvas_h
        self.s = profile.pt_per_px  # pt→px scale for this profile

    def rect(self, x, y, w, h, lw=3.0, stroke=BLACK):
        self.c.setLineWidth(lw * self.s)
        self.c.setStrokeColor(stroke)
        self.c.rect(x * self.s, (self.h - y - h) * self.s, w * self.s, h * self.s, stroke=1, fill=0)

    def line(self, x0, y0, x1, y1, lw=2.0, stroke=BLACK, dash=None):
        self.c.setLineWidth(lw * self.s)
        self.c.setStrokeColor(stroke)
        self.c.setDash(*dash) if dash else self.c.setDash()
        self.c.line(x0 * self.s, (self.h - y0) * self.s, x1 * self.s, (self.h - y1) * self.s)
        self.c.setDash()

    def text(self, x, baseline_y, s, size_pt, font, fill=BLACK):
        self.c.setFont(font, size_pt)
        self.c.setFillColor(fill)
        self.c.drawString(x * self.s, (self.h - baseline_y) * self.s, s)

    def bracket(self, x, y, dx, dy, arm=60, lw=4.0):
        """L-bracket at corner (x, y); dx/dy = +1/-1 point the arms inward."""
        self.line(x, y, x + dx * arm, y, lw=lw)
        self.line(x, y, x, y + dy * arm, lw=lw)
