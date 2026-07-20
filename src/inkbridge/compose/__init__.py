"""Compose: markdown → row-grid PDF + input-area manifest (Phase 2.5).

Design: Analysis 0012. The renderer emits the manifest as a byproduct of
rendering — every cell bbox is row arithmetic, and the manifest's
`bbox_norm` values feed convert.targeted.region_has_ink unchanged on the
readback side.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

COMPOSE_VERSION = "0.4.0"


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
) -> ComposeResult:
    """Render markdown (a Path to a .md file, or the text itself) to a
    pushable PDF plus its input-area manifest.
    """
    from .geometry import (
        CANVAS_H,
        CANVAS_W,
        PAGE_H_PT,
        PAGE_W_PT,
        TRIGGER_BOX,
        TRIGGER_PITCH,
        TRIGGER_SLOTS,
        TRIGGER_X0,
    )
    from .parser import parse
    from .render import Renderer, _slug

    text = source.read_text() if isinstance(source, Path) else source
    output_pdf = Path(output_pdf)
    manifest_path = Path(manifest_path) if manifest_path else output_pdf.with_suffix(".manifest.json")

    source_md5 = hashlib.md5(text.encode()).hexdigest()
    doc_id = doc_id or f"{_slug(output_pdf.stem)}-{source_md5[:8]}"

    renderer = Renderer(output_pdf)
    renderer.render(parse(text))

    manifest = {
        "doc_id": doc_id,
        "compose_version": COMPOSE_VERSION,
        "canvas": {"width": CANVAS_W, "height": CANVAS_H},
        "page_size_pt": [PAGE_W_PT, PAGE_H_PT],
        "pages": renderer.page,
        "source_md5": source_md5,
        "trigger_slots": {
            "x0": TRIGGER_X0,
            "pitch": TRIGGER_PITCH,
            "box": TRIGGER_BOX,
            "capacity": TRIGGER_SLOTS,
        },
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
