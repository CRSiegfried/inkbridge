"""Cheap, targeted reads of a single page/region — no full conversion.

Phase 1.5 work (see docs/roadmap.md). Motivation and feasibility notes in
docs/note-format.md#implication-targeted-reads-for-latency: supernotelib
already exposes per-page decode separately from whole-notebook conversion,
which should make this much cheaper than routing through
convert.notebook.note_to_pdf + OCR for a simple "was this marked" check.
"""

from __future__ import annotations

from pathlib import Path


def page_changed(note_path: Path, page_number: int, since_token: str) -> bool:
    """Cheapest tier: has this page changed since since_token, without
    decoding stroke data? Feasibility unconfirmed — see docs/note-format.md.
    """
    raise NotImplementedError("Phase 1.5: confirm change-detection is possible at all")


def region_has_ink(note_path: Path, page_number: int, bbox: tuple[int, int, int, int]) -> bool:
    """Decode a single page and check whether bbox (x, y, w, h) contains any
    ink — e.g. to check whether a checkbox was marked, without full OCR/VLM
    transcription of the page.
    """
    raise NotImplementedError("Phase 1.5: wire up supernotelib's convert(page_number)")
