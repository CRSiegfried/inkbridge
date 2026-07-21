"""Readback: a compose manifest + a pulled ``.pdf.mark`` → per-cell
three-way decisions, plus per-page ink hashes for re-dispatch idempotency.

Decisions follow the Analysis 0009 F4 contract — blank / ANSWERED /
AMBIGUOUS-escalate, never a boolean — computed over the *isolated* mark
decode, where printed glyphs are byte-level absent and a true blank reads
exactly 0.000 (0009 F3, the two-render discipline).

The default bands come from 0009's calibration fixtures (stray dot ~0.062%,
half-stroke ~0.19%, lightest deliberate answer ~0.49%). 0009 F10 warns the
numbers are geometry-dependent and do not transfer to new cell sizes;
recalibration against compose's row-grid cells is pending the annotated
sampler, so treat these as provisional defaults, not calibrated constants.

The ink-hash store implements Analysis 0012 F6: a ticked capture box stays
ticked, so a poller re-dispatching every flagged page would loop forever.
Storing a hash of each page's decoded ink bitmap and re-dispatching only on
change handles "user added more scribbles later" and gets erase-to-reset
for free.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from inkbridge.convert.targeted import (
    INK_GRAY_CUTOFF,
    coverage_in_gray,
    decode_page_gray,
)

# 0009 F4 bands, normalized-coverage fractions. Below the floor is stray-dot
# territory rounding to blank; between floor and line is the escalate band;
# above the line is a deliberate answer. Provisional — see module docstring.
AMBIGUOUS_FLOOR = 0.001
ANSWERED_LINE = 0.004


class Decision(str, Enum):
    BLANK = "blank"
    AMBIGUOUS = "ambiguous"
    ANSWERED = "answered"


def decide(
    coverage: float,
    *,
    ambiguous_floor: float = AMBIGUOUS_FLOOR,
    answered_line: float = ANSWERED_LINE,
) -> Decision:
    """Three-way decision for one cell's ink-coverage fraction (0009 F4)."""
    if coverage < ambiguous_floor:
        return Decision.BLANK
    if coverage < answered_line:
        return Decision.AMBIGUOUS
    return Decision.ANSWERED


@dataclass
class CellReading:
    id: str
    type: str
    label: str | None
    page: int
    coverage: float
    decision: Decision


@dataclass
class PageReading:
    page: int
    ink_hash: str
    cells: list[CellReading]


def ink_hash(gray, *, ink_gray_cutoff: int = INK_GRAY_CUTOFF) -> str:
    """sha256 of the binarized ink bitmap of a decoded page. Stable against
    anything but actual ink change: the decode is near-binary, and hashing
    the thresholded mask (not raw grayscale) keeps the anti-aliased skirt
    from mattering.
    """
    mask = gray < ink_gray_cutoff
    return hashlib.sha256(mask.tobytes()).hexdigest()


def read_pages(
    manifest: dict,
    grays: dict[int, "object"],
    *,
    ink_gray_cutoff: int = INK_GRAY_CUTOFF,
    ambiguous_floor: float = AMBIGUOUS_FLOOR,
    answered_line: float = ANSWERED_LINE,
) -> list[PageReading]:
    """Decision pass over already-decoded pages ({page_number: gray array}).
    Pure of I/O — :func:`read_mark` is the decoding front-end.
    """
    by_page: dict[int, list[dict]] = {}
    for cell in manifest["cells"]:
        by_page.setdefault(cell["page"], []).append(cell)

    readings = []
    for page in sorted(grays):
        gray = grays[page]
        cells = [
            CellReading(
                id=c["id"],
                type=c["type"],
                label=c.get("label"),
                page=page,
                coverage=(cov := coverage_in_gray(
                    gray, tuple(c["bbox_norm"]), ink_gray_cutoff=ink_gray_cutoff)),
                decision=decide(
                    cov, ambiguous_floor=ambiguous_floor, answered_line=answered_line),
            )
            for c in by_page.get(page, [])
        ]
        readings.append(PageReading(
            page=page,
            ink_hash=ink_hash(gray, ink_gray_cutoff=ink_gray_cutoff),
            cells=cells,
        ))
    return readings


def read_mark(
    manifest: dict | Path,
    mark_path: Path,
    *,
    ink_gray_cutoff: int = INK_GRAY_CUTOFF,
    ambiguous_floor: float = AMBIGUOUS_FLOOR,
    answered_line: float = ANSWERED_LINE,
) -> list[PageReading]:
    """Decode every manifest page of ``mark_path`` once and run the
    three-way decision over each cell.

    Page identity is positional — mark-page k is compose-page k (the device
    never modifies a pushed PDF, 0014 F3). No fiducial confirms it: a
    printed/positional mark can't survive the isolated-ink readback
    (composite.py; 0009 F3), and a page-count guard can't substitute either,
    because the mark is *sparse* (only annotated pages materialize) and
    carries no page index (0009 F7) — so a blank page and a deleted page are
    indistinguishable by count. This decode therefore assumes a **dense**
    mark: every manifest page was annotated, so mark-page k lines up with
    compose-page k. Sparse multi-page marks (a page left entirely blank) are
    an open problem — see ADR-0004; ``decode_page_gray`` will raise
    IndexError for a manifest page absent from the mark.
    """
    if isinstance(manifest, Path):
        manifest = json.loads(manifest.read_text())
    pages = sorted({c["page"] for c in manifest["cells"]})
    grays = {p: decode_page_gray(mark_path, p) for p in pages}
    return read_pages(
        manifest, grays,
        ink_gray_cutoff=ink_gray_cutoff,
        ambiguous_floor=ambiguous_floor,
        answered_line=answered_line,
    )


class InkHashStore:
    """JSON-file store of per-(doc_id, page) ink-bitmap hashes (0012 F6).

    ``changed()`` answers "should this page be (re-)dispatched"; call
    ``update()`` once the dispatch has been handed off, so a crash between
    the two re-dispatches rather than drops.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self._hashes: dict[str, str] = {}
        if self.path.exists():
            self._hashes = json.loads(self.path.read_text())

    @staticmethod
    def _key(doc_id: str, page: int) -> str:
        return f"{doc_id}/p{page}"

    def changed(self, doc_id: str, page: int, page_ink_hash: str) -> bool:
        """True if this page's ink differs from the last recorded state
        (including never-seen pages).
        """
        return self._hashes.get(self._key(doc_id, page)) != page_ink_hash

    def update(self, doc_id: str, page: int, page_ink_hash: str) -> None:
        self._hashes[self._key(doc_id, page)] = page_ink_hash
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._hashes, indent=2, sort_keys=True) + "\n")
