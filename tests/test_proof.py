"""`proof` — device-free self-test (Analysis 0017 F8): stamp synthetic ink
into every manifest cell, read it back, assert all ANSWERED.

Exercises the pure ``proof()`` over a real composed manifest and over a
deliberately-degenerate one, plus the CLI verb's contract exit codes.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from inkbridge.compose import compose
from inkbridge.proof import proof, proof_payload, stamp_pages

pytest.importorskip("numpy")

FORM = ("# Form\n\n- [ ] alpha\n- [x] beta\n\n"
        "{choice: size | S | M | L}\n\n{comb: code n=4}\n\n"
        "{capture: sketch rows=4}\n\n{ack: reviewed}\n")


def _manifest(tmp_path, md=FORM, device="manta"):
    res = compose(md, tmp_path / "f.pdf", device=device)
    return json.loads(res.manifest_path.read_text())


@pytest.mark.parametrize("device", ["manta", "nomad"])
def test_proof_passes_on_a_real_manifest(tmp_path, device):
    result = proof(_manifest(tmp_path, device=device))
    assert result.ok
    assert result.failures == []
    assert result.cells > 0
    assert result.pages >= 1


def test_proof_covers_every_cell(tmp_path):
    manifest = _manifest(tmp_path)
    result = proof(manifest)
    # every manifest cell is stamped and asserted — nothing silently skipped
    assert result.cells == len(manifest["cells"])


def test_stamp_pages_paints_one_array_per_page(tmp_path):
    md = "# L\n\n" + "\n".join(f"- [ ] item {i}" for i in range(40))
    manifest = _manifest(tmp_path, md=md)
    grays = stamp_pages(manifest)
    assert set(grays) == {c["page"] for c in manifest["cells"]}
    for gray in grays.values():
        assert gray.shape == (manifest["canvas"]["height"],
                              manifest["canvas"]["width"])


def test_proof_flags_a_degenerate_bbox(tmp_path):
    manifest = _manifest(tmp_path)
    # An out-of-bounds bbox maps to an empty crop -> BLANK, not ANSWERED.
    manifest["cells"][0]["bbox_norm"] = [1.0, 1.0, 0.0, 0.0]
    bad_id = manifest["cells"][0]["id"]
    result = proof(manifest)
    assert not result.ok
    assert [f.id for f in result.failures] == [bad_id]
    assert result.failures[0].decision == "blank"


def test_proof_missing_canvas_raises(tmp_path):
    manifest = _manifest(tmp_path)
    del manifest["canvas"]
    with pytest.raises(ValueError, match="canvas"):
        proof(manifest)


def test_proof_payload_shape(tmp_path):
    payload = proof_payload(proof(_manifest(tmp_path)))
    assert payload["ok"] is True
    assert payload["failures"] == []
    assert set(payload) == {"doc_id", "pages", "cells", "ok", "failures"}


def _run(*args):
    from inkbridge.cli import main
    return CliRunner().invoke(main, ["proof", *args])


def test_cli_proof_passes(tmp_path):
    res = compose(FORM, tmp_path / "f.pdf")
    out = _run(str(res.manifest_path))
    assert out.exit_code == 0
    assert "PASS" in out.output


def test_cli_proof_json(tmp_path):
    res = compose(FORM, tmp_path / "f.pdf")
    out = _run(str(res.manifest_path), "--json")
    assert out.exit_code == 0
    payload = json.loads(out.output)
    assert payload["schema_version"] == "proof.v1"
    assert payload["ok"] is True


def test_cli_proof_fails_nonzero(tmp_path):
    res = compose(FORM, tmp_path / "f.pdf")
    manifest = json.loads(res.manifest_path.read_text())
    manifest["cells"][0]["bbox_norm"] = [1.0, 1.0, 0.0, 0.0]
    res.manifest_path.write_text(json.dumps(manifest))
    out = _run(str(res.manifest_path))
    assert out.exit_code == 1
    assert "FAIL" in out.output


def test_cli_proof_missing_manifest_not_found(tmp_path):
    out = _run(str(tmp_path / "nope.manifest.json"))
    assert out.exit_code == 4
