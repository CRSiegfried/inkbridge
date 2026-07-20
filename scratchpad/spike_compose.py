"""Compose spike (Analysis 0012, findings 8-9): render one row-grid page
with checkbox cells, a capture field, and a command strip; emit the bbox
manifest; then verify the geometry round-trip by rasterizing the PDF at the
device canvas resolution (1920x2560) and checking every drawn glyph lands
inside its manifest bbox as mapped by convert.targeted._bbox_to_pixels.

Run:  uv run --with reportlab --with pypdfium2 python scratchpad/spike_compose.py
"""

from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib.colors import Color, black
from reportlab.pdfgen import canvas as rl_canvas

from inkbridge.convert.targeted import _bbox_to_pixels

# Device canvas (hardware-confirmed Manta note canvas) and PDF page scale.
# 1 pt = 4 device px, so the page is 480x640 pt at the same 3:4 aspect.
W, H = 1920, 2560
S = 0.25
ROW = 80  # base grid row height, device px

OUT = Path(__file__).parent
PDF_PATH = OUT / "spike_001.pdf"
MANIFEST_PATH = OUT / "spike_001.manifest.json"
PREVIEW_PATH = OUT / "spike_001_preview.png"

GRAY = Color(0.55, 0.55, 0.55)
FAINT = Color(0.78, 0.78, 0.78)

cells: list[dict] = []   # manifest cells (normalized bboxes)
glyphs: dict[str, tuple[int, int, int, int]] = {}  # cell id -> drawn glyph rect, device px


def norm(x: float, y: float, w: float, h: float) -> list[float]:
    return [round(x / W, 6), round(y / H, 6), round(w / W, 6), round(h / H, 6)]


class Px:
    """Draw in device-pixel, top-left-origin coordinates on a pt canvas."""

    def __init__(self, c: rl_canvas.Canvas):
        self.c = c

    def rect(self, x, y, w, h, lw=3.0, stroke=black):
        self.c.setLineWidth(lw * S)
        self.c.setStrokeColor(stroke)
        self.c.rect(x * S, (H - y - h) * S, w * S, h * S, stroke=1, fill=0)

    def line(self, x0, y0, x1, y1, lw=2.0, stroke=black, dash=None):
        self.c.setLineWidth(lw * S)
        self.c.setStrokeColor(stroke)
        self.c.setDash(*dash) if dash else self.c.setDash()
        self.c.line(x0 * S, (H - y0) * S, x1 * S, (H - y1) * S)
        self.c.setDash()

    def text(self, x, baseline_y, s, size_pt=16, fill=black, font="Helvetica"):
        self.c.setFont(font, size_pt)
        self.c.setFillColor(fill)
        self.c.drawString(x * S, (H - baseline_y) * S, s)

    def bracket(self, x, y, dx, dy, arm=60, lw=4.0):
        """L-bracket at corner (x, y); dx/dy = +1/-1 point the arms inward."""
        self.line(x, y, x + dx * arm, y, lw=lw)
        self.line(x, y, x, y + dy * arm, lw=lw)


def add_cell(cid, ctype, label, x, y, w, h, glyph_rect=None):
    cells.append(
        {"id": cid, "page": 1, "type": ctype, "label": label, "bbox_norm": norm(x, y, w, h)}
    )
    if glyph_rect:
        glyphs[cid] = glyph_rect


