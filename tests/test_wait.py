"""`wait` — the bounded long-poll that synchronizes dispatch → collect (D1).

Exits 0 once a mark is delivered, exits 3 (typed timeout) when none arrives in
the window. The backoff loop is driven with an injected clock/sleep so the
timeout path is deterministic and instant.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner
from fake_cloud import FakeServer

from inkbridge import ops
from inkbridge.dispatch import Ledger


def _entry():
    return {
        "doc_id": "form-abc12345",
        "remote": {"folder": "Document", "name": "form.pdf"},
        "base_md5": "b" * 32, "size": 10, "dispatched_at": "t",
        "manifest": None, "response_cells": [], "trigger_cells": [],
        "mark_md5": None, "acknowledged_at": None,
    }


@pytest.fixture()
def ledger(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"entries": [_entry()]}))
    return Ledger(path)


def _deliver_mark(server: FakeServer):
    server.rows["form.pdf"] = server.row("form.pdf", "b" * 32, 10, "id-form.pdf")
    server.rows["form.pdf.mark"] = server.row(
        "form.pdf.mark", "a" * 32, 100, "id-form.pdf.mark")


def test_wait_returns_0_on_mark_and_returns_3_on_timeout(
        client, server: FakeServer, ledger, tmp_path):
    # The D1 gate, both halves against fake_cloud with an injected clock:
    #
    # (a) returns_0_on_mark — the mark is on the server, so the first poll sees
    #     it and wait returns the arrival row (→ CLI exit 0) without sleeping.
    _deliver_mark(server)
    slept: list = []
    row = ops.wait(lambda: client, ledger, "form-abc12345", timeout=60,
                   sleep=slept.append, monotonic=lambda: 0.0)
    assert row["state"] == "responded" and row["mark_md5"] == "a" * 32
    assert slept == []  # arrived immediately, no backoff

    # (b) returns_3_on_timeout — a fresh doc with no mark; the injected clock
    #     jumps past the deadline after a couple of polls, so wait raises the
    #     typed WaitTimeout (→ CLI exit 3) with no real waiting.
    server.rows.clear()
    lp = tmp_path / "empty-ledger.json"
    lp.write_text(json.dumps({"entries": [_entry()]}))
    ticks = iter([0.0, 1.0, 2.0, 5.0, 100.0])
    slept = []
    with pytest.raises(ops.WaitTimeout):
        ops.wait(lambda: client, Ledger(lp), "form-abc12345", timeout=10,
                 sleep=slept.append, monotonic=lambda: next(ticks))
    assert slept  # it did back off between polls before giving up


def test_wait_unknown_doc_raises(client, ledger):
    with pytest.raises(ops.UnknownDocError):
        ops.wait(lambda: client, ledger, "no-such-doc", timeout=1)


# -- CLI exit codes (the observable contract) -----------------------------

def _run(server, ledger_path, *args, monkeypatch):
    def connect():
        import httpx

        from inkbridge.transport.private_cloud import PCClient
        http = httpx.Client(transport=httpx.MockTransport(server.handler))
        c = PCClient("http://cloud.test", http=http)
        c.login("user@test", "pw")
        return c

    monkeypatch.setattr("inkbridge.transport.connect", connect)
    from inkbridge.cli import main
    return CliRunner().invoke(
        main, ["wait", "form-abc12345", "--ledger", str(ledger_path), *args])


def test_cli_wait_exit_0_when_mark_present(server, ledger, monkeypatch):
    _deliver_mark(server)
    res = _run(server, ledger.path, "--json", monkeypatch=monkeypatch)
    assert res.exit_code == 0
    payload = json.loads(res.stdout)
    assert payload["schema_version"] == "wait.v1"
    assert payload["state"] == "responded"


def test_cli_wait_exit_3_on_timeout(server, ledger, monkeypatch):
    # timeout=0 → the deadline is already past after the first mark-less poll,
    # so the CLI returns exit 3 promptly with a typed timeout error.
    res = _run(server, ledger.path, "--timeout", "0", "--json",
               monkeypatch=monkeypatch)
    assert res.exit_code == 3
    assert res.stdout == ""
    assert json.loads(res.stderr)["error"]["code"] == "timeout"
