"""Compose pipeline tests (Analysis 0012 F8-F9).

The geometry round-trip test is the load-bearing one: it rasterizes the
rendered PDF at the device canvas resolution (1920x2560) and checks that
printed glyphs land inside their manifest bboxes as mapped by
convert.targeted._bbox_to_pixels — the same mapping the readback path uses
against a pulled .pdf.mark.
"""

from __future__ import annotations

import json

import pytest

from inkbridge.compose import compose
from inkbridge.compose.geometry import TRIGGER_SLOTS
from inkbridge.compose.parser import (
    Ack,
    Capture,
    Checkbox,
    Choice,
    Comb,
    Paragraph,
    Slider,
    Table,
    parse,
)
from inkbridge.convert.targeted import _bbox_to_pixels

KITCHEN_SINK = """\
# Grocery run

Please review this list *carefully* and check what we need. See
[the store](https://example.com/a-very-long-url-path-that-must-char-break-gracefully-0123456789-abcdefghijklmnopqrstuvwxyz-0123456789) for details.

## Produce

- [ ] milk
- [ ] eggs
- [x] coffee

1. first step
2. second step
   - nested detail
     - deeper nested detail that flattens at depth two and also wraps because it is a fairly long line of text

> A quoted reminder line that should wrap onto multiple rows and render with a side bar next to it.

{choice: store | HEB | Kroger | Costco}

{capture: extra items rows=5}

{ack: reviewed}

{slider: how urgent | not at all | very}

{comb: date n=8}

```
code line one
a much longer code line that will need to be character wrapped because it exceeds the content width 01234567890123456789012345678901234567890123456789
```

---

| a | b |
|---|---|
| 1 | 2 |

![diagram](x.png)

Final paragraph with superlongunbreakabletoken_abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqrstuvwxyz0123456789 end.
"""


def test_kitchen_sink_renders(tmp_path):
    res = compose(KITCHEN_SINK, tmp_path / "sink.pdf")
    assert res.pdf_path.exists() and res.manifest_path.exists()
    assert res.pages >= 1
    manifest = json.loads(res.manifest_path.read_text())
    assert manifest["compose_version"]
    types = {c["type"] for c in manifest["cells"]}
    assert {"checkbox", "choice", "capture", "ack", "slider", "comb",
            "capture_trigger", "command"} <= types
    for cell in manifest["cells"]:
        x, y, w, h = cell["bbox_norm"]
        assert 0 <= x and 0 <= y and w > 0 and h > 0
        assert x + w <= 1 and y + h <= 1
        assert 1 <= cell["page"] <= manifest["pages"]


def test_deterministic_output(tmp_path):
    a = compose(KITCHEN_SINK, tmp_path / "a.pdf")
    b = compose(KITCHEN_SINK, tmp_path / "b.pdf")
    assert a.pdf_path.read_bytes() == b.pdf_path.read_bytes()
    ma = json.loads(a.manifest_path.read_text())
    mb = json.loads(b.manifest_path.read_text())
    assert ma["cells"] == mb["cells"]


def test_geometry_roundtrip(tmp_path):
    np = pytest.importorskip("numpy")
    pdfium = pytest.importorskip("pypdfium2")

    md = ("# Form\n\n- [ ] alpha\n- [ ] beta\n- [ ] gamma\n\n"
          "{slider: mood | low | high}\n\n{comb: code n=4}\n\n"
          "{capture: sketch rows=6}\n")
    res = compose(md, tmp_path / "form.pdf")
    pdf = pdfium.PdfDocument(str(res.pdf_path))
    pil = pdf[0].render(scale=4).to_pil().convert("L")
    assert pil.size == (1920, 2560)
    arr = np.asarray(pil)

    for cell in res.cells:
        if cell["page"] != 1:
            continue
        x0, y0, x1, y1 = _bbox_to_pixels(tuple(cell["bbox_norm"]), arr.shape)
        crop = arr[y0:y1, x0:x1]
        if cell["type"] in ("checkbox", "ack", "capture_trigger", "command",
                            "slider", "comb"):
            # The printed glyph must land inside its manifest bbox.
            assert (crop < 128).any(), f"no glyph ink inside bbox of {cell['id']}"
        elif cell["type"] == "capture":
            # Corner brackets present; interior only faint ruling (no dark ink).
            for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
                win = arr[max(0, cy - 80) : cy + 80, max(0, cx - 80) : cx + 80]
                assert (win < 128).any(), f"missing bracket at {(cx, cy)} for {cell['id']}"
            inner = arr[y0 + 100 : y1 - 100, x0 + 100 : x1 - 100]
            assert not (inner < 128).any(), f"dark ink inside capture interior {cell['id']}"


