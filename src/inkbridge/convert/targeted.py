"""Cheap, targeted reads of a single page/region — no full conversion.

supernotelib exposes per-page decode separately from whole-notebook
conversion, which makes reading a single page or region much cheaper
than routing through ``convert.notebook.note_to_pdf`` plus OCR for a
simple "was this marked" check.
"""

from __future__ import annotations

from pathlib import Path

# Grayscale value below which a decoded pixel counts as ink. The decoded
# .pdf.mark render is near-binary: background is 255,
# ink is 0, with only a thin anti-aliased skirt in between. Anything in
# [0, 200) is treated as ink; the exact cutoff barely matters (a
# sensitivity sweep moves coverage <0.02 pp for cutoffs 50..250).
INK_GRAY_CUTOFF = 200


def decode_page_gray(note_path: Path, page_number: int):
    """Decode one page of a Supernote mark file to a grayscale numpy array
    of shape (H, W) = (2560, 1920) for the Manta. page_number is 1-indexed
    to match the manifest; supernotelib's convert() is 0-indexed.
    """
    import numpy as np  # local import: keep module import cheap / dependency-light
    import supernotelib as sn
    from supernotelib.converter import ImageConverter

    nb = sn.load_notebook(str(note_path))
    img = ImageConverter(nb).convert(page_number - 1)
    return np.asarray(img.convert("L"))


def _bbox_to_pixels(
    bbox_norm: tuple[float, float, float, float],
    shape: tuple[int, int],
    pad_px: int = 0,
) -> tuple[int, int, int, int]:
    """Map a normalized top-left [x, y, w, h] bbox (fractions of the page)
    onto pixel indices (x0, y0, x1, y1) for a (H, W) array, clamped to
    bounds and optionally padded outward by pad_px on every side.
    """
    h, w = shape
    nx, ny, nw, nh = bbox_norm
    x0 = round(nx * w) - pad_px
    y0 = round(ny * h) - pad_px
    x1 = round((nx + nw) * w) + pad_px
    y1 = round((ny + nh) * h) + pad_px
    x0 = max(0, min(x0, w))
    x1 = max(0, min(x1, w))
    y0 = max(0, min(y0, h))
    y1 = max(0, min(y1, h))
    return x0, y0, x1, y1


def coverage_in_gray(
    gray,
    bbox_norm: tuple[float, float, float, float],
    *,
    ink_gray_cutoff: int = INK_GRAY_CUTOFF,
    pad_px: int = 0,
) -> float:
    """Fraction (0..1) of pixels inside the normalized bbox of an
    already-decoded grayscale page that are ink (grayscale < cutoff).
    Lets callers with many cells on one page decode that page once.
    """
    import numpy as np

    x0, y0, x1, y1 = _bbox_to_pixels(bbox_norm, gray.shape, pad_px)
    crop = gray[y0:y1, x0:x1]
    if crop.size == 0:
        return 0.0
    return float(np.count_nonzero(crop < ink_gray_cutoff)) / crop.size


def page_changed(note_path: Path, page_number: int, since_token: str) -> bool:
    """Report whether a page's ink content has changed since a prior
    checkpoint, without decoding and comparing full stroke data.

    Not yet implemented — it is not yet confirmed that the underlying
    ``.note`` format exposes a cheap-enough signal (e.g. a per-page
    revision marker or checksum) to answer this without doing the full
    decode it's meant to avoid. Until this lands, callers who need to
    detect changes can decode the page (see :func:`decode_page_gray`)
    before and after and compare the results directly.
    """
    raise NotImplementedError(
        "page_changed is not yet implemented: cheap per-page change "
        "detection has not been confirmed possible for the .note format. "
        "As a workaround, decode the page with decode_page_gray() before "
        "and after and compare the results yourself."
    )
