"""MCP server tool tests.

Drives the six MCP tools (:mod:`inkbridge.mcp`) directly — no MCP client — the
way ``test_ops`` drives the ops layer: the transport ``connect`` seam is
injected by monkeypatching ``inkbridge.mcp._connect`` to ``lambda: client``
(the ``client``/``server`` fake-cloud fixtures), and each tool is passed an
explicit ``ledger_path`` under ``tmp_path``. Asserts each tool returns the same
``*.v1`` body the CLI emits, that the typed-error paths surface the CLI's
``code`` string as a ``ToolError``, and that ``composite_page`` returns an inline
PNG. ``compose`` and ``composite_page`` need no cloud.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fake_cloud import FakeServer
from mcp.server.fastmcp import Image
from mcp.server.fastmcp.exceptions import ToolError

from inkbridge import mcp
from inkbridge.dispatch import Ledger
from inkbridge.readback import CellReading, Decision, PageReading
from inkbridge.transport.private_cloud import PCClient

FIXTURES = Path(__file__).parent / "fixtures"

MANIFEST = {
    "doc_id": "form-abc12345",
    "cells": [
        {"id": "checkbox.milk", "type": "checkbox", "page": 1},
        {"id": "choice.size.m", "type": "choice", "page": 1},
        {"id": "cmd.capture.p1", "type": "capture_trigger", "page": 1},
    ],
}


@pytest.fixture()
def inject(client: PCClient, monkeypatch):
    """Wire the tools' lazy connector to the fake cloud, as the CLI wires
    ``transport.connect``."""
    monkeypatch.setattr(mcp, "_connect", lambda: client)
    return client


def _seed_base(tmp_path: Path, *, manifest=MANIFEST):
    """Write a base doc + manifest and return (file, manifest_path|None, ledger_path)."""
    f = tmp_path / "form.pdf"
    f.write_bytes(b"%PDF-form")
    manifest_path = None
    if manifest is not None:
        manifest_path = tmp_path / "form.manifest.json"
        manifest_path.write_text(json.dumps(manifest))
    return f, manifest_path, tmp_path / "ledger.json"


# -- compose (no cloud) ---------------------------------------------------

def test_compose_from_ir_returns_compose_v1(tmp_path: Path):
    out = tmp_path / "quiz.pdf"
    payload = mcp.compose(output_pdf=str(out), blocks=[
        {"kind": "heading", "level": 1, "text": "Quiz"},
        {"kind": "checkbox", "label": "Ready?"},
    ])
    assert payload["pdf"] == str(out)
    assert payload["manifest"] == str(tmp_path / "quiz.manifest.json")
    assert payload["doc_id"].startswith("quiz-")
    assert payload["pages"] == 1
    assert payload["cells"] == 2
    assert payload["device"] == "manta" and payload["scale"] == 0.72  # dense default
    # Artifacts really materialized, so dispatch can push them.
    assert out.exists() and Path(payload["manifest"]).exists()


def test_compose_markdown_scale_override(tmp_path: Path):
    out = tmp_path / "note.pdf"
    payload = mcp.compose(source_markdown="# Hi\n\nBody.\n",
                          output_pdf=str(out), scale=1.0)
    assert payload["scale"] == 1.0 and out.exists()


def test_compose_requires_exactly_one_source(tmp_path: Path):
    out = tmp_path / "x.pdf"
    with pytest.raises(ToolError, match=r"\[invalid_source\]"):
        mcp.compose(output_pdf=str(out))  # neither
    with pytest.raises(ToolError, match=r"\[invalid_source\]"):
        mcp.compose(output_pdf=str(out), source_markdown="# a", blocks=[])  # both


def test_compose_unknown_density_is_invalid_source(tmp_path: Path):
    with pytest.raises(ToolError, match=r"\[invalid_source\]"):
        mcp.compose(output_pdf=str(tmp_path / "x.pdf"),
                    source_markdown="# a", density="huge")


def test_compose_bad_ir_kind_is_invalid_source(tmp_path: Path):
    with pytest.raises(ToolError, match=r"\[invalid_source\]"):
        mcp.compose(output_pdf=str(tmp_path / "x.pdf"),
                    blocks=[{"kind": "no_such_kind"}])


# -- dispatch -------------------------------------------------------------

def test_dispatch_returns_dispatch_v1_and_persists_ledger(inject, tmp_path: Path):
    f, manifest_path, ledger_path = _seed_base(tmp_path)
    payload = mcp.dispatch(str(f), manifest_path=str(manifest_path),
                           ledger_path=str(ledger_path))
    assert payload == {
        "doc_id": "form-abc12345",
        "remote": {"folder": "Document", "name": "form.pdf"},
        "manifest": str(manifest_path),
        "response_cells": 2,
        "trigger_cells": 1,
        "ledger": str(ledger_path),
    }
    assert Ledger(ledger_path).find("form-abc12345") is not None


def test_dispatch_replace_true_is_idempotent(inject, tmp_path: Path):
    """The MCP default replace=true makes a re-dispatch succeed where the
    cloud's no-overwrite would otherwise raise already_exists."""
    f, manifest_path, ledger_path = _seed_base(tmp_path)
    kw = dict(manifest_path=str(manifest_path), ledger_path=str(ledger_path))
    mcp.dispatch(str(f), **kw)
    payload = mcp.dispatch(str(f), **kw)  # would fail without replace=true
    assert payload["doc_id"] == "form-abc12345"


