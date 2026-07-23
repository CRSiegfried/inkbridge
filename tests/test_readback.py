"""Readback decision + ink-hash-store tests.

Most tests run over synthetic decoded pages: read_pages() is pure over
{page: gray array}, so cells are painted directly onto 2560x1920 arrays.
The two `..._mark_...` tests at the bottom exercise the *real* supernotelib
decode path (`read_mark` → `decode_page_gray`) against a tracked device
capture in `tests/fixtures/` (a `.pdf.mark`, admitted under ADR-0005) — the
coverage that the painted-array tests structurally cannot reach.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from inkbridge.readback import (
    AMBIGUOUS_FLOOR,
    ANSWERED_LINE,
    Decision,
    InkHashStore,
    SparseMarkError,
    decide,
    ink_hash,
    read_mark,
    read_pages,
)

H, W = 2560, 1920

FIXTURES = Path(__file__).parent / "fixtures"


def blank_page() -> np.ndarray:
    return np.full((H, W), 255, dtype=np.uint8)


def paint(gray: np.ndarray, bbox_norm, fill_fraction: float) -> None:
    """Ink approximately fill_fraction of a normalized bbox's pixels,
    filling row-major from the top-left corner.
    """
    x, y, w, h = bbox_norm
    x0, y0 = int(x * W), int(y * H)
    x1, y1 = int((x + w) * W), int((y + h) * H)
    cols = x1 - x0
    budget = max(1, int((y1 - y0) * cols * fill_fraction))
    full_rows, rest = divmod(budget, cols)
    gray[y0:y0 + full_rows, x0:x1] = 0
    if rest:
        gray[y0 + full_rows, x0:x0 + rest] = 0


CELL_A = [0.1, 0.1, 0.2, 0.05]
CELL_B = [0.1, 0.3, 0.2, 0.05]
CELL_C = [0.1, 0.5, 0.2, 0.05]

MANIFEST = {
    "doc_id": "test-doc",
    "cells": [
        {"id": "a", "page": 1, "type": "checkbox", "label": "a", "bbox_norm": CELL_A},
        {"id": "b", "page": 1, "type": "checkbox", "label": "b", "bbox_norm": CELL_B},
        {"id": "c", "page": 2, "type": "capture", "label": None, "bbox_norm": CELL_C},
    ],
}


def test_decide_bands():
    assert decide(0.0) is Decision.BLANK
    assert decide(AMBIGUOUS_FLOOR / 2) is Decision.BLANK
    assert decide((AMBIGUOUS_FLOOR + ANSWERED_LINE) / 2) is Decision.AMBIGUOUS
    assert decide(ANSWERED_LINE * 2) is Decision.ANSWERED


def test_read_pages_three_way():
    p1 = blank_page()
    paint(p1, CELL_A, 0.5)        # heavy ink -> ANSWERED
    paint(p1, CELL_B, 0.002)      # a sliver -> AMBIGUOUS band
    p2 = blank_page()             # untouched -> BLANK

    pages = read_pages(MANIFEST, {1: p1, 2: p2})
    by_id = {c.id: c for p in pages for c in p.cells}
    assert by_id["a"].decision is Decision.ANSWERED
    assert by_id["b"].decision is Decision.AMBIGUOUS
    assert by_id["c"].decision is Decision.BLANK
    assert by_id["c"].coverage == 0.0  # true blank is exactly 0.000 (0009 F3)


def test_read_pages_cells_grouped_per_page():
    pages = read_pages(MANIFEST, {1: blank_page(), 2: blank_page()})
    assert [p.page for p in pages] == [1, 2]
    assert [c.id for c in pages[0].cells] == ["a", "b"]
    assert [c.id for c in pages[1].cells] == ["c"]


def test_ink_hash_ignores_antialiasing_skirt():
    a, b = blank_page(), blank_page()
    paint(a, CELL_A, 0.5)
    paint(b, CELL_A, 0.5)
    b[b == 255] = 230  # lighten the background: still above the ink cutoff
    assert ink_hash(a) == ink_hash(b)


def test_ink_hash_changes_with_more_ink():
    a, b = blank_page(), blank_page()
    paint(a, CELL_A, 0.5)
    paint(b, CELL_A, 0.5)
    paint(b, CELL_B, 0.5)  # "user added more scribbles later"
    assert ink_hash(a) != ink_hash(b)


def test_hash_store_redispatch_cycle(tmp_path):
    store_path = tmp_path / "hashes.json"
    page = blank_page()
    paint(page, CELL_A, 0.5)
    h1 = ink_hash(page)

    store = InkHashStore(store_path)
    assert store.changed("doc", 1, h1)          # never seen -> dispatch
    store.update("doc", 1, h1)
    assert not store.changed("doc", 1, h1)      # ticked box stays ticked -> skip

    paint(page, CELL_B, 0.5)
    h2 = ink_hash(page)
    assert store.changed("doc", 1, h2)          # more ink -> re-dispatch

    # erase-to-reset for free: back to the old bitmap is also a change
    store.update("doc", 1, h2)
    assert store.changed("doc", 1, h1)


def test_hash_store_persists_across_instances(tmp_path):
    store_path = tmp_path / "hashes.json"
    InkHashStore(store_path).update("doc", 3, "abc")
    fresh = InkHashStore(store_path)
    assert not fresh.changed("doc", 3, "abc")
    assert fresh.changed("other-doc", 3, "abc")


def test_hash_store_keys_by_doc_and_page(tmp_path):
    store = InkHashStore(tmp_path / "h.json")
    store.update("doc", 1, "x")
    assert store.changed("doc", 2, "x")


def test_atomic_write_survives_crash(monkeypatch, tmp_path):
    # A3: a crash AFTER the temp file is written but BEFORE the rename must
    # leave the hash store intact and parseable (temp-then-os.replace).
    path = tmp_path / "h.json"
    store = InkHashStore(path)
    store.update("doc", 1, "first")
    original = path.read_bytes()

    import inkbridge.atomicio as atomicio

    def boom(src, dst):  # os.replace stand-in: temp is already written
        raise OSError("simulated crash before rename")

    monkeypatch.setattr(atomicio.os, "replace", boom)
    with pytest.raises(OSError):
        store.update("doc", 2, "second")

    # Store untouched and still parseable; the crashed update left no temp.
    assert path.read_bytes() == original
    fresh = InkHashStore(path)
    assert not fresh.changed("doc", 1, "first")   # page 1 survived
    assert fresh.changed("doc", 2, "second")      # page 2 write was rolled back
    assert not list(tmp_path.glob(".*tmp*"))


@pytest.mark.parametrize("fill,expected", [
    (0.0, Decision.BLANK),
    (1.0, Decision.ANSWERED),
])
def test_extremes(fill, expected):
    p = blank_page()
    if fill:
        paint(p, CELL_A, fill)
    manifest = {"doc_id": "d", "cells": [
        {"id": "a", "page": 1, "type": "checkbox", "bbox_norm": CELL_A}]}
    (reading,) = read_pages(manifest, {1: p})
    assert reading.cells[0].decision is expected


# --- Real device-capture decode (C2/C1), tracked fixture under ADR-0005 ---

def _load_fixture():
    manifest = json.loads((FIXTURES / "sampler_form.manifest.json").read_text())
    expected = json.loads((FIXTURES / "sampler_form.readback.json").read_text())
    mark = FIXTURES / "sampler_form.pdf.mark"
    return manifest, mark, expected


def test_real_mark_decode_matches_expected_readback():
    """C2: the real supernotelib decode of a tracked device `.pdf.mark`
    reproduces the recorded per-cell coverage and three-way decision. This
    is the regression gate on `decode_page_gray`, the supernotelib boundary,
    and the 1-/0-indexed page mapping — none of which the synthetic-array
    tests above can touch.
    """
    manifest, mark, expected = _load_fixture()

    readings = read_mark(manifest, mark)
    got = {
        (pr.page, c.id): (c.coverage, c.decision.value)
        for pr in readings for c in pr.cells
    }

    expected_cells = [
        (p["page"], c["id"], c["coverage"], c["decision"])
        for p in expected["pages"] for c in p["cells"]
    ]
    # the fixture is a genuine answered form, not all-blank
    assert any(d == "answered" for *_, d in expected_cells)
    assert len(got) == len(expected_cells)

    for page, cid, cov, decision in expected_cells:
        assert (page, cid) in got, f"missing cell {cid} on page {page}"
        got_cov, got_decision = got[(page, cid)]
        assert got_cov == pytest.approx(cov, abs=1e-6), f"{cid} coverage"
        assert got_decision == decision, f"{cid} decision"


def test_real_mark_decode_maps_page_two_correctly():
    """C1 (positive branch): page-2 ink reads back as page 2, not
    misattributed. A manifest referencing only page-2 cells decodes the
    second mark page and yields that page's real, nonzero answers.
    """
    manifest, mark, expected = _load_fixture()
    p2_only = {**manifest,
               "cells": [c for c in manifest["cells"] if c["page"] == 2]}

    (reading,) = read_mark(p2_only, mark)
    assert reading.page == 2
    got = {c.id: (c.coverage, c.decision.value) for c in reading.cells}
    for c in next(p["cells"] for p in expected["pages"] if p["page"] == 2):
        assert got[c["id"]][0] == pytest.approx(c["coverage"], abs=1e-6)
        assert got[c["id"]][1] == c["decision"]


def test_sparse_mark_page_identity_refuses_typed():
    """C1: a manifest page absent from the (sparse) mark is refused with a
    typed SparseMarkError, never silently misattributed. The fixture mark
    has 2 pages; a manifest that also references a page 3 must raise before
    returning any reading.
    """
    manifest, mark, _ = _load_fixture()
    phantom = copy.deepcopy(next(c for c in manifest["cells"] if c["page"] == 2))
    phantom["id"] = "phantom.page3"
    phantom["page"] = 3
    sparse_manifest = {**manifest, "cells": manifest["cells"] + [phantom]}

    with pytest.raises(SparseMarkError):
        read_mark(sparse_manifest, mark)
