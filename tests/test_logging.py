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

import json

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
