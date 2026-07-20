"""Compositing alignment tests (Analysis 0012 finding 5).

No device mark file here: the alignment claim is that mark-space
coordinates (1920×2560, top-left origin) land on the same spot in the
rendered base page. Synthetic ink drawn at the compose template's corner
registration ticks must therefore overlay the rendered ticks — if the
page-to-canvas scale or origin were off, the overlap collapses.
"""

from __future__ import annotations

import numpy as np
import pytest

from inkbridge.compose import compose
from inkbridge.composite import (
    CANVAS_H,
    CANVAS_W,
    composite_arrays,
    render_base_page,
)

# Corner ticks as drawn by Renderer._start_page: L-brackets at 40 px from
# each canvas corner, arms (length 40) pointing inward.
CORNERS = ((40, 40, 1, 1), (CANVAS_W - 40, 40, -1, 1),
           (40, CANVAS_H - 40, 1, -1), (CANVAS_W - 40, CANVAS_H - 40, -1, -1))
ARM = 40


def synthetic_tick_ink() -> np.ndarray:
    """A mark-space page whose only ink retraces the corner brackets."""
    ink = np.full((CANVAS_H, CANVAS_W), 255, dtype=np.uint8)
    for x, y, dx, dy in CORNERS:
        x2 = x + dx * ARM
        y2 = y + dy * ARM
        ink[y - 1 : y + 2, min(x, x2) : max(x, x2)] = 0   # horizontal arm
        ink[min(y, y2) : max(y, y2), x - 1 : x + 2] = 0   # vertical arm
    return ink


@pytest.fixture(scope="module")
def base_page(tmp_path_factory) -> np.ndarray:
    out = tmp_path_factory.mktemp("composite") / "doc.pdf"
    compose("# Alignment\n\nSome content.\n", out)
    return render_base_page(out, 1)


def test_base_renders_at_canvas_size(base_page):
    assert base_page.shape == (CANVAS_H, CANVAS_W, 3)


def test_ticks_align_with_mark_space(base_page):
    ink = synthetic_tick_ink()
    base_gray = base_page.min(axis=2)
    ink_mask = ink < 200
    base_dark = base_gray < 128

    # Most synthetic ink pixels must land on already-dark base pixels —
    # the rendered ticks. Rasterization may differ by a pixel of
    # anti-aliasing, hence not 100%.
    overlap = (ink_mask & base_dark).sum() / ink_mask.sum()
    assert overlap > 0.5, f"tick overlap only {overlap:.1%} — scale/origin drift"

    # And per corner, the centroids of base ink vs synthetic ink agree to
    # within 2 px in a clean window around the bracket.
    for x, y, _, _ in CORNERS:
        y0, y1 = max(0, y - 45), y + 45
        x0, x1 = max(0, x - 45), x + 45
        b = np.argwhere(base_dark[y0:y1, x0:x1])
        s = np.argwhere(ink_mask[y0:y1, x0:x1])
        assert len(b) and len(s)
        drift = np.abs(b.mean(axis=0) - s.mean(axis=0))
        assert (drift < 2).all(), f"corner ({x},{y}) centroid drift {drift}"


def test_composite_paints_only_ink_pixels(base_page):
    ink = synthetic_tick_ink()
    out = composite_arrays(base_page, ink, ink_color=(255, 0, 0))
    mask = ink < 200
    assert (out[mask] == (255, 0, 0)).all()
    assert (out[~mask] == base_page[~mask]).all()
    # input untouched
    assert not (base_page[mask] == (255, 0, 0)).all()


def test_composite_refuses_shape_mismatch(base_page):
    with pytest.raises(ValueError, match="refusing to resample"):
        composite_arrays(base_page, np.full((100, 100), 255, dtype=np.uint8))


def test_render_base_page_rejects_wrong_aspect(tmp_path):
    from reportlab.pdfgen import canvas as rl_canvas

    pdf = tmp_path / "square.pdf"
    c = rl_canvas.Canvas(str(pdf), pagesize=(400, 400))
    c.showPage()
    c.save()
    with pytest.raises(ValueError, match="device canvas"):
        render_base_page(pdf, 1)