def render() -> None:
    c = rl_canvas.Canvas(str(PDF_PATH), pagesize=(W * S, H * S))
    p = Px(c)

    # Corner registration ticks (visual aid for compositing checks only).
    for cx, dx in ((40, 1), (W - 40, -1)):
        for cy, dy in ((40, 1), (H - 40, -1)):
            p.bracket(cx, cy, dx, dy, arm=40, lw=3.0)

    # Title block.
    p.text(160, 140, "INKBRIDGE SPIKE 001", size_pt=20)
    p.line(160, 175, W - 160, 175, lw=3.0)
    p.text(160, 262, "Check any of these:", size_pt=11, fill=GRAY)

    # Checkbox rows: cell = 2 grid rows (160 px) tall, generous 400 px wide
    # (matches the calibrated 0009 fixture generosity). Glyph = 90x90 box.
    items = [("check_milk", "milk"), ("check_eggs", "eggs"), ("check_coffee", "coffee")]
    for i, (cid, label) in enumerate(items):
        top = 300 + i * 180
        gx, gy, gs = 170, top + 35, 90
        p.rect(gx, gy, gs, gs, lw=4.0)
        p.line(130, top + 160, 1790, top + 160, lw=1.5, stroke=FAINT)  # row rule
        p.text(300, top + 98, label, size_pt=16)
        add_cell(cid, "checkbox", label, 130, top, 400, 160, glyph_rect=(gx, gy, gs, gs))

    # Capture field: 600 px of ruled empty rows with corner brackets.
    p.text(160, 922, "CAPTURE - draw or write anything below:", size_pt=11, fill=GRAY)
    capx, capy, capw, caph = 130, 960, 1660, 600
    for k in range(1, 5):
        p.line(capx + 40, capy + k * 120, capx + capw - 40, capy + k * 120,
               lw=1.5, stroke=FAINT, dash=(2, 4))
    p.bracket(capx, capy, 1, 1)
    p.bracket(capx + capw, capy, -1, 1)
    p.bracket(capx, capy + caph, 1, -1)
    p.bracket(capx + capw, capy + caph, -1, -1)
    add_cell("capture_main", "capture", "freeform capture", capx, capy, capw, caph)

    # Command strip: bottom band. Trigger box for page 1 sits in slot 0
    # (page-dependent slot position = the positional fiducial).
    strip_top = 2360
    p.line(130, strip_top, 1790, strip_top, lw=2.0, stroke=GRAY)
    p.text(160, strip_top - 14, "command strip", size_pt=7, fill=GRAY)

    tb = (160, strip_top + 24, 64, 64)  # trigger box, slot 0
    p.rect(*tb, lw=4.0)
    p.text(160, strip_top + 112, "capture pg", size_pt=7, fill=GRAY)
    add_cell("cmd_capture_p1", "capture_trigger", "capture this page (slot 1)",
             tb[0] - 16, tb[1] - 16, 96, 96, glyph_rect=tb)

    for j, (cid, label) in enumerate(
        [("cmd_done", "done"), ("cmd_remind", "remind"), ("cmd_archive", "archive")]
    ):
        bx = 1400 + j * 160
        b = (bx, strip_top + 24, 64, 64)
        p.rect(*b, lw=4.0)
        p.text(bx, strip_top + 112, label, size_pt=7, fill=GRAY)
        add_cell(cid, "command", label, bx - 16, b[1] - 16, 96, 96, glyph_rect=b)

    c.showPage()
    c.save()

    manifest = {
        "doc_id": "spike-compose-001",
        "compose_version": "spike-0",
        "canvas": {"width": W, "height": H},
        "page_size_pt": [W * S, H * S],
        "pages": 1,
        "cells": cells,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n")


def verify() -> bool:
    import numpy as np
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(PDF_PATH))
    pil = pdf[0].render(scale=1 / S).to_pil().convert("L")
    assert pil.size == (W, H), f"raster is {pil.size}, expected {(W, H)}"
    arr = np.asarray(pil)
    pil.save(PREVIEW_PATH)

    manifest = json.loads(MANIFEST_PATH.read_text())
    ok = True
    print(f"raster: {pil.size[0]}x{pil.size[1]}  "
          f"(page {manifest['page_size_pt']} pt @ scale {1 / S:g})\n")
    print(f"{'cell':16} {'expected glyph px':>22} {'observed ink px':>22} {'max_d':>6}  result")

    for cell in manifest["cells"]:
        cid = cell["id"]
        x0, y0, x1, y1 = _bbox_to_pixels(tuple(cell["bbox_norm"]), arr.shape)
        crop = arr[y0:y1, x0:x1]
        dark_ys, dark_xs = np.nonzero(crop < 128)
        if cid in glyphs:
            # Printed label text may legitimately share the (generous) cell;
            # on-device it contributes zero ink to the .mark (0009 F3), so
            # the geometry check is: the glyph's ink sits at its expected
            # rect (within a padded window around it), and that rect lies
            # inside the manifest bbox.
            gx, gy, gw, gh = glyphs[cid]
            expected = (gx, gy, gx + gw, gy + gh)
            pad = 8
            win = arr[max(0, gy - pad):gy + gh + pad, max(0, gx - pad):gx + gw + pad]
            wys, wxs = np.nonzero(win < 128)
            if wys.size == 0:
                print(f"{cid:16} {str(expected):>22} {'NO INK FOUND':>22} {'':>6}  FAIL")
                ok = False
                continue
            observed = (max(0, gx - pad) + wxs.min(), max(0, gy - pad) + wys.min(),
                        max(0, gx - pad) + wxs.max() + 1, max(0, gy - pad) + wys.max() + 1)
            deltas = [abs(o - e) for o, e in zip(observed, expected)]
            contained = (expected[0] >= x0 and expected[1] >= y0
                         and expected[2] <= x1 and expected[3] <= y1)
            passed = contained and max(deltas) <= 3
            ok &= passed
            print(f"{cid:16} {str(expected):>22} {str(observed):>22} "
                  f"{max(deltas):>6}  {'PASS' if passed else 'FAIL'}")
        elif cid == "capture_main":
            # Brackets at all four corners; interior ruling faint (>=128).
            corners_ok = all(
                (arr[max(0, cy - 80):cy + 80, max(0, cx - 80):cx + 80] < 128).any()
                for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1))
            )
            inner = arr[y0 + 100:y1 - 100, x0 + 100:x1 - 100]
            interior_clear = not (inner < 128).any()
            passed = corners_ok and interior_clear
            ok &= passed
            print(f"{cid:16} {'4 corner brackets':>22} "
                  f"{('found' if corners_ok else 'MISSING'):>22} "
                  f"{'':>6}  {'PASS' if passed else 'FAIL'}"
                  + ("" if interior_clear else "  (interior not clear)"))

    return ok


if __name__ == "__main__":
    render()
    good = verify()
    print(f"\npdf:      {PDF_PATH}\nmanifest: {MANIFEST_PATH}\npreview:  {PREVIEW_PATH}")
    print("\nGEOMETRY ROUND-TRIP:", "PASS" if good else "FAIL")
    raise SystemExit(0 if good else 1)
