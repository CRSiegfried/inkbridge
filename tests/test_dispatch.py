"""Dispatch-ledger tests: entry construction, persistence, and the
status join (Analysis 0011: base md5 anchor -> sibling .mark locator ->
.mark md5 as the ink signal) against the mocked private cloud.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest
from click.testing import CliRunner
from fake_cloud import FakeServer

from inkbridge.dispatch import Ledger, acknowledge, check_entries, entry_for
from inkbridge.transport.private_cloud import PCClient

MANIFEST = {
    "doc_id": "form-abc12345",
    "cells": [
        {"id": "checkbox.milk", "type": "checkbox", "page": 1},
        {"id": "choice.size.m", "type": "choice", "page": 1},
        {"id": "cmd.capture.p1", "type": "capture_trigger", "page": 1},
    ],
}


def _dispatch(client: PCClient, tmp_path: Path, manifest=MANIFEST,
              name="form.pdf", data=b"%PDF-form") -> dict:
    f = tmp_path / name
    f.write_bytes(data)
    info = client.push(f, "Document")
    return entry_for(f, info, manifest,
                     tmp_path / "form.manifest.json" if manifest else None)


def test_entry_for_splits_cells(client: PCClient, tmp_path: Path):
    entry = _dispatch(client, tmp_path)
    assert entry["doc_id"] == "form-abc12345"
    assert entry["response_cells"] == ["checkbox.milk", "choice.size.m"]
    assert entry["trigger_cells"] == ["cmd.capture.p1"]
    assert entry["base_md5"] == hashlib.md5(b"%PDF-form").hexdigest()
    assert entry["remote"] == {"folder": "Document", "name": "form.pdf"}
    assert entry["mark_md5"] is None and entry["acknowledged_at"] is None
    assert entry["dispatched_at"]


def test_entry_for_without_manifest(client: PCClient, tmp_path: Path):
    entry = _dispatch(client, tmp_path, manifest=None)
    md5 = hashlib.md5(b"%PDF-form").hexdigest()
    assert entry["doc_id"] == f"form-{md5[:8]}"
    assert entry["manifest"] is None
    assert entry["response_cells"] == [] and entry["trigger_cells"] == []


def test_ledger_roundtrip_and_upsert(tmp_path: Path):
    path = tmp_path / "ledger.json"
    ledger = Ledger(path)
    a = {"doc_id": "a-1", "remote": {"folder": "Document", "name": "a.pdf"}}
    b = {"doc_id": "b-1", "remote": {"folder": "Document", "name": "b.pdf"}}
    ledger.upsert(a)
    ledger.upsert(b)
    ledger.save()

    reloaded = Ledger(path)
    assert [e["doc_id"] for e in reloaded.entries] == ["a-1", "b-1"]
    assert reloaded.find("a-1") == a and reloaded.find("nope") is None

    # re-dispatch under the same remote name supersedes the old expectation
    reloaded.upsert({"doc_id": "a-2",
                     "remote": {"folder": "Document", "name": "a.pdf"}})
    assert [e["doc_id"] for e in reloaded.entries] == ["b-1", "a-2"]


def test_status_lifecycle(client: PCClient, server: FakeServer, tmp_path: Path):
    entry = _dispatch(client, tmp_path)

    (r,) = check_entries([entry], client)
    assert r["state"] == "waiting" and not r["base_changed"]
    assert r["mark_md5"] is None

    # device syncs ink back: the .mark sidecar appears as its own row
    server.rows["form.pdf.mark"] = server.row(
        "form.pdf.mark", "a" * 32, 100, "id-form.pdf.mark")
    (r,) = check_entries([entry], client)
    assert r["state"] == "responded" and r["mark_md5"] == "a" * 32

    acknowledge(entry, r["mark_md5"])
    assert entry["acknowledged_at"]
    (r,) = check_entries([entry], client)
    assert r["state"] == "seen"

    # more ink lands: .mark md5 churns
    server.rows["form.pdf.mark"]["md5"] = "b" * 32
    (r,) = check_entries([entry], client)
    assert r["state"] == "changed" and r["mark_md5"] == "b" * 32

    # base md5 drift breaks the ink-pure anchor -> flagged
    server.rows["form.pdf"]["md5"] = "c" * 32
    (r,) = check_entries([entry], client)
    assert r["base_changed"]

    # base row gone entirely
    del server.rows["form.pdf"]
    (r,) = check_entries([entry], client)
    assert r["state"] == "missing"


def test_status_missing_folder_is_missing_not_error(client: PCClient):
    entry = {"doc_id": "x-1", "base_md5": "0" * 32, "mark_md5": None,
             "remote": {"folder": "Gone", "name": "x.pdf"}}
    (r,) = check_entries([entry], client)
    assert r["state"] == "missing"


def test_check_entries_one_listing_per_folder(client: PCClient, server: FakeServer,
                                              tmp_path: Path):
    entries = [_dispatch(client, tmp_path, name=f"f{i}.pdf") for i in range(3)]
    calls = {"n": 0}
    real_ls = client.ls

    def counting_ls(directory_id: int = 0):
        calls["n"] += 1
        return real_ls(directory_id)

    client.ls = counting_ls
    check_entries(entries, client)
    # resolve_dir("Document") lists the root once, then Document once
    assert calls["n"] == 2


def test_default_ledger_path_env(monkeypatch, tmp_path: Path):
    from inkbridge.dispatch import default_ledger_path

    # $INKBRIDGE_LEDGER is the explicit override and wins verbatim.
    monkeypatch.setenv("INKBRIDGE_LEDGER", str(tmp_path / "l.json"))
    assert default_ledger_path() == tmp_path / "l.json"


def test_default_ledger_path_uses_state_dir(monkeypatch, tmp_path: Path):
    # A5: no override -> a per-user state dir, honoring XDG_STATE_HOME, never
    # the cwd.
    from inkbridge.dispatch import LEDGER_NAME, default_ledger_path

    monkeypatch.delenv("INKBRIDGE_LEDGER", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert default_ledger_path() == tmp_path / "state" / "inkbridge" / LEDGER_NAME


def test_ledger_default_is_cwd_independent(monkeypatch, tmp_path: Path):
    # A5 gate: the default ledger path resolves to the SAME location from two
    # different working directories, and lives OUTSIDE the cwd unless the
    # $INKBRIDGE_LEDGER override says otherwise.
    import os

    from inkbridge.dispatch import default_ledger_path

    monkeypatch.delenv("INKBRIDGE_LEDGER", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()

    cwd = os.getcwd()
    try:
        os.chdir(dir_a)
        from_a = default_ledger_path().resolve()
        os.chdir(dir_b)
        from_b = default_ledger_path().resolve()
    finally:
        os.chdir(cwd)

    assert from_a == from_b                       # cwd-independent
    assert dir_a not in from_a.parents            # outside the cwd
    assert dir_b not in from_b.parents

    # The override still lets a caller pin an explicit (even relative) path.
    monkeypatch.setenv("INKBRIDGE_LEDGER", "pinned.json")
    assert default_ledger_path() == Path("pinned.json")


def test_atomic_write_survives_crash(monkeypatch, tmp_path: Path):
    # A3: a crash AFTER the temp file is written but BEFORE the rename must
    # leave the original ledger intact and parseable (temp-then-os.replace).
    path = tmp_path / "ledger.json"
    ledger = Ledger(path)
    ledger.upsert({"doc_id": "a-1", "remote": {"folder": "Document", "name": "a.pdf"}})
    ledger.save()
    original = path.read_bytes()

    import inkbridge.atomicio as atomicio

    def boom(src, dst):  # os.replace stand-in: temp is already written
        raise OSError("simulated crash before rename")

    monkeypatch.setattr(atomicio.os, "replace", boom)
    ledger.upsert({"doc_id": "b-2", "remote": {"folder": "Document", "name": "b.pdf"}})
    with pytest.raises(OSError):
        ledger.save()

    # Original ledger untouched and still parseable; no temp left behind.
    assert path.read_bytes() == original
    assert [e["doc_id"] for e in Ledger(path).entries] == ["a-1"]
    assert not list(tmp_path.glob(".*tmp*"))


def test_entry_without_manifest_never_pretends_cells(client: PCClient,
                                                     tmp_path: Path):
    # collect refuses manifest-less entries at the CLI layer; the ledger
    # layer must make that detectable rather than fabricating cell lists.
    entry = _dispatch(client, tmp_path, manifest=None)
    assert not entry["manifest"]
    with pytest.raises(TypeError):
        Path(entry["manifest"])  # None is not a path — the CLI checks first


def _server_from_env(monkeypatch, server: FakeServer):
    def from_env(cls, env_file=None):
        http = httpx.Client(transport=httpx.MockTransport(server.handler))
        c = PCClient("http://cloud.test", http=http)
        c.login("user@test", "pw")
        return c
    monkeypatch.setattr(PCClient, "from_env", classmethod(from_env))


def _dispatch_cli(*args):
    from inkbridge.cli import main
    return CliRunner().invoke(main, ["dispatch", *args])


def test_cli_dispatch_json_payload(server: FakeServer, monkeypatch, tmp_path: Path):
    # doc_id (and remote/cells/ledger) come back as structured dispatch.v1
    # fields, not scraped from a prose line.
    _server_from_env(monkeypatch, server)
    f = tmp_path / "form.pdf"
    f.write_bytes(b"%PDF-form")
    manifest = tmp_path / "form.manifest.json"
    manifest.write_text(json.dumps(MANIFEST))
    ledger = tmp_path / "ledger.json"
    res = _dispatch_cli(str(f), "--manifest", str(manifest),
                        "--ledger", str(ledger), "--json")
    assert res.exit_code == 0
    payload = json.loads(res.stdout)
    assert payload["schema_version"] == "dispatch.v1"
    assert payload["doc_id"] == "form-abc12345"
    assert payload["remote"] == {"folder": "Document", "name": "form.pdf"}
    assert payload["response_cells"] == 2 and payload["trigger_cells"] == 1
    assert payload["manifest"] == str(manifest)
    assert payload["ledger"] == str(ledger)


def test_cli_dispatch_json_missing_folder_is_exit_4(server: FakeServer, monkeypatch,
                                                    tmp_path: Path):
    _server_from_env(monkeypatch, server)
    f = tmp_path / "form.pdf"
    f.write_bytes(b"%PDF-form")
    res = _dispatch_cli(str(f), "--to", "Nonexistent",
                        "--ledger", str(tmp_path / "ledger.json"), "--json")
    assert res.exit_code == 4
    assert res.stdout == ""
    assert json.loads(res.stderr)["error"]["code"] == "not_found"
