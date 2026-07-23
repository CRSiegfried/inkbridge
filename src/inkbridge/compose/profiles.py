"""Concrete Supernote device profiles — the per-model canvas/PPI/chrome data
the compose geometry engine (``geometry.DeviceProfile``) is parameterized over.

Kept separate from ``geometry.py`` so the geometry *system* carries no device
literals: a new panel is one more entry here, and a synthetic profile can be
composed against without touching the engine.

Every supported panel is ~300 PPI, so a device pixel is a fixed physical
distance and the shared design constants (row height, glyph boxes, margins)
carry across models — same physical ergonomics for the hand holding the pen.
Only the canvas size, PPI, and chrome envelope (what the reader UI clips at the
bottom of the screen) are per-device, and the envelope is *measured* only where
the inked ruler fixture has been run on real hardware (``chrome_calibrated``).
"""

from __future__ import annotations

from .geometry import DeviceProfile

# Manta (A5 X2, 10.7", 1920x2560 hardware-confirmed; ~299 PPI). Chrome envelope
# measured with the inked ruler fixture (2026-07-20): the reader UI clips the
# bottom *corners* — on the sides the lowest fully visible ruler line is y=2440
# (x~460) — while the center-bottom stays visible to at least y=2540 (x~930).
# So side content must clear side_safe_bottom, and only the center_x0..center_x1
# band may use the deeper center_safe_bottom. Corner registration ticks are
# exempt (compositing-only marks, never meant to be read on screen).
MANTA = DeviceProfile(
    name="manta",
    canvas_w=1920,
    canvas_h=2560,
    ppi=299.1,
    strip_top=2340,
    side_safe_bottom=2420,
    center_safe_bottom=2520,
    center_x0=640,
    center_x1=1280,
    chrome_calibrated=True,
)

# Nomad (A6 X2, 7.8"; ~300 PPI). ASSUMED, no device on hand — community-
# documented 1404x1872 canvas (same 3:4 aspect; note this is the figure that was
# *refuted as the Manta canvas*, so don't cross-wire the two). Chrome envelope
# assumptions, pending an on-device ruler fixture:
#   - same px distances from the bottom edge as the Manta measured (same reader
#     app, same PPI → chrome should be the same physical height):
#     strip_top/side_safe/center_safe = canvas_h - 220/140/40;
#   - center-visible band scaled by width about the centerline
#     (Manta ±320 of the width → ±234 of 1404).
# Anything read back from a real Nomad should replace these numbers and flip
# chrome_calibrated.
NOMAD = DeviceProfile(
    name="nomad",
    canvas_w=1404,
    canvas_h=1872,
    ppi=300.0,
    strip_top=1872 - 220,
    side_safe_bottom=1872 - 140,
    center_safe_bottom=1872 - 40,
    center_x0=702 - 234,
    center_x1=702 + 234,
    chrome_calibrated=False,
)

PROFILES = {p.name: p for p in (MANTA, NOMAD)}
