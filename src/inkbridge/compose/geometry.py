"""Row-grid page geometry for the compose renderer.

Everything is drawn in device-pixel, top-left-origin coordinates on the
target device's note canvas; the PDF page is the same sheet at 1 pt = 4
device px (3:4 aspect on every supported model). Input-area bboxes are
arithmetic over these constants — coordinates are inputs to the renderer,
never recovered from layout output — so a manifest bbox is correct by
construction once the raster round-trip test pins the page-to-canvas scale.

Device profiles: every supported Supernote panel is ~300 PPI, so a device
pixel is a fixed physical distance and the shared design constants (row
height, glyph boxes, margins) carry across models unchanged — same physical
ergonomics for the hand holding the pen. Only the canvas size and the
chrome envelope (what the reader UI clips at the bottom of the screen) are
per-device, and the envelope is *measured* only where we've run the inked
ruler fixture on real hardware (`chrome_calibrated`).
"""

from __future__ import annotations

from dataclasses import dataclass

from reportlab.lib.colors import Color, black

SCALE = 0.25  # 1 pt = 4 device px, fixed across profiles (fonts.py depends on it)

ROW = 80  # base grid row height, device px (~300 PPI: a physical size)


@dataclass(frozen=True)
class DeviceProfile:
    """Canvas size and chrome envelope for one Supernote model."""

    name: str
    canvas_w: int
    canvas_h: int
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

    # Shared design constants — physical sizes, identical across ~300 PPI
    # panels. Overridable per-profile but expected to stay put.
    margin_x: int = 130
    content_top: int = 160
    glyph_box: int = 90  # tickable printed box (checkbox/ack/choice)
    glyph_pad: int = 20  # manifest cell = box + pad (first device calibration)
    trigger_box: int = 64  # page-level AI-parse trigger, centered per page

    @property
    def page_w_pt(self) -> float:
        return self.canvas_w * SCALE

    @property
    def page_h_pt(self) -> float:
        return self.canvas_h * SCALE

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
        return (self.strip_top - 40 - self.content_top) // ROW

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


# Manta (A5 X2, 10.7", 1920x2560 hardware-confirmed). Chrome envelope
# measured with the inked ruler fixture (2026-07-20): the reader UI clips
# the bottom *corners* — on the sides the lowest fully visible ruler line
# is y=2440 (x~460) — while the center-bottom stays visible to at least
# y=2540 (x~930). So side content must clear side_safe_bottom, and only
# the center_x0..center_x1 band may use the deeper center_safe_bottom.
# Corner registration ticks are exempt (compositing-only marks, never
# meant to be read on screen).
MANTA = DeviceProfile(
    name="manta",
    canvas_w=1920,
    canvas_h=2560,
    strip_top=2340,
    side_safe_bottom=2420,
    center_safe_bottom=2520,
    center_x0=640,
    center_x1=1280,
    chrome_calibrated=True,
)

# Nomad (A6 X2, 7.8"). ASSUMED, no device on hand — community-documented
# 1404x1872 canvas (same 3:4 aspect, ~300 PPI; note this is the figure that
# was *refuted as the Manta canvas*, so don't cross-wire the two). Chrome
# envelope assumptions, pending an on-device ruler fixture:
#   - same px distances from the bottom edge as the Manta measured (same
#     reader app, same PPI → chrome should be the same physical height):
#     strip_top/side_safe/center_safe = canvas_h - 220/140/40;
#   - center-visible band scaled by width about the centerline
#     (Manta ±320 of 1920 → ±234 of 1404).
# Anything read back from a real Nomad should replace these numbers and
# flip chrome_calibrated.
NOMAD = DeviceProfile(
    name="nomad",
    canvas_w=1404,
    canvas_h=1872,
    strip_top=1872 - 220,
    side_safe_bottom=1872 - 140,
    center_safe_bottom=1872 - 40,
    center_x0=702 - 234,
    center_x1=702 + 234,
    chrome_calibrated=False,
)

PROFILES = {p.name: p for p in (MANTA, NOMAD)}

BLACK = black
GRAY = Color(0.55, 0.55, 0.55)
FAINT = Color(0.78, 0.78, 0.78)


class Px:
    """Draw in device-pixel, top-left-origin coordinates on a pt canvas."""

    def __init__(self, c, profile: DeviceProfile):
        self.c = c
        self.h = profile.canvas_h

    def rect(self, x, y, w, h, lw=3.0, stroke=BLACK):
        self.c.setLineWidth(lw * SCALE)
        self.c.setStrokeColor(stroke)
        self.c.rect(x * SCALE, (self.h - y - h) * SCALE, w * SCALE, h * SCALE, stroke=1, fill=0)

    def line(self, x0, y0, x1, y1, lw=2.0, stroke=BLACK, dash=None):
        self.c.setLineWidth(lw * SCALE)
        self.c.setStrokeColor(stroke)
        self.c.setDash(*dash) if dash else self.c.setDash()
        self.c.line(x0 * SCALE, (self.h - y0) * SCALE, x1 * SCALE, (self.h - y1) * SCALE)
        self.c.setDash()

    def text(self, x, baseline_y, s, size_pt, font, fill=BLACK):
        self.c.setFont(font, size_pt)
        self.c.setFillColor(fill)
        self.c.drawString(x * SCALE, (self.h - baseline_y) * SCALE, s)

    def bracket(self, x, y, dx, dy, arm=60, lw=4.0):
        """L-bracket at corner (x, y); dx/dy = +1/-1 point the arms inward."""
        self.line(x, y, x + dx * arm, y, lw=lw)
        self.line(x, y, x, y + dy * arm, lw=lw)
