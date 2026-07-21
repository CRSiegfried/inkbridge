"""Compose: markdown → row-grid PDF + input-area manifest (Phase 2.5).

Design: Analysis 0012. The renderer emits the manifest as a byproduct of
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


def compose(
    source: str | Path,
    output_pdf: Path,
    manifest_path: Path | None = None,
    doc_id: str | None = None,
    device: str = "manta",
) -> ComposeResult:
    """Render markdown (a Path to a .md file, or the text itself) to a
    pushable PDF plus its input-area manifest, for the named device profile.
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

    text = source.read_text() if isinstance(source, Path) else source
    output_pdf = Path(output_pdf)
    manifest_path = Path(manifest_path) if manifest_path else output_pdf.with_suffix(".manifest.json")

    source_md5 = hashlib.md5(text.encode()).hexdigest()
    doc_id = doc_id or f"{_slug(output_pdf.stem)}-{source_md5[:8]}"

    renderer = Renderer(output_pdf, profile)
    renderer.render(parse(text))

    manifest = {
        "doc_id": doc_id,
        "compose_version": COMPOSE_VERSION,
        "device": {"name": profile.name, "chrome_calibrated": profile.chrome_calibrated},
        "canvas": {"width": profile.canvas_w, "height": profile.canvas_h},
        "page_size_pt": [profile.page_w_pt, profile.page_h_pt],
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
