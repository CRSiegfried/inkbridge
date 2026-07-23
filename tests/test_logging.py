"""Opt-in logging (`inkbridge.obs`) must never disturb the ADR-0002 contract.

The load-bearing invariants:

- Default invocation (no ``-v``, no ``--log-file``) is byte-for-byte identical
  to before logging existed: the ``--json`` stdout document is unchanged and
  stderr stays a clean ``error.v1`` envelope (nothing else).
- ``-v`` adds per-invocation lines to *stderr* only; stdout is still identical.
- ``--log-file`` / ``INKBRIDGE_LOG`` captures the same activity to a *file*,
  leaving both stdout and stderr untouched — the safe mode for a subprocess
  consumer that parses the stderr envelope.
"""

from __future__ import annotations

import hashlib
import json
import re

import httpx
from click.testing import CliRunner
from fake_cloud import FakeServer

from inkbridge.transport.private_cloud import AuthError, PCClient


def _invoke(*args):
    from inkbridge.cli import main

    return CliRunner().invoke(main, list(args))


def _stub_from_env(monkeypatch, fn):
    monkeypatch.setattr(PCClient, "from_env", classmethod(fn))


def _live_client(server: FakeServer):
    http = httpx.Client(transport=httpx.MockTransport(server.handler))
    c = PCClient("http://cloud.test", http=http)
    c.login("user@test", "pw")
    return c


# ---------------------------------------------------------------------------
# stdout is byte-for-byte unchanged, stderr silent, by default
# ---------------------------------------------------------------------------

def test_default_invocation_is_silent_and_json_unchanged(server: FakeServer, monkeypatch):
    _stub_from_env(monkeypatch, lambda cls, env_file=None: _live_client(server))

    quiet = _invoke("doctor", "--json")
    verbose = _invoke("-v", "doctor", "--json")

    assert quiet.exit_code == 0
    # Default mode emits nothing to stderr (no log leakage).
    assert quiet.stderr == ""
    # --verbose changes stderr but NOT the stdout JSON document (byte-for-byte).
    assert verbose.stdout == quiet.stdout
    assert json.loads(quiet.stdout)["schema_version"] == "doctor.v1"


def test_verbose_logs_invocation_to_stderr(server: FakeServer, monkeypatch):
    _stub_from_env(monkeypatch, lambda cls, env_file=None: _live_client(server))

    res = _invoke("-v", "doctor", "--json")

    assert res.exit_code == 0
    assert "invoke: inkbridge doctor" in res.stderr


def test_error_envelope_stays_clean_without_verbose(monkeypatch):
    # A machine consumer parses the stderr envelope; without -v it must be
    # EXACTLY the error.v1 JSON, with no log lines interleaved.
    def _raise(cls, env_file=None):
        raise KeyError("INKBRIDGE_CLOUD_URL not set in environment or .env")

    _stub_from_env(monkeypatch, _raise)
    res = _invoke("doctor", "--json")

    assert res.exit_code == 6
    envelope = json.loads(res.stderr)  # parses cleanly → nothing else on stderr
    assert envelope["error"]["code"] == "config_missing"


def test_verbose_logs_exit_reason(monkeypatch):
    def _raise(cls, env_file=None):
        raise AuthError("/official/user/account/login/new", "E0000", "bad password")

    _stub_from_env(monkeypatch, _raise)
    res = _invoke("-v", "doctor", "--json")

    assert res.exit_code == 5
    # The CliError exit reason surfaces in the opt-in log.
    assert "exit 5 auth" in res.stderr


# ---------------------------------------------------------------------------
# --log-file / INKBRIDGE_LOG: capture to a file, leave stdout+stderr untouched
# ---------------------------------------------------------------------------

def test_log_file_captures_without_touching_stdout_or_stderr(
    server: FakeServer, monkeypatch, tmp_path
):
    _stub_from_env(monkeypatch, lambda cls, env_file=None: _live_client(server))
    log_path = tmp_path / "inkbridge.log"

    baseline = _invoke("doctor", "--json")
    logged = _invoke("--log-file", str(log_path), "doctor", "--json")

    assert logged.exit_code == 0
    # File logging is invisible on both streams — the subprocess-safe mode.
    assert logged.stdout == baseline.stdout
    assert logged.stderr == ""
    contents = log_path.read_text()
    assert "invoke: inkbridge" in contents
    assert "logged in to http://cloud.test/api" in contents


