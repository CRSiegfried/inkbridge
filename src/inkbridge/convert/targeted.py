"""Cheap, targeted reads of a single page/region — no full conversion.

Phase 1.5 work (see docs/roadmap.md). Motivation and feasibility notes in
docs/note-format.md#implication-targeted-reads-for-latency: supernotelib
already exposes per-page decode separately from whole-notebook conversion,
which should make this much cheaper than routing through
convert.notebook.note_to_pdf + OCR for a simple "was this marked" check.
"""

from __future__ import annotations

from pathlib import Path

# Grayscale value below which a decoded pixel counts as ink. The decoded
# .pdf.mark render is near-binary (see Analysis 0009): background is 255,
# ink is 0, with only a thin anti-aliased skirt in between. Anything in
# [0, 200) is treated as ink; the exact cutoff barely matters (Analysis
# 0009 sensitivity sweep: coverage moves <0.02 pp for cutoffs 50..250).
INK_GRAY_CUTOFF = 200

# Fraction-of-cell coverage above which region_has_ink returns True by
# default. Empirically (Analysis 0009, real Manta fixtures) a true blank
# cell is exactly 0.000, a single stray dot is ~0.062%, a half-stroke is
# ~0.19%, and the lightest deliberate answer (a checkmark) is ~0.49%.
# 0.30% sits in the gap between the half-stroke and the lightest real
# answer; it is NOT a clean separator from a stray/partial mark — see the
# analysis's ambiguity-band discussion before relying on presence alone.
DEFAULT_COVERAGE_THRESHOLD = 0.003


def _decode_page_gray(note_path: Path, page_number: int):
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
    x0 = int(round(nx * w)) - pad_px
    y0 = int(round(ny * h)) - pad_px
    x1 = int(round((nx + nw) * w)) + pad_px
    y1 = int(round((ny + nh) * h)) + pad_px
    x0 = max(0, min(x0, w))
    x1 = max(0, min(x1, w))
    y0 = max(0, min(y0, h))
    y1 = max(0, min(y1, h))
    return x0, y0, x1, y1


def region_ink_coverage(
    note_path: Path,
    page_number: int,
    bbox_norm: tuple[float, float, float, float],
    *,
    ink_gray_cutoff: int = INK_GRAY_CUTOFF,
    pad_px: int = 0,
) -> float:
    """Fraction (0..1) of pixels inside the normalized bbox that are ink
    (grayscale < ink_gray_cutoff) on the current decoded state of the page.
    """
    import numpy as np

    gray = _decode_page_gray(note_path, page_number)
    x0, y0, x1, y1 = _bbox_to_pixels(bbox_norm, gray.shape, pad_px)
    crop = gray[y0:y1, x0:x1]
    if crop.size == 0:
        return 0.0
    return float(np.count_nonzero(crop < ink_gray_cutoff)) / crop.size


def region_has_ink(
    note_path: Path,
    page_number: int,
    bbox_norm: tuple[float, float, float, float],
    *,
    threshold: float = DEFAULT_COVERAGE_THRESHOLD,
    ink_gray_cutoff: int = INK_GRAY_CUTOFF,
    pad_px: int = 0,
) -> bool:
    """Decode a single page and report whether the normalized top-left bbox
    [x, y, w, h] contains ink coverage strictly above ``threshold`` — a
    presence check for "was this cell answered", without full OCR/VLM.

    Presence-only cannot distinguish a legitimate light answer from a stray
    or partial mark (Analysis 0009); ``threshold`` trades false-positives
    (stray dots) against false-negatives (faint/partial answers).
    """
    coverage = region_ink_coverage(
        note_path, page_number, bbox_norm,
        ink_gray_cutoff=ink_gray_cutoff, pad_px=pad_px,
    )
    return coverage > threshold


def page_changed(note_path: Path, page_number: int, since_token: str) -> bool:
    """Cheapest tier: has this page changed since since_token, without
    decoding stroke data? Feasibility unconfirmed — see docs/note-format.md.
    """
    raise NotImplementedError("Phase 1.5: confirm change-detection is possible at all")