def test_pagination_and_fiducial_slots(tmp_path):
    md = "# Long list\n\n" + "\n".join(f"- [ ] item {i}" for i in range(40))
    res = compose(md, tmp_path / "long.pdf")
    assert res.pages >= 2
    triggers = [c for c in res.cells if c["type"] == "capture_trigger"]
    assert len(triggers) == res.pages
    for t in triggers:
        assert t["slot"] == min(t["page"] - 1, TRIGGER_SLOTS - 1)
        assert t["fiducial_unique"] == (t["page"] <= TRIGGER_SLOTS)
    # every page carries a full command strip
    for p in range(1, res.pages + 1):
        names = {c["label"] for c in res.cells if c["type"] == "command" and c["page"] == p}
        assert names == {"done", "remind", "archive"}


def test_strip_clears_device_safe_bottom(tmp_path):
    # Device feedback 2026-07-20: the reader UI covers ~the bottom 100 px,
    # which hid the strip labels and clipped box bottoms. Nothing but the
    # corner registration ticks may be drawn below STRIP_SAFE_BOTTOM.
    np = pytest.importorskip("numpy")
    pdfium = pytest.importorskip("pypdfium2")
    from inkbridge.compose.geometry import STRIP_SAFE_BOTTOM

    res = compose("# T\n\n- [ ] item\n", tmp_path / "t.pdf")
    pdf = pdfium.PdfDocument(str(res.pdf_path))
    arr = np.asarray(pdf[0].render(scale=4).to_pil().convert("L"))
    below = arr[STRIP_SAFE_BOTTOM + 4 :, 130:1790]  # exclude tick corners
    assert not (below < 128).any(), "strip content extends below the safe area"


def test_long_checkbox_label_wraps_to_second_line(tmp_path):
    np = pytest.importorskip("numpy")
    pdfium = pytest.importorskip("pypdfium2")

    long = "a checkbox with a much longer label to see how truncation behaves on the device screen"
    res = compose(f"- [ ] milk\n- [ ] {long}\n", tmp_path / "cb.pdf")
    pdf = pdfium.PdfDocument(str(res.pdf_path))
    arr = np.asarray(pdf[0].render(scale=4).to_pil().convert("L"))

    def second_line_band(cell):
        # cell bbox is the padded glyph box; recover the row top / left
        # edge the label offsets are drawn from (box at x0+40, top+35).
        from inkbridge.compose.geometry import GLYPH_PAD

        x, y, _, _ = cell["bbox_norm"]
        px = int(x * 1920) + GLYPH_PAD - 40
        py = int(y * 2560) + GLYPH_PAD - 35
        return arr[py + 112 : py + 150, px + 180 : px + 1400]

    short_cell, long_cell = (c for c in res.cells if c["type"] == "checkbox")
    assert not (second_line_band(short_cell) < 128).any()
    assert (second_line_band(long_cell) < 128).any(), "long label did not wrap"