def test_inkbridge_log_env_var_is_honored(server: FakeServer, monkeypatch, tmp_path):
    _stub_from_env(monkeypatch, lambda cls, env_file=None: _live_client(server))
    log_path = tmp_path / "env.log"
    monkeypatch.setenv("INKBRIDGE_LOG", str(log_path))

    res = _invoke("doctor", "--json")

    assert res.exit_code == 0
    assert res.stderr == ""
    assert "invoke: inkbridge" in log_path.read_text()


# ---------------------------------------------------------------------------
# D5: every transport verb emits a timed request line at -v (INFO), not only -vv
# ---------------------------------------------------------------------------

_TIMED_REQUEST = re.compile(r"\b(GET|POST|PUT)\b.*ms")


def _seed_markable(server: FakeServer):
    """A base row + a real-bytes .mark blob so pull/collect download for real."""
    data = b"markbytes"
    server.rows["form.pdf"] = server.row("form.pdf", "b" * 32, 10, "id-form.pdf")
    server.rows["form.pdf.mark"] = server.row(
        "form.pdf.mark", hashlib.md5(data).hexdigest(), len(data), "id-form.pdf.mark")
    server.blobs["inner-form.pdf.mark"] = data


def test_verbose_logs_timed_upload_request(server: FakeServer, monkeypatch, tmp_path):
    # dispatch uploads: at -v, stderr carries a timed upload line (POST/PUT ... ms)
    # and the ls-verify line, while stdout stays valid contract JSON.
    _stub_from_env(monkeypatch, lambda cls, env_file=None: _live_client(server))
    f = tmp_path / "form.pdf"
    f.write_bytes(b"%PDF-form")

    res = _invoke("-v", "dispatch", str(f), "--ledger", str(tmp_path / "l.json"), "--json")
    assert res.exit_code == 0
    json.loads(res.stdout)  # stdout is pure contract JSON
    assert _TIMED_REQUEST.search(res.stderr), res.stderr
    assert "PUT /oss/upload" in res.stderr           # the byte upload, timed
    assert "/file/list/query" in res.stderr          # the ls verify, timed


def test_verbose_logs_timed_download_request(server: FakeServer, monkeypatch, tmp_path):
    # collect downloads: at -v, stderr carries a timed download line (GET ... ms).
    _seed_markable(server)
    _stub_from_env(monkeypatch, lambda cls, env_file=None: _live_client(server))
    manifest = tmp_path / "form.manifest.json"
    manifest.write_text(json.dumps({"doc_id": "form-1", "cells": []}))
    ledger = tmp_path / "l.json"
    ledger.write_text(json.dumps({"entries": [{
        "doc_id": "form-1", "remote": {"folder": "Document", "name": "form.pdf"},
        "manifest": str(manifest), "mark_md5": None, "acknowledged_at": None,
    }]}))

    res = _invoke("-v", "collect", "form-1", "--ledger", str(ledger),
                  "-o", str(tmp_path / "out"), "--json")
    assert res.exit_code == 0
    json.loads(res.stdout)
    assert "GET blob" in res.stderr and _TIMED_REQUEST.search(res.stderr), res.stderr


def test_default_invocation_emits_no_request_lines(server: FakeServer, monkeypatch, tmp_path):
    # Without -v, the per-request timing lines must NOT leak (stderr silent).
    _stub_from_env(monkeypatch, lambda cls, env_file=None: _live_client(server))
    f = tmp_path / "form.pdf"
    f.write_bytes(b"%PDF-form")

    res = _invoke("dispatch", str(f), "--ledger", str(tmp_path / "l.json"), "--json")
    assert res.exit_code == 0
    assert res.stderr == ""
    assert not _TIMED_REQUEST.search(res.stderr)