def test_dispatch_missing_folder_maps_not_found(inject, tmp_path: Path):
    f, _, ledger_path = _seed_base(tmp_path, manifest=None)
    with pytest.raises(ToolError, match=r"\[not_found\]"):
        mcp.dispatch(str(f), remote_folder="Nonexistent",
                     ledger_path=str(ledger_path))


# -- status ---------------------------------------------------------------

def test_status_returns_status_v1(inject, server: FakeServer, tmp_path: Path):
    f, manifest_path, ledger_path = _seed_base(tmp_path)
    mcp.dispatch(str(f), manifest_path=str(manifest_path),
                 ledger_path=str(ledger_path))

    payload = mcp.status(ledger_path=str(ledger_path))
    assert payload["ledger"] == str(ledger_path)
    (row,) = payload["entries"]
    assert row == {
        "doc_id": "form-abc12345",
        "remote": "Document/form.pdf",
        "state": "waiting",
        "mark_md5": None,
        "base_changed": False,
    }

    # A .mark lands; acknowledge=True persists the ledger.
    server.rows["form.pdf.mark"] = server.row(
        "form.pdf.mark", "a" * 32, 100, "id-form.pdf.mark")
    payload = mcp.status(acknowledge=True, ledger_path=str(ledger_path))
    (row,) = payload["entries"]
    assert row["state"] == "responded" and row["mark_md5"] == "a" * 32
    assert Ledger(ledger_path).entries[0]["mark_md5"] == "a" * 32


# -- wait_for_response ----------------------------------------------------

def test_wait_returns_on_arrived_mark(inject, server: FakeServer, tmp_path: Path):
    f, manifest_path, ledger_path = _seed_base(tmp_path)
    mcp.dispatch(str(f), manifest_path=str(manifest_path),
                 ledger_path=str(ledger_path))
    # Mark already present -> the first poll returns without sleeping.
    server.rows["form.pdf.mark"] = server.row(
        "form.pdf.mark", "a" * 32, 100, "id-form.pdf.mark")
    row = mcp.wait_for_response("form-abc12345", timeout_s=5,
                                ledger_path=str(ledger_path))
    assert row["state"] == "responded" and row["mark_md5"] == "a" * 32


def test_wait_unknown_doc_maps_unknown_doc(inject, tmp_path: Path):
    _, _, ledger_path = _seed_base(tmp_path, manifest=None)
    with pytest.raises(ToolError, match=r"\[unknown_doc\]"):
        mcp.wait_for_response("no-such-doc", timeout_s=1,
                              ledger_path=str(ledger_path))


# -- collect --------------------------------------------------------------

def _dispatch_and_respond(client: PCClient, tmp_path: Path, mark_bytes=b"ink"):
    """Dispatch a manifest-backed doc via the tool and land its .mark response."""
    f, manifest_path, ledger_path = _seed_base(tmp_path)
    mcp.dispatch(str(f), manifest_path=str(manifest_path),
                 ledger_path=str(ledger_path))
    mark = tmp_path / "form.pdf.mark"
    mark.write_bytes(mark_bytes)
    client.push(mark, "Document")  # the .mark row + bytes now exist server-side
    return ledger_path


