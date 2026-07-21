"""`collect` materializes the answers sidecar (ADR-0003): pull the mark,
resolve, write `<doc>.answers.json` — with NO ledger mutation and the
contract exit codes (3 no-response / 4 unknown-doc / 6 no-manifest).

Transport is stubbed (the real pull is covered by test_private_cloud) and
read_mark is synthetic (covered by test_readback/test_answers), so these
tests exercise collect's own materialize/no-mutate/exit-code logic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from inkbridge.readback import CellReading, Decision, PageReading


def _page(cells):
    return PageReading(page=1, ink_hash="h", cells=cells)


def _cell(id_, type_, decision, label=None):
    return CellReading(id=id_, type=type_, label=label, page=1,
                       coverage=0.0, decision=decision)


class _StubClient:
    """Stands in for PCClient: writes a placeholder mark and returns pull
    info, or raises FileNotFoundError to model 'no response yet'."""

    def __init__(self, respond=True):
        self.respond = respond

    def pull(self, folder, name, dest):
        if not self.respond:
            raise FileNotFoundError(f"{folder}/{name} not on server")
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake-mark-bytes")
        return {"listing_md5": "aa" * 16, "bytes_md5": "bb" * 16,
                "size": 15, "match": True}


@pytest.fixture()
def ledger_and_manifest(tmp_path):
    """A ledger with one manifest-backed entry; returns (ledger_path, doc_id)."""
    manifest = tmp_path / "form.manifest.json"
    manifest.write_text(json.dumps({"doc_id": "form-abc12345", "cells": []}))
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps({"entries": [{
        "doc_id": "form-abc12345",
        "remote": {"folder": "Document", "name": "form.pdf"},
        "manifest": str(manifest),
        "mark_md5": None, "acknowledged_at": None,
    }]}))
    return ledger, "form-abc12345"


@pytest.fixture()
def stub(monkeypatch):
    def _install(*, respond=True, pages=None):
        monkeypatch.setattr(
            "inkbridge.transport.private_cloud.PCClient.from_env",
            classmethod(lambda cls: _StubClient(respond=respond)))
        if pages is not None:
            monkeypatch.setattr("inkbridge.readback.read_mark",
                                lambda manifest, mark_path, **kw: pages)
    return _install


def _run(ledger, doc_id, out, *extra):
    from inkbridge.cli import main
    return CliRunner().invoke(
        main, ["collect", doc_id, "--ledger", str(ledger), "-o", str(out), *extra])


def test_collect_writes_sidecar_exit_ok(ledger_and_manifest, stub, tmp_path):
    ledger, doc_id = ledger_and_manifest
    stub(pages=[_page([
        _cell("choice.meal.eggs", "choice", Decision.ANSWERED, "meal: eggs"),
        _cell("choice.meal.oats", "choice", Decision.BLANK, "meal: oats"),
        _cell("ack.terms", "ack", Decision.ANSWERED, "terms"),
    ])])
    out = tmp_path / "responses"
    res = _run(ledger, doc_id, out, "--json")
    assert res.exit_code == 0

    doc = json.loads(res.stdout)
    assert doc["schema_version"] == "collect.v1"
    assert doc["mark_md5"] == "aa" * 16  # provenance = the listing md5

    sidecar = Path(doc["answers_file"])
    assert sidecar == out / f"{doc_id}.answers.json"
    written = json.loads(sidecar.read_text())
    assert written["schema_version"] == "answers.v1"
    assert written["doc_id"] == doc_id
    assert written["mark_md5"] == "aa" * 16
    by_id = {a["id"]: a for a in written["answers"]}
    assert by_id["choice.meal"]["value"] == "eggs"
    assert by_id["ack.terms"]["value"] is True


def test_collect_does_not_mutate_ledger(ledger_and_manifest, stub, tmp_path):
    # ADR-0003: collect no longer acknowledges — reading materializes a file,
    # it does not advance the ledger.
    ledger, doc_id = ledger_and_manifest
    before = ledger.read_bytes()
    stub(pages=[_page([_cell("ack.t", "ack", Decision.ANSWERED, "t")])])
    _run(ledger, doc_id, tmp_path / "r", "--json")
    assert ledger.read_bytes() == before


def test_collect_no_response_yet_is_exit_3(ledger_and_manifest, stub, tmp_path):
    ledger, doc_id = ledger_and_manifest
    stub(respond=False)
    res = _run(ledger, doc_id, tmp_path / "r", "--json")
    assert res.exit_code == 3          # NO_CHANGE — a poll with nothing to do
    assert res.stdout == ""
    assert json.loads(res.stderr)["error"]["code"] == "no_response"


def test_collect_unknown_doc_is_exit_4(ledger_and_manifest, stub, tmp_path):
    ledger, _ = ledger_and_manifest
    res = _run(ledger, "no-such-doc", tmp_path / "r", "--json")
    assert res.exit_code == 4
    assert json.loads(res.stderr)["error"]["code"] == "unknown_doc"


def test_collect_manifestless_doc_is_exit_6(tmp_path):
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps({"entries": [{
        "doc_id": "bare-1",
        "remote": {"folder": "Document", "name": "bare.pdf"},
        "manifest": None, "mark_md5": None, "acknowledged_at": None,
    }]}))
    res = _run(ledger, "bare-1", tmp_path / "r", "--json")
    assert res.exit_code == 6          # PRECONDITION — no manifest to resolve against
    assert json.loads(res.stderr)["error"]["code"] == "no_manifest"


def test_collect_human_mode_no_json_noise(ledger_and_manifest, stub, tmp_path):
    ledger, doc_id = ledger_and_manifest
    stub(pages=[_page([_cell("ack.t", "ack", Decision.ANSWERED, "t")])])
    res = _run(ledger, doc_id, tmp_path / "r")
    assert res.exit_code == 0
    assert "answers:" in res.stdout and doc_id in res.stdout
    assert not res.stdout.lstrip().startswith("{")
