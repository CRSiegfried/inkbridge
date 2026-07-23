"""`rm` never hangs an agent on a stdin prompt (CT2).

Under --json or a non-TTY stdin, a missing -y is a typed confirmation_required
exit (6), not a blocked prompt; -y deletes non-interactively. The interactive
(TTY, human) path still confirms.
"""

from __future__ import annotations

import json

import httpx
import pytest
from click.testing import CliRunner
from fake_cloud import FakeServer

from inkbridge.transport.private_cloud import PCClient


@pytest.fixture()
def cloud(server: FakeServer, monkeypatch):
    def connect():
        http = httpx.Client(transport=httpx.MockTransport(server.handler))
        c = PCClient("http://cloud.test", http=http)
        c.login("user@test", "pw")
        return c

    monkeypatch.setattr("inkbridge.transport.connect", connect)
    return server


def _seed(server: FakeServer, name="doc.pdf"):
    server.rows[name] = server.row(name, "a" * 32, 10, f"id-{name}")


def _run(*args, stdin=""):
    from inkbridge.cli import main
    return CliRunner().invoke(main, ["rm", *args], input=stdin)


def test_rm_json_without_yes_is_confirmation_required_not_hang(cloud):
    res = _run("Document/doc.pdf", "--json", stdin="")  # empty, non-TTY stdin
    assert res.exit_code == 6
    assert res.stdout == ""
    err = json.loads(res.stderr)
    assert err["error"]["code"] == "confirmation_required"
    assert "Traceback" not in res.stderr


def test_rm_non_tty_without_yes_is_typed_error(cloud):
    # Even in human mode, a non-TTY stdin must never prompt/hang.
    res = _run("Document/doc.pdf", stdin="")
    assert res.exit_code == 6
    assert res.stderr.startswith("error: refusing to delete")


def test_rm_yes_deletes_non_interactively_json(cloud):
    _seed(cloud, "doc.pdf")
    res = _run("Document/doc.pdf", "--yes", "--json", stdin="")
    assert res.exit_code == 0
    payload = json.loads(res.stdout)
    assert payload["schema_version"] == "rm.v1"
    assert payload["deleted"] == ["Document/doc.pdf"]
    assert "doc.pdf" not in cloud.rows


def test_rm_yes_deletes_non_interactively_human(cloud):
    _seed(cloud, "doc.pdf")
    res = _run("Document/doc.pdf", "-y", stdin="")
    assert res.exit_code == 0
    assert "Deleted Document/doc.pdf" in res.stdout
    assert "doc.pdf" not in cloud.rows


def test_rm_missing_file_is_typed_not_found(cloud):
    res = _run("Document/nope.pdf", "--yes", "--json", stdin="")
    assert res.exit_code == 4
    assert json.loads(res.stderr)["error"]["code"] == "not_found"
