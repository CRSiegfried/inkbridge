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
from inkbridge.compose.profiles import MANTA, PROFILES
from inkbridge.compose.parser import (
    Ack,
    Capture,
    Checkbox,
    Choice,
    Comb,
    Paragraph,
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
    assert {"checkbox", "choice", "capture", "ack", "comb",
            "capture_trigger"} <= types
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


@pytest.mark.parametrize("device", sorted(PROFILES))
def test_geometry_roundtrip(tmp_path, device):
    np = pytest.importorskip("numpy")
    pdfium = pytest.importorskip("pypdfium2")

    g = PROFILES[device]
    md = ("# Form\n\n- [ ] alpha\n- [ ] beta\n- [ ] gamma\n\n"
          "{comb: code n=4}\n\n"
          "{capture: sketch rows=6}\n")
    res = compose(md, tmp_path / "form.pdf", device=device)
    pdf = pdfium.PdfDocument(str(res.pdf_path))
    pil = pdf[0].render(scale=4).to_pil().convert("L")
    assert pil.size == (g.canvas_w, g.canvas_h)
    arr = np.asarray(pil)

    for cell in res.cells:
        if cell["page"] != 1:
            continue
        x0, y0, x1, y1 = _bbox_to_pixels(tuple(cell["bbox_norm"]), arr.shape)
        crop = arr[y0:y1, x0:x1]
        if cell["type"] in ("checkbox", "ack", "capture_trigger", "comb"):
            # The printed glyph must land inside its manifest bbox.
            assert (crop < 128).any(), f"no glyph ink inside bbox of {cell['id']}"
        elif cell["type"] == "capture":
            # Corner brackets present; interior only faint ruling (no dark ink).
            for cx, cy in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
                win = arr[max(0, cy - 80) : cy + 80, max(0, cx - 80) : cx + 80]
                assert (win < 128).any(), f"missing bracket at {(cx, cy)} for {cell['id']}"
            inner = arr[y0 + 100 : y1 - 100, x0 + 100 : x1 - 100]
            assert not (inner < 128).any(), f"dark ink inside capture interior {cell['id']}"


@pytest.mark.parametrize("scale", [0.85, 0.72])
def test_density_scale_geometry_roundtrip(tmp_path, scale):
    # A tighter density scales every content constant uniformly; the printed
    # glyph must still land inside its (normalized, scale-independent) manifest
    # bbox — the same check convert.targeted uses on the readback path.
    np = pytest.importorskip("numpy")
    pdfium = pytest.importorskip("pypdfium2")

    md = ("# Form\n\n- [ ] alpha\n- [ ] beta\n\n{choice: size | S | M | L}\n\n"
          "{comb: code n=4}\n\n{capture: sketch rows=6}\n\n{ack: reviewed}\n")
    res = compose(md, tmp_path / "d.pdf", scale=scale)
    assert json.loads(res.manifest_path.read_text())["layout"] == {"scale": scale}
    pdf = pdfium.PdfDocument(str(res.pdf_path))
    arr = np.asarray(pdf[0].render(scale=4).to_pil().convert("L"))
    for cell in res.cells:
        if cell["page"] != 1 or cell["type"] not in (
            "checkbox", "ack", "capture_trigger", "comb", "choice"):
            continue
        x0, y0, x1, y1 = _bbox_to_pixels(tuple(cell["bbox_norm"]), arr.shape)
        assert (arr[y0:y1, x0:x1] < 128).any(), f"no glyph ink in bbox of {cell['id']}"


def test_density_packs_more_rows_per_page(tmp_path):
    md = "# Long list\n\n" + "\n".join(f"- [ ] item {i}" for i in range(30))
    normal = compose(md, tmp_path / "n.pdf", scale=1.0)
    dense = compose(md, tmp_path / "d.pdf", scale=0.72)
    assert dense.pages < normal.pages  # same content, fewer pages


def test_density_output_deterministic(tmp_path):
    md = "# T\n\n- [ ] a\n- [ ] b\n\n{comb: code n=4}\n"
    a = compose(md, tmp_path / "a.pdf", scale=0.8)
    b = compose(md, tmp_path / "b.pdf", scale=0.8)
    assert a.pdf_path.read_bytes() == b.pdf_path.read_bytes()


def test_nonpositive_scale_rejected(tmp_path):
    with pytest.raises(ValueError, match="scale must be positive"):
        compose("- [ ] a\n", tmp_path / "x.pdf", scale=0)


def test_pagination_one_centered_trigger_per_page(tmp_path):
    md = "# Long list\n\n" + "\n".join(f"- [ ] item {i}" for i in range(40))
    res = compose(md, tmp_path / "long.pdf")
    assert res.pages >= 2
    triggers = [c for c in res.cells if c["type"] == "capture_trigger"]
    assert len(triggers) == res.pages
    # The trigger box is page-independent (centered), not a positional
    # fiducial: same x on every page, and it carries no page-identity extras.
    assert len({t["bbox_norm"][0] for t in triggers}) == 1
    for t in triggers:
        assert "slot" not in t and "fiducial_unique" not in t
    # every page carries exactly one trigger and no other strip cells
    for p in range(1, res.pages + 1):
        strip = [c for c in res.cells if c["id"].startswith("cmd.") and c["page"] == p]
        assert len(strip) == 1 and strip[0]["type"] == "capture_trigger"


@pytest.mark.parametrize("device", sorted(PROFILES))
def test_strip_clears_device_safe_bottom(tmp_path, device):
    # Chrome envelope (measured on the Manta with the 2026-07-20 ruler
    # fixture; assumed for the Nomad): the reader UI clips the bottom
    # corners below side_safe_bottom but leaves the center_x0..center_x1
    # band visible to center_safe_bottom. Only the corner registration
    # ticks (compositing-only) may break these.
    np = pytest.importorskip("numpy")
    pdfium = pytest.importorskip("pypdfium2")

    g = PROFILES[device]
    res = compose("# T\n\n- [ ] item\n", tmp_path / "t.pdf", device=device)
    pdf = pdfium.PdfDocument(str(res.pdf_path))
    arr = np.asarray(pdf[0].render(scale=4).to_pil().convert("L"))
    dark = arr < 128
    # sides (tick corners excluded; 6 px slack for a boundary box's own
    # stroke width): nothing below the side-safe line
    left = dark[g.side_safe_bottom + 4 :, g.content_x0 : g.center_x0 - 6]
    right = dark[g.side_safe_bottom + 4 :, g.center_x1 + 6 : g.content_x1]
    assert not left.any() and not right.any(), "side content below safe line"
    # center band: nothing below the deeper center-safe line
    center = dark[g.center_safe_bottom + 4 :, g.center_x0 : g.center_x1]
    assert not center.any(), "center content below center-safe line"


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
        x, y, _, _ = cell["bbox_norm"]
        px = int(x * 1920) + MANTA.glyph_pad - 40
        py = int(y * 2560) + MANTA.glyph_pad - 35
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


@pytest.mark.parametrize("device", sorted(PROFILES))
def test_trigger_box_centered_in_visible_band(device):
    g = PROFILES[device]
    x = g.trigger_center_x0
    assert x == (g.canvas_w - g.trigger_box) // 2  # dead center
    assert g.center_x0 <= x and x + g.trigger_box <= g.center_x1


def test_device_profiles_share_physical_constants():
    # Both panels are ~300 PPI: the hand-ergonomic sizes must not drift
    # between profiles — only canvas and chrome envelope may differ.
    manta, nomad = PROFILES["manta"], PROFILES["nomad"]
    for attr in ("glyph_box", "glyph_pad", "trigger_box",
                 "margin_x", "content_top"):
        assert getattr(manta, attr) == getattr(nomad, attr)
    assert manta.chrome_calibrated and not nomad.chrome_calibrated
    assert (nomad.canvas_w, nomad.canvas_h) == (1404, 1872)


def test_manifest_carries_device_block(tmp_path):
    res = compose("- [ ] a\n", tmp_path / "n.pdf", device="nomad")
    manifest = json.loads(res.manifest_path.read_text())
    assert manifest["device"] == {"name": "nomad", "chrome_calibrated": False}
    assert manifest["canvas"] == {"width": 1404, "height": 1872}
    m = json.loads(compose("- [ ] a\n", tmp_path / "m.pdf").manifest_path.read_text())
    assert m["device"] == {"name": "manta", "chrome_calibrated": True}
    assert m["canvas"] == {"width": 1920, "height": 2560}


def test_unknown_device_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown device"):
        compose("- [ ] a\n", tmp_path / "x.pdf", device="a6x")


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


def test_comb_directives():
    c1, c2 = parse("{comb: date n=10}\n\n{comb: zip}\n")
    assert isinstance(c1, Comb) and c1.n == 10
    assert isinstance(c2, Comb) and c2.n == 8  # default


def test_slider_directive_is_not_recognized():
    # slider was removed; a {slider: ...} directive is no longer parsed as an
    # input cell — it degrades to a visible Paragraph like any non-directive.
    (block,) = parse("{slider: mood | low | high}\n")
    assert isinstance(block, Paragraph)


def test_comb_manifest_extras(tmp_path):
    res = compose("{comb: date n=6}\n", tmp_path / "s.pdf")
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
    assert {c["type"] for c in res.cells} == {"capture_trigger"}


def _compose_cli(*args):
    from click.testing import CliRunner

    from inkbridge.cli import main
    return CliRunner().invoke(main, ["compose", *args])


def test_cli_compose_json_payload(tmp_path):
    # doc_id is a structured field of the compose.v1 result, not prose.
    src = tmp_path / "f.md"
    src.write_text("# Form\n\n- [ ] alpha\n- [x] beta\n")
    res = _compose_cli(str(src), "-o", str(tmp_path / "f.pdf"), "--json")
    assert res.exit_code == 0
    payload = json.loads(res.stdout)
    assert payload["schema_version"] == "compose.v1"
    assert payload["doc_id"]
    assert payload["pdf"].endswith("f.pdf")
    assert payload["manifest"].endswith("f.manifest.json")
    assert payload["cells"] >= 1 and payload["pages"] >= 1
    assert payload["device"] == "manta"
    # the structured doc_id matches what the written manifest carries
    manifest = json.loads((tmp_path / "f.manifest.json").read_text())
    assert manifest["doc_id"] == payload["doc_id"]


def test_cli_compose_json_invalid_source_is_error(tmp_path):
    src = tmp_path / "f.md"
    src.write_text("- [ ] a\n")
    res = _compose_cli(str(src), "-o", str(tmp_path / "f.pdf"), "--scale", "0", "--json")
    assert res.exit_code == 1
    assert res.stdout == ""  # --json keeps stdout pure; the error is on stderr
    assert json.loads(res.stderr)["error"]["code"] == "invalid_source"
