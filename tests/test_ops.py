"""In-process operations layer (ADR-0006 / remediation A1).

Drives ``ops.{dispatch,status,collect}`` directly — no Click — against the
mocked private cloud (``fake_cloud`` via the ``client``/``server`` fixtures)
and a temp ledger, asserting:

- the RETURNED payloads equal what the CLI emits today (``dispatch.v1`` body,
  the status-row list, the ``collect.v1`` body + sidecar);
- ``ops`` owns the domain writes (ledger persisted, acknowledgement persisted,
  answers sidecar materialized) while ``collect`` leaves the ledger untouched;
- the typed domain errors raise on the unknown-doc / no-manifest / no-response
  paths (so the CLI can map them to the exit taxonomy);
- and structurally, the three command bodies now DELEGATE to ``ops`` with no
  orchestration left inline.

``connect`` is injected as a zero-arg connector (``lambda: client``), matching
how the CLI passes ``PCClient.from_env``.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest
from fake_cloud import FakeServer

from inkbridge import ops
from inkbridge.dispatch import Ledger
from inkbridge.readback import CellReading, Decision, PageReading
from inkbridge.transport.private_cloud import PCClient

MANIFEST = {
    "doc_id": "form-abc12345",
    "cells": [
        {"id": "checkbox.milk", "type": "checkbox", "page": 1},
        {"id": "choice.size.m", "type": "choice", "page": 1},
        {"id": "cmd.capture.p1", "type": "capture_trigger", "page": 1},
    ],
}


def _connect(client):
    """The injected connector the CLI models as ``PCClient.from_env``."""
    return lambda: client


def _seed_base(client: PCClient, tmp_path: Path, *, manifest=MANIFEST):
    """Push a base doc and return (file, manifest_path|None, ledger)."""
    f = tmp_path / "form.pdf"
    f.write_bytes(b"%PDF-form")
    manifest_path = None
    if manifest is not None:
        manifest_path = tmp_path / "form.manifest.json"
        manifest_path.write_text(json.dumps(manifest))
    return f, manifest_path, Ledger(tmp_path / "ledger.json")


# -- dispatch -------------------------------------------------------------

def test_dispatch_returns_dispatch_v1_and_persists_ledger(client: PCClient,
                                                          tmp_path: Path):
    f, manifest_path, ledger = _seed_base(client, tmp_path)
    payload = ops.dispatch(_connect(client), ledger, f,
                           remote_folder="Document", manifest_path=manifest_path)
    # Byte-for-byte the dispatch.v1 body the CLI wraps in emit_result.
    assert payload == {
        "doc_id": "form-abc12345",
        "remote": {"folder": "Document", "name": "form.pdf"},
        "manifest": str(manifest_path),
        "response_cells": 2,
        "trigger_cells": 1,
        "ledger": str(ledger.path),
    }
    # Domain write: the ledger was upserted AND saved (reload sees the entry).
    assert Ledger(ledger.path).find("form-abc12345") is not None


def test_dispatch_without_manifest_tracks_arrival_only(client: PCClient,
                                                       tmp_path: Path):
    f, _, ledger = _seed_base(client, tmp_path, manifest=None)
    payload = ops.dispatch(_connect(client), ledger, f,
                           remote_folder="Document", manifest_path=None)
    md5 = hashlib.md5(b"%PDF-form").hexdigest()
    assert payload["doc_id"] == f"form-{md5[:8]}"
    assert payload["manifest"] is None
    assert payload["response_cells"] == 0 and payload["trigger_cells"] == 0


def test_dispatch_missing_folder_propagates_filenotfound(client: PCClient,
                                                        tmp_path: Path):
    f, _, ledger = _seed_base(client, tmp_path, manifest=None)
    # A folder the fake cloud can't resolve -> the CLI maps this to NOT_FOUND.
    with pytest.raises(FileNotFoundError):
        ops.dispatch(_connect(client), ledger, f,
                     remote_folder="Nonexistent", manifest_path=None)


# -- status ---------------------------------------------------------------

def test_status_returns_rows_and_acknowledges(client: PCClient, server: FakeServer,
                                             tmp_path: Path):
    f, manifest_path, ledger = _seed_base(client, tmp_path)
    ops.dispatch(_connect(client), ledger, f,
                 remote_folder="Document", manifest_path=manifest_path)

    (row,) = ops.status(_connect(client), ledger, acknowledge=False)
    assert row == {
        "doc_id": "form-abc12345",
        "remote": "Document/form.pdf",
        "state": "waiting",
        "mark_md5": None,
        "base_changed": False,
    }

    # A .mark response lands; acknowledge=True must persist the ledger.
    server.rows["form.pdf.mark"] = server.row(
        "form.pdf.mark", "a" * 32, 100, "id-form.pdf.mark")
    (row,) = ops.status(_connect(client), ledger, acknowledge=True)
    assert row["state"] == "responded" and row["mark_md5"] == "a" * 32
    assert Ledger(ledger.path).entries[0]["mark_md5"] == "a" * 32  # persisted


# -- collect --------------------------------------------------------------

def _dispatch_and_respond(client: PCClient, tmp_path: Path, mark_bytes=b"ink"):
    """Dispatch a manifest-backed doc and land a .mark response for it."""
    f, manifest_path, ledger = _seed_base(client, tmp_path)
    ops.dispatch(_connect(client), ledger, f,
                 remote_folder="Document", manifest_path=manifest_path)
    mark = tmp_path / "form.pdf.mark"
    mark.write_bytes(mark_bytes)
    client.push(mark, "Document")  # the .mark row + bytes now exist server-side
    return ledger


def test_collect_returns_collect_v1_and_writes_sidecar(client: PCClient,
                                                      tmp_path: Path, monkeypatch):
    ledger = _dispatch_and_respond(client, tmp_path, mark_bytes=b"ink-bytes")
    monkeypatch.setattr(
        "inkbridge.readback.read_mark",
        lambda manifest, mark_path, **kw: [PageReading(page=1, ink_hash="h", cells=[
            CellReading(id="ack.terms", type="ack", label="terms", page=1,
                        coverage=0.0, decision=Decision.ANSWERED)])])
    out = tmp_path / "responses"
    payload = ops.collect(_connect(client), ledger, "form-abc12345", output_dir=out)

    assert payload["doc_id"] == "form-abc12345"
    assert payload["mark_file"] == str(out / "form.pdf.mark")
    assert payload["mark_md5"] == hashlib.md5(b"ink-bytes").hexdigest()
    assert payload["answers_file"] == str(out / "form-abc12345.answers.json")
    by_id = {a["id"]: a for a in payload["answers"]}
    assert by_id["ack.terms"]["value"] is True

    # Domain write: sidecar materialized under output_dir with the envelope.
    written = json.loads(Path(payload["answers_file"]).read_text())
    assert written["schema_version"] == "answers.v1"
    assert written["mark_md5"] == payload["mark_md5"]
    # collect NEVER mutates the ledger (ADR-0003).
    assert Ledger(ledger.path).entries[0]["mark_md5"] is None


def test_collect_unknown_doc_raises_typed(client: PCClient, tmp_path: Path):
    ledger = Ledger(tmp_path / "ledger.json")  # empty
    with pytest.raises(ops.UnknownDocError):
        ops.collect(_connect(client), ledger, "no-such-doc", output_dir=tmp_path)


def test_collect_no_manifest_raises_typed(client: PCClient, tmp_path: Path):
    f, _, ledger = _seed_base(client, tmp_path, manifest=None)
    ops.dispatch(_connect(client), ledger, f,
                 remote_folder="Document", manifest_path=None)
    doc_id = ledger.entries[0]["doc_id"]
    with pytest.raises(ops.NoManifestError):
        ops.collect(_connect(client), ledger, doc_id, output_dir=tmp_path)


def test_collect_no_response_raises_typed(client: PCClient, tmp_path: Path):
    f, manifest_path, ledger = _seed_base(client, tmp_path)
    ops.dispatch(_connect(client), ledger, f,
                 remote_folder="Document", manifest_path=manifest_path)
    # base is present but no .mark ever landed -> pull FileNotFoundError.
    with pytest.raises(ops.NoResponseError):
        ops.collect(_connect(client), ledger, "form-abc12345", output_dir=tmp_path)


# -- structural: the command bodies delegate ------------------------------

def test_command_bodies_delegate_to_ops():
    """No orchestration remains inline in the three verbs: each command body
    calls ``ops.<verb>`` and none of the composing primitives it used to own."""
    from inkbridge import cli

    forbidden = {
        "dispatch": ["entry_for(", ".upsert(", "ledger.save("],
        "status": ["check_entries(", "acknowledge("],
        "collect": ["resolve_answers(", "answers_payload(", ".write_text("],
    }
    for verb, banned in forbidden.items():
        src = inspect.getsource(getattr(cli, verb).callback)
        assert f"ops.{verb}(" in src, f"{verb} does not delegate to ops.{verb}"
        for token in banned:
            assert token not in src, f"{verb} still orchestrates inline: {token!r}"
