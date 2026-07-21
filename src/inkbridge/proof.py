"""Device-free self-test (Analysis 0017 finding 8).

Stamp synthetic ink into every manifest cell, run the readback decision over
the synthetic mark, and assert every cell reads ANSWERED. No device, no
human: the only fully autonomous end-to-end check available pre-hardware.

What it verifies: every manifest bbox is in-bounds and non-empty,
``_bbox_to_pixels`` maps it to a real crop, and the decision bands classify a
filled cell as ANSWERED. What it does **not** verify: compose's ``norm()``
against the rendered PDF. Synthetic ink is painted at the same manifest bbox
readback reads, so a drift that moved the printed glyph and the manifest bbox
together would pass here — the compose-side geometry contract (a printed
glyph lands inside its own bbox) is covered by
``tests/test_compose.py::test_geometry_roundtrip``. ``proof`` is the runtime
decision-pipeline check, not a substitute for that.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from inkbridge.convert.targeted import _bbox_to_pixels
from inkbridge.readback import Decision, read_pages


@dataclass
class ProofFailure:
    id: str
    page: int
    type: str
    coverage: float
    decision: str


@dataclass
class ProofResult:
    doc_id: str | None
    pages: int
    cells: int
    failures: list[ProofFailure]

    @property
    def ok(self) -> bool:
        return not self.failures


def _canvas_shape(manifest: dict) -> tuple[int, int]:
    canvas = manifest.get("canvas")
    if not canvas:
        raise ValueError(
            "manifest has no canvas block; recompose with a current build")
    return int(canvas["height"]), int(canvas["width"])


def stamp_pages(manifest: dict) -> dict:
    """Blank device-canvas arrays with every cell's bbox filled with ink —
    the synthetic isolated-mark analog of a fully answered document. Painted
    via ``_bbox_to_pixels``, the exact region ``coverage_in_gray`` reads, so
    a well-formed cell is unambiguously ANSWERED and a degenerate one (empty
    or out-of-bounds crop) paints nothing and surfaces as a failure.
    """
    import numpy as np

    h, w = _canvas_shape(manifest)
    grays: dict[int, "np.ndarray"] = {}
    for cell in manifest["cells"]:
        gray = grays.get(cell["page"])
        if gray is None:
            gray = grays[cell["page"]] = np.full((h, w), 255, dtype=np.uint8)
        x0, y0, x1, y1 = _bbox_to_pixels(tuple(cell["bbox_norm"]), (h, w))
        gray[y0:y1, x0:x1] = 0
    return grays


def proof(manifest: dict) -> ProofResult:
    """Stamp every cell, read it back, and collect any cell that does not
    read ANSWERED (Analysis 0017 F8)."""
    grays = stamp_pages(manifest)
    readings = read_pages(manifest, grays)
    failures = [
        ProofFailure(c.id, c.page, c.type, c.coverage, c.decision.value)
        for p in readings for c in p.cells
        if c.decision is not Decision.ANSWERED
    ]
    return ProofResult(
        doc_id=manifest.get("doc_id"),
        pages=len(grays),
        cells=sum(len(p.cells) for p in readings),
        failures=failures,
    )


def proof_payload(result: ProofResult) -> dict:
    """The ``proof.v1`` result document (used by the CLI's --json path)."""
    return {
        "doc_id": result.doc_id,
        "pages": result.pages,
        "cells": result.cells,
        "ok": result.ok,
        "failures": [asdict(f) for f in result.failures],
    }
