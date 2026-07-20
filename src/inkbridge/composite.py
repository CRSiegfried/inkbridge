"""Capture compositing (Analysis 0012 finding 5): decoded ``.pdf.mark``
ink overlaid on the rendered base PDF page at the device's 1920×2560
canvas.

This is the *capture render* half of the two-render discipline: the
composite is what gets cropped and dispatched to a VLM — annotation on top
of the printed content. It is **never** a coverage target; presence checks
run on the isolated mark decode only (0009 F3), where printed glyphs are
byte-level absent.

Alignment rests on the byte-stable round-trip (0003 F5: the device never
modifies a pushed PDF, so push-time coordinates stay valid) and on the
compose template drawing the page as the same 1920×2560 sheet the mark
decode produces. The corner registration ticks compose prints are the
built-in alignment check: synthetic ink drawn at tick coordinates in mark
space must land on the rendered ticks.
"""

from __future__ import annotations

from pathlib import Path

from inkbridge.convert.targeted import (
    INK_GRAY_CUTOFF,
    _bbox_to_pixels,
    decode_page_gray,
)

CANVAS_W, CANVAS_H = 1920, 2560


def render_base_page(pdf_path: Path, page_number: int):
    """Rasterize one PDF page (1-indexed) to an RGB numpy array at the
    device canvas resolution. Pages with the compose template's 3:4 sheet
    land on 1920×2560 exactly; other aspect ratios are scaled to canvas
    width and must match the canvas within a pixel or a ValueError is
    raised (a mismatched base cannot be composited against mark space).
    """
    import numpy as np
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        page = pdf[page_number - 1]
        w_pt, _ = page.get_size()
        img = page.render(scale=CANVAS_W / w_pt).to_pil().convert("RGB")
    finally:
        pdf.close()
    if img.size != (CANVAS_W, CANVAS_H):
        raise ValueError(
            f"page {page_number} of {pdf_path} renders to {img.size}, "
            f"not the {CANVAS_W}x{CANVAS_H} device canvas — wrong aspect "
            "ratio for mark-space compositing")
    return np.asarray(img).copy()


def composite_arrays(
    base_rgb,
    ink_gray,
    *,
    ink_gray_cutoff: int = INK_GRAY_CUTOFF,
    ink_color: tuple[int, int, int] = (0, 0, 0),
):
    """Overlay a decoded mark page (H×W grayscale) onto a rendered base
    page (H×W×3 RGB): pixels the mark decode considers ink replace the
    base. Pure array math — shapes must match exactly, because a silent
    resample would be exactly the alignment bug this module exists to
    avoid.
    """
    if base_rgb.shape[:2] != ink_gray.shape:
        raise ValueError(
            f"base {base_rgb.shape[:2]} and ink {ink_gray.shape} disagree — "
            "refusing to resample")
    out = base_rgb.copy()
    out[ink_gray < ink_gray_cutoff] = ink_color
    return out


def composite_page(
    base_pdf: Path,
    mark_path: Path,
    page_number: int,
    *,
    ink_gray_cutoff: int = INK_GRAY_CUTOFF,
    ink_color: tuple[int, int, int] = (0, 0, 0),
):
    """Render base page + decode mark page + overlay. Returns a PIL Image
    ready for the VLM (or for cropping via ``composite_region``).
    """
    from PIL import Image

    base = render_base_page(base_pdf, page_number)
    ink = decode_page_gray(mark_path, page_number)
    return Image.fromarray(composite_arrays(
        base, ink, ink_gray_cutoff=ink_gray_cutoff, ink_color=ink_color))


def composite_region(
    base_pdf: Path,
    mark_path: Path,
    page_number: int,
    bbox_norm: tuple[float, float, float, float],
    *,
    pad_px: int = 40,
    ink_gray_cutoff: int = INK_GRAY_CUTOFF,
    ink_color: tuple[int, int, int] = (0, 0, 0),
):
    """Composite one page and crop a manifest cell's bbox (padded) — the
    unit a flagged capture field ships to the VLM as.
    """
    img = composite_page(
        base_pdf, mark_path, page_number,
        ink_gray_cutoff=ink_gray_cutoff, ink_color=ink_color)
    x0, y0, x1, y1 = _bbox_to_pixels(bbox_norm, (CANVAS_H, CANVAS_W), pad_px)
    return img.crop((x0, y0, x1, y1))