def test_choice_columns_follow_option_width(tmp_path):
    short = compose("{choice: q | a | b | c | d}\n", tmp_path / "s.pdf")
    ys = {c["bbox_norm"][1] for c in short.cells if c["type"] == "choice"}
    assert len(ys) == 1  # four short options share one row

    long_opts = "{choice: next store run | HEB | Kroger | Costco | skip this week}\n"
    wide = compose(long_opts, tmp_path / "w.pdf")
    ys = {c["bbox_norm"][1] for c in wide.cells if c["type"] == "choice"}
    assert len(ys) > 1  # "skip this week" forces fewer, wider columns


def test_directive_parsing():
    blocks = parse(
        "{capture: sketch rows=4}\n\n{choice: size | S | M | L}\n\n{ack: reviewed}\n"
    )
    cap, choice, ack = blocks
    assert isinstance(cap, Capture) and cap.label == "sketch" and cap.rows == 4
    assert isinstance(choice, Choice) and choice.label == "size"
    assert choice.options == ["S", "M", "L"]
    assert isinstance(ack, Ack) and ack.label == "reviewed"


def test_malformed_directive_stays_visible():
    blocks = parse("{choice: only-a-label}\n\n{bogus: nothing}\n")
    assert all(isinstance(b, Paragraph) for b in blocks)


def test_checkbox_detection():
    blocks = parse("- [ ] unchecked\n- [x] checked\n- plain item\n")
    assert isinstance(blocks[0], Checkbox) and blocks[0].label == "unchecked"
    assert isinstance(blocks[1], Checkbox) and blocks[1].label == "checked"
    assert not isinstance(blocks[2], Checkbox)


def test_table_parses_to_rows():
    blocks = parse("| name | qty |\n|---|---|\n| milk | 2 |\n| eggs | 12 |\n")
    (table,) = [b for b in blocks if isinstance(b, Table)]
    assert table.rows == [["name", "qty"], ["milk", "2"], ["eggs", "12"]]


def test_inline_segments():
    (p,) = parse("plain **bold** and *italic* plus `code` and ***both***\n")
    assert isinstance(p, Paragraph)
    assert p.segments == [
        ("plain ", "body"),
        ("bold", "bold"),
        (" and ", "body"),
        ("italic", "italic"),
        (" plus ", "body"),
        ("code", "code"),
        (" and ", "body"),
        ("both", "bolditalic"),
    ]
    assert p.text == "plain bold and italic plus code and both"


def test_slider_and_comb_directives():
    blocks = parse(
        "{slider: urgency | low | high}\n\n{slider: plain}\n\n"
        "{comb: date n=10}\n\n{comb: zip}\n"
    )
    s1, s2, c1, c2 = blocks
    assert isinstance(s1, Slider) and (s1.label, s1.left, s1.right) == ("urgency", "low", "high")
    assert isinstance(s2, Slider) and (s2.left, s2.right) == ("", "")
    assert isinstance(c1, Comb) and c1.n == 10
    assert isinstance(c2, Comb) and c2.n == 8  # default


def test_slider_and_comb_manifest_extras(tmp_path):
    res = compose("{slider: mood | bad | good}\n\n{comb: date n=6}\n", tmp_path / "s.pdf")
    (slider,) = [c for c in res.cells if c["type"] == "slider"]
    track = slider["track_norm"]
    assert 0 < track["x0"] < track["x1"] < 1 and 0 < track["y"] < 1
    # track must lie inside the cell bbox
    x, y, w, h = slider["bbox_norm"]
    assert x <= track["x0"] and track["x1"] <= x + w and y <= track["y"] <= y + h

    (comb,) = [c for c in res.cells if c["type"] == "comb"]
    assert comb["n"] == 6 and len(comb["boxes_norm"]) == 6
    for bx, by, bw, bh in comb["boxes_norm"]:
        assert x_contains(comb["bbox_norm"], (bx, by, bw, bh))


def x_contains(outer, inner) -> bool:
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return ox <= ix and oy <= iy and ix + iw <= ox + ow and iy + ih <= oy + oh


def test_empty_document(tmp_path):
    res = compose("", tmp_path / "empty.pdf")
    assert res.pages == 1
    assert {c["type"] for c in res.cells} == {"capture_trigger", "command"}