def test_collect_returns_collect_v1_and_writes_sidecar(inject, tmp_path: Path,
                                                       monkeypatch):
    ledger_path = _dispatch_and_respond(inject, tmp_path, mark_bytes=b"ink-bytes")
    monkeypatch.setattr(
        "inkbridge.readback.read_mark",
        lambda manifest, mark_path, **kw: [PageReading(page=1, ink_hash="h", cells=[
            CellReading(id="ack.terms", type="ack", label="terms", page=1,
                        coverage=0.0, decision=Decision.ANSWERED)])])
    out = tmp_path / "responses"
    payload = mcp.collect("form-abc12345", output_dir=str(out),
                          ledger_path=str(ledger_path))

    assert payload["doc_id"] == "form-abc12345"
    assert payload["mark_file"] == str(out / "form.pdf.mark")
    assert payload["mark_md5"] == hashlib.md5(b"ink-bytes").hexdigest()
    assert payload["answers_file"] == str(out / "form-abc12345.answers.json")
    by_id = {a["id"]: a for a in payload["answers"]}
    assert by_id["ack.terms"]["value"] is True

    written = json.loads(Path(payload["answers_file"]).read_text())
    assert written["schema_version"] == "answers.v1"
    # collect never mutates the ledger.
    assert Ledger(ledger_path).entries[0]["mark_md5"] is None


def test_collect_unknown_doc_maps_unknown_doc(inject, tmp_path: Path):
    ledger_path = tmp_path / "ledger.json"  # empty
    with pytest.raises(ToolError, match=r"\[unknown_doc\]"):
        mcp.collect("no-such-doc", output_dir=str(tmp_path),
                    ledger_path=str(ledger_path))


def test_collect_no_manifest_maps_no_manifest(inject, tmp_path: Path):
    f, _, ledger_path = _seed_base(tmp_path, manifest=None)
    mcp.dispatch(str(f), ledger_path=str(ledger_path))
    doc_id = Ledger(ledger_path).entries[0]["doc_id"]
    with pytest.raises(ToolError, match=r"\[no_manifest\]"):
        mcp.collect(doc_id, output_dir=str(tmp_path), ledger_path=str(ledger_path))


def test_collect_no_response_maps_no_response(inject, tmp_path: Path):
    f, manifest_path, ledger_path = _seed_base(tmp_path)
    mcp.dispatch(str(f), manifest_path=str(manifest_path),
                 ledger_path=str(ledger_path))
    # base present but no .mark ever landed -> pull FileNotFoundError.
    with pytest.raises(ToolError, match=r"\[no_response\]"):
        mcp.collect("form-abc12345", output_dir=str(tmp_path),
                    ledger_path=str(ledger_path))


# -- composite_page (no cloud, real fixtures) -----------------------------

def test_composite_page_returns_inline_png(tmp_path: Path):
    out = tmp_path / "composite.png"
    result = mcp.composite_page(
        base_pdf=str(FIXTURES / "sampler_form.pdf"),
        mark_path=str(FIXTURES / "sampler_form.pdf.mark"),
        page_number=1, output_png=str(out))
    img, note = result
    assert isinstance(img, Image)
    assert isinstance(note, str) and str(out) in note
    # Saved PNG is a real, non-trivial image.
    assert out.exists() and out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_composite_page_missing_base_maps_not_found(tmp_path: Path):
    with pytest.raises(ToolError, match=r"\[not_found\]"):
        mcp.composite_page(base_pdf=str(tmp_path / "nope.pdf"),
                           mark_path=str(FIXTURES / "sampler_form.pdf.mark"),
                           page_number=1)


# -- the tool surface -----------------------------------------------------

def test_no_cli_import():
    """The server must reach the domain through ops/compose/composite, never
    the Click front-end. Checked in a fresh interpreter, since other test
    modules in a full run import ``inkbridge.cli`` and pollute ``sys.modules``."""
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-c",
         "import inkbridge.mcp, sys; "
         "sys.exit(1 if 'inkbridge.cli' in sys.modules else 0)"],
        capture_output=True, text=True)
    assert proc.returncode == 0, (
        f"importing inkbridge.mcp pulled in inkbridge.cli\n{proc.stderr}")
