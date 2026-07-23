"""Compose: markdown → row-grid PDF + input-area manifest (Phase 2.5).

The renderer emits the manifest as a byproduct of
rendering — every cell bbox is row arithmetic, and the manifest's
`bbox_norm` values feed convert.targeted.region_has_ink unchanged on the
readback side.

The target device is a geometry profile (geometry.PROFILES): Manta is the
calibrated default; the Nomad profile renders to its community-documented
1404x1872 canvas with an assumed chrome envelope (manifest carries
`device.chrome_calibrated` so downstream consumers know which).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

COMPOSE_VERSION = "0.7.0"


@dataclass
class ComposeResult:
    pdf_path: Path
    manifest_path: Path
    doc_id: str
    pages: int
    cells: list[dict]


# Named density presets → layout scale (see render.Renderer). "normal" is
# the calibrated 1.0 baseline; the tighter variants shrink every content
# design constant (fonts, rows, glyph boxes) uniformly. "dense" (0.72) is the
# device-validated default for dispatch — its shrunk tickable boxes were
# confirmed comfortable for a pen mark on the Manta (2026-07-21). The CLI
# defaults to it.
DENSITIES = {"normal": 1.0, "compact": 0.85, "dense": 0.72}


def _stamp_decision_bands(cells: list[dict], profile) -> None:
    """Write per-cell readback decision bands into each manifest cell (G1).
    The calibration bands are anchored to the tick box at scale 1.0
    (``A_ref``); a cell of bbox-pixel-area ``A_cell`` gets bands scaled by
    ``A_ref / A_cell``, holding the *absolute* ink threshold constant across
    cell sizes and densities (a deliberate mark is ~constant absolute ink, so
    its coverage fraction is inversely proportional to area). A standard tick
    cell at scale 1.0 gets factor 1.0 (bands == base)."""
    from inkbridge.readback import AMBIGUOUS_FLOOR, ANSWERED_LINE

    ref_side = profile.glyph_box + 2 * profile.glyph_pad  # tick cell, scale 1.0
    a_ref = float(ref_side * ref_side)
    canvas_area = float(profile.canvas_w * profile.canvas_h)
    for cell in cells:
        _x, _y, w, h = cell["bbox_norm"]
        a_cell = w * h * canvas_area  # bbox area in px²
        factor = a_ref / a_cell if a_cell > 0 else 1.0
        cell["bands"] = {
            "ambiguous_floor": round(AMBIGUOUS_FLOOR * factor, 8),
            "answered_line": round(ANSWERED_LINE * factor, 8),
        }


def compose(
    source: str | Path,
    output_pdf: Path,
    manifest_path: Path | None = None,
    doc_id: str | None = None,
    device: str = "manta",
    scale: float = 1.0,
) -> ComposeResult:
    """Render markdown (a Path to a .md file, or the text itself) to a
    pushable PDF plus its input-area manifest, for the named device profile.

    `scale` is the layout density factor (1.0 = calibrated baseline; <1.0
    packs tighter). It scales content uniformly — fonts, row height, glyph
    boxes — leaving the canvas, margins, and chrome envelope device-fixed;
    manifest bboxes stay correct by construction (render.Renderer).
    """
    from .geometry import PROFILES
    from .parser import parse
    from .render import Renderer, _slug

    try:
        profile = PROFILES[device]
    except KeyError:
        raise ValueError(
            f"unknown device {device!r}; known profiles: {', '.join(sorted(PROFILES))}"
        ) from None
    if scale <= 0:
        raise ValueError(f"scale must be positive, got {scale!r}")

    text = source.read_text() if isinstance(source, Path) else source
    output_pdf = Path(output_pdf)
    manifest_path = Path(manifest_path) if manifest_path else output_pdf.with_suffix(".manifest.json")

    source_md5 = hashlib.md5(text.encode()).hexdigest()
    doc_id = doc_id or f"{_slug(output_pdf.stem)}-{source_md5[:8]}"

    renderer = Renderer(output_pdf, profile, scale)
    renderer.render(parse(text))
    _stamp_decision_bands(renderer.cells, profile)

    manifest = {
        "doc_id": doc_id,
        "compose_version": COMPOSE_VERSION,
        "device": {"name": profile.name, "chrome_calibrated": profile.chrome_calibrated},
        "canvas": {"width": profile.canvas_w, "height": profile.canvas_h},
        "page_size_pt": [profile.page_w_pt, profile.page_h_pt],
        # Provenance only: bboxes are normalized, so readback is scale-agnostic.
        "layout": {"scale": scale},
        "pages": renderer.page,
        "source_md5": source_md5,
        "cells": renderer.cells,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    return ComposeResult(
        pdf_path=output_pdf,
        manifest_path=manifest_path,
        doc_id=doc_id,
        pages=renderer.page,
        cells=renderer.cells,
    )
