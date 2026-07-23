"""Device geometry is fully profile-driven (G2): no module-scope canvas
constant, and a synthetic non-Manta profile (different PPI/aspect) composes and
round-trips through the geometry the same way the Manta does."""

from __future__ import annotations

import pytest

from inkbridge.compose.geometry import MM_PER_INCH, DeviceProfile


def _alt_profile() -> DeviceProfile:
    """A synthetic panel unlike any real one: a near-square aspect (not 3:4)
    and a distinctly non-300 PPI, so any Manta-specific assumption would break."""
    return DeviceProfile(
        name="alt", canvas_w=1000, canvas_h=1100, ppi=250.0,
        strip_top=980, side_safe_bottom=1000, center_safe_bottom=1050,
        center_x0=350, center_x1=650, chrome_calibrated=False,
    )


def test_derived_geometry_is_profile_driven():
    alt = _alt_profile()
    # row_h derives from the physical mm target and THIS profile's PPI — not a
    # module constant, so it differs from the ~300 PPI panels' 80 px.
    assert alt.row_h == round(alt.row_mm / MM_PER_INCH * alt.ppi)
    assert alt.row_h != 80
    # pt canvas follows the profile's own pt_per_px and canvas dims.
    assert alt.page_w_pt == alt.canvas_w * alt.pt_per_px
    assert alt.page_h_pt == alt.canvas_h * alt.pt_per_px
    # normalized bbox round-trips against the profile's canvas.
    x, y, w, h = 130, 160, 90, 90
    nx, ny, nw, nh = alt.norm(x, y, w, h)
    assert round(nx * alt.canvas_w) == x and round(ny * alt.canvas_h) == y
    assert round(nw * alt.canvas_w) == w and round(nh * alt.canvas_h) == h


def test_alt_profile_roundtrips(tmp_path, monkeypatch):
    # compose→geometry against a synthetic non-Manta profile: the composed PDF
    # rasterizes back to the profile's canvas, and every printed glyph lands
    # inside its manifest bbox — proving the pipeline reads geometry from the
    # profile, not from Manta module constants.
    np = pytest.importorskip("numpy")
    pdfium = pytest.importorskip("pypdfium2")

    from inkbridge.compose import compose
    from inkbridge.compose import profiles as profiles_mod
    from inkbridge.convert.targeted import _bbox_to_pixels

    alt = _alt_profile()
    monkeypatch.setitem(profiles_mod.PROFILES, "alt", alt)

    res = compose("# Form\n\n- [ ] alpha\n- [ ] beta\n\n{ack: agree}\n",
                  tmp_path / "form.pdf", device="alt")

    pdf = pdfium.PdfDocument(str(res.pdf_path))
    try:
        pil = pdf[0].render(scale=1 / alt.pt_per_px).to_pil().convert("L")
    finally:
        pdf.close()
    # The page rasterizes exactly to the synthetic canvas — the aspect and scale
    # came from the profile, not a 3:4 / 1920x2560 assumption.
    assert pil.size == (alt.canvas_w, alt.canvas_h)

    arr = np.asarray(pil)
    tickable = [c for c in res.cells if c["type"] in ("checkbox", "ack")]
    assert tickable, "expected tickable cells to check"
    for cell in tickable:
        x0, y0, x1, y1 = _bbox_to_pixels(tuple(cell["bbox_norm"]), arr.shape)
        assert (arr[y0:y1, x0:x1] < 128).any(), f"no glyph ink in bbox of {cell['id']}"
