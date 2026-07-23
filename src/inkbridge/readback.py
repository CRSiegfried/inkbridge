"""Readback: a compose manifest + a pulled ``.pdf.mark`` → per-cell
three-way decisions, plus per-page ink hashes for re-dispatch idempotency.

Decisions are three-way — blank / ANSWERED /
AMBIGUOUS-escalate, never a boolean — computed over the *isolated* mark
decode, where printed glyphs are byte-level absent and a true blank reads
exactly 0.000 (0009 F3, the two-render discipline).

The default bands come from 0009's calibration fixtures (stray dot ~0.062%,
half-stroke ~0.19%, lightest deliberate answer ~0.49%). 0009 F10 warns the
numbers are geometry-dependent and do not transfer to new cell sizes;
recalibration against compose's row-grid cells is pending the annotated
sampler, so treat these as provisional defaults, not calibrated constants.

The ink-hash store handles re-dispatch churn: a ticked capture box stays
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

from inkbridge.atomicio import atomic_write_text, file_lock
from inkbridge.convert.targeted import (
    INK_GRAY_CUTOFF,
    coverage_in_gray,
    decode_page_gray,
)

# 0009 F4 bands, normalized-coverage fractions. Below the floor is stray-dot
# territory rounding to blank; between floor and line is the escalate band;
# above the line is a deliberate answer. These are the CALIBRATION BASIS anchored
# to the tick box at scale 1.0: compose scales them per cell by the
# cell's area and writes the result into the manifest, and read_pages decides
# from those per-cell bands. They survive here as the base compose scales from
# and as the fallback for a manifest that predates the per-cell `bands` field.
AMBIGUOUS_FLOOR = 0.001
ANSWERED_LINE = 0.004


class SparseMarkError(Exception):
    """A manifest page is absent from the ``.pdf.mark``.

    The mark is sparse — only annotated pages materialize, with no page
    index (0009 F7) — so a page the device left blank cannot be located and
    the positional mapping would misattribute later pages' ink. Refusing is
    the safe outcome. This *types* the failure ``decode_page_gray``
    already surfaces as a bare ``IndexError``; it is not a structural
    page-count guard on valid dense reads (which the design deliberately
    omits) — a dense
    mark decodes unchanged.
    """


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
    # Explicit per-question group id from the manifest (G4). Choice options
    # sharing a group are one question even across a page break; None on
    # single-cell types and on manifests that predate the field.
    group: str | None = None


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
        cells = []
        for c in by_page.get(page, []):
            # The manifest's per-cell bands are authoritative; the
            # module-global defaults are only the fallback for a manifest that
            # predates the field, so a decode reads no decision global when the
            # bands are present.
            bands = c.get("bands") or {}
            af = bands.get("ambiguous_floor", ambiguous_floor)
            al = bands.get("answered_line", answered_line)
            cov = coverage_in_gray(
                gray, tuple(c["bbox_norm"]), ink_gray_cutoff=ink_gray_cutoff)
            cells.append(CellReading(
                id=c["id"],
                type=c["type"],
                label=c.get("label"),
                page=page,
                coverage=cov,
                decision=decide(cov, ambiguous_floor=af, answered_line=al),
                group=c.get("group"),
            ))
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
    an open problem. When a manifest page is absent from the
    mark this refuses with :class:`SparseMarkError` rather than misattribute:
    the decode is eager over every manifest page, so a compose-generated
    manifest (which references *every* page via its command strip) can never
    return a reading before hitting the missing page. Correcting the mapping —
    not just detecting the gap — still needs positional page identity we don't
    have; this only makes the failure loud and typed.
    """
    if isinstance(manifest, Path):
        manifest = json.loads(manifest.read_text())
    pages = sorted({c["page"] for c in manifest["cells"]})
    grays = {}
    for p in pages:
        try:
            grays[p] = decode_page_gray(mark_path, p)
        except IndexError as e:
            raise SparseMarkError(
                f"manifest references page {p} but it is absent from "
                f"{Path(mark_path).name} — a sparse mark (blank/missing page) "
                f"can't be read positionally without misattributing ink"
            ) from e
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
        """Record a page's ink hash crash-safely (A3): under an advisory lock,
        re-read the on-disk store and merge this key in before writing (so a
        concurrent writer's other-page update isn't lost), then write via an
        atomic temp-then-rename (so a crash can't corrupt the store)."""
        key = self._key(doc_id, page)
        with file_lock(self.path):
            if self.path.exists():
                # Merge onto the latest on-disk state, not our load-time snapshot,
                # so two processes updating different pages don't clobber.
                self._hashes = json.loads(self.path.read_text())
            self._hashes[key] = page_ink_hash
            atomic_write_text(
                self.path, json.dumps(self._hashes, indent=2, sort_keys=True) + "\n")
