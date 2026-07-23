"""The agent-facing contract is fully adopted (CT1 / ADR-0002).

Every command must support ``--json`` and, on success, emit exactly one JSON
document carrying a ``schema_version`` envelope on stdout — no bare list, no
hand-rolled dict, no human prose mixed in. This drives ``--json`` on all
commands against the sampler fixtures + ``fake_cloud`` and asserts the envelope
invariant, so a command that regresses off the contract fails here.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from click.testing import CliRunner
from fake_cloud import FakeServer

from inkbridge.transport.private_cloud import PCClient

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def env(server: FakeServer, monkeypatch, tmp_path):
    """A fully wired world: cloud commands hit ``fake_cloud`` (seeded with a
    real ``.mark`` blob so ``collect``/``pull`` decode genuine bytes), read-path
    commands use the tracked sampler fixtures, and there is a manifest-backed
    ledger entry to collect."""
    def connect():
        http = httpx.Client(transport=httpx.MockTransport(server.handler))
        c = PCClient("http://cloud.test", http=http)
        c.login("user@test", "pw")
        return c

    monkeypatch.setattr("inkbridge.transport.connect", connect)

    # Seed the real sampler mark directly as a blob (bypassing fake_cloud's
    # crude multipart capture, which would mangle binary bytes) so pull/collect
    # retrieve it byte-exact and read_mark decodes it for real.
    mark_bytes = (FIXTURES / "sampler_form.pdf.mark").read_bytes()
    server.rows["sampler_form.pdf.mark"] = server.row(
        "sampler_form.pdf.mark", hashlib.md5(mark_bytes).hexdigest(),
        len(mark_bytes), "id-sampler_form.pdf.mark")
    server.blobs["inner-sampler_form.pdf.mark"] = mark_bytes
    # A plain base row so status has something to join and rm has a target.
    server.rows["sampler_form.pdf"] = server.row(
        "sampler_form.pdf", "b" * 32, 10, "id-sampler_form.pdf")

    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps({"entries": [{
        "doc_id": "sampler-collect",
        "remote": {"folder": "Document", "name": "sampler_form.pdf"},
        "base_md5": "b" * 32, "size": 10, "dispatched_at": "t",
        "manifest": str(FIXTURES / "sampler_form.manifest.json"),
        "response_cells": [], "trigger_cells": [],
        "mark_md5": None, "acknowledged_at": None,
    }]}))

    src = tmp_path / "upload.pdf"
    src.write_bytes(b"%PDF-upload")
    md = tmp_path / "note.md"
    md.write_text("# Note\n\n{ack: agree}\n")
    out = tmp_path / "out"
    out.mkdir()

    return SimpleNamespace(
        tmp=tmp_path, ledger=ledger, src=src, md=md, out=out,
        sampler_pdf=FIXTURES / "sampler_form.pdf",
        sampler_mark=FIXTURES / "sampler_form.pdf.mark",
        sampler_manifest=FIXTURES / "sampler_form.manifest.json",
    )


def _argv(env, cmd: str) -> list[str]:
    out = env.out
    return {
        "doctor": ["doctor", "--json"],
        "ls": ["ls", "--json"],
        "push": ["push", str(env.src), "--to", "Document", "--json"],
        "pull": ["pull", "Document/sampler_form.pdf.mark",
                 "-o", str(out / "m.mark"), "--json"],
        "rm": ["rm", "Document/sampler_form.pdf", "-y", "--json"],
        "dispatch": ["dispatch", str(env.src), "--manifest", str(env.sampler_manifest),
                     "--ledger", str(env.tmp / "disp.json"), "--json"],
        "reconcile": ["reconcile", "Document/sampler_form.pdf",
                      "--manifest", str(env.sampler_manifest),
                      "--ledger", str(env.tmp / "recon.json"), "--json"],
        "status": ["status", "--ledger", str(env.ledger), "--json"],
        "wait": ["wait", "sampler-collect", "--ledger", str(env.ledger),
                 "--timeout", "5", "--json"],
        "collect": ["collect", "sampler-collect", "--ledger", str(env.ledger),
                    "-o", str(out), "--json"],
        "readback": ["readback", str(env.sampler_manifest), str(env.sampler_mark),
                     "--json"],
        "answers": ["answers", str(env.sampler_manifest), str(env.sampler_mark),
                    "--json"],
        "composite": ["composite", str(env.sampler_pdf), str(env.sampler_mark),
                      "-o", str(out / "c.png"), "--json"],
        "proof": ["proof", str(env.sampler_manifest), "--json"],
        "merge": ["merge", str(env.sampler_pdf), str(env.sampler_pdf),
                  "-o", str(out / "merged.pdf"), "--json"],
        "compose": ["compose", str(env.md), "-o", str(out / "c.pdf"),
                    "--manifest", str(out / "c.manifest.json"), "--json"],
    }[cmd]


# The full command surface. If a command is added, add it here — the point of
# this test is that NO command is off the contract.
ALL_COMMANDS = [
    "doctor", "ls", "push", "pull", "rm", "dispatch", "reconcile", "status",
    "wait", "collect", "readback", "answers", "composite", "proof", "merge",
    "compose",
]


def test_command_surface_is_complete(env):
    # Guard: every registered command is represented above, so a new command
    # can't silently escape the contract check below.
    from inkbridge.cli import main

    registered = set(main.commands)
    assert registered == set(ALL_COMMANDS), (
        f"command surface drift: {registered ^ set(ALL_COMMANDS)}")


@pytest.mark.parametrize("cmd", ALL_COMMANDS)
def test_every_command_json_has_schema_version(env, cmd):
    from inkbridge.cli import main

    res = CliRunner().invoke(main, _argv(env, cmd))
    assert res.exit_code == 0, (
        f"{cmd} exited {res.exit_code}; stderr={res.stderr!r} exc={res.exception!r}")
    # stdout is exactly one JSON object (nothing human leaked alongside it)...
    doc = json.loads(res.stdout)
    assert isinstance(doc, dict), f"{cmd} stdout is not a JSON object"
    # ...carrying a non-empty schema_version envelope.
    version = doc.get("schema_version")
    assert isinstance(version, str) and version, (
        f"{cmd} result has no schema_version: {doc}")
