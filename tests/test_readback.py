"""Readback decision + ink-hash-store tests over synthetic decoded pages.

No real .mark decode here: read_pages() is pure over {page: gray array},
so cells are painted directly onto 2560x1920 arrays. Decode-dependent
behavior (supernotelib) is covered by the calibration fixtures in
Analysis 0009, not unit tests.
"""

from __future__ import annotations

import numpy as np
import pytest

from inkbridge.readback import (
    AMBIGUOUS_FLOOR,
    ANSWERED_LINE,
    Decision,
    InkHashStore,
    decide,
    ink_hash,
    read_pages,
)

H, W = 2560, 1920


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
