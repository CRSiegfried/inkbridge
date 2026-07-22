"""`doctor` — the ADR-0002 doctor-class readiness probe: config present,
cloud reachable, credentials accepted. Contract exits 0 / 5 auth /
6 precondition.

Also covers the shared cloud-error mapping (`_cloud_errors`) that gives every
cloud command AUTH(5)/PRECONDITION(6) instead of an uncaught traceback —
exercised here through `ls` as a representative Tier-B command.
"""

from __future__ import annotations

import json

import httpx
from click.testing import CliRunner
from fake_cloud import FakeServer

from inkbridge.transport.private_cloud import AuthError, PCClient


def _invoke(cmd, *args):
    from inkbridge.cli import main
    return CliRunner().invoke(main, [cmd, *args])


def _stub_from_env(monkeypatch, fn):
    monkeypatch.setattr(PCClient, "from_env", classmethod(fn))


def _live_client(server: FakeServer):
    http = httpx.Client(transport=httpx.MockTransport(server.handler))
    c = PCClient("http://cloud.test", http=http)
    c.login("user@test", "pw")
    return c


def test_doctor_ok_json(server: FakeServer, monkeypatch):
    _stub_from_env(monkeypatch, lambda cls, env_file=None: _live_client(server))
    res = _invoke("doctor", "--json")
    assert res.exit_code == 0
    payload = json.loads(res.stdout)
    assert payload["schema_version"] == "doctor.v1"
    assert payload["ok"] is True
    assert [c["name"] for c in payload["checks"]] == ["authentication", "connectivity"]


def test_doctor_ok_human_mode(server: FakeServer, monkeypatch):
    _stub_from_env(monkeypatch, lambda cls, env_file=None: _live_client(server))
    res = _invoke("doctor")
    assert res.exit_code == 0
    assert "OK" in res.stdout
    assert not res.stdout.lstrip().startswith("{")


def test_doctor_missing_config_is_exit_6(monkeypatch):
    def _raise(cls, env_file=None):
        raise KeyError("INKBRIDGE_CLOUD_URL not set in environment or .env")
    _stub_from_env(monkeypatch, _raise)
    res = _invoke("doctor", "--json")
    assert res.exit_code == 6
    assert json.loads(res.stderr)["error"]["code"] == "config_missing"


def test_doctor_bad_credentials_is_exit_5(monkeypatch):
    def _raise(cls, env_file=None):
        raise AuthError("/official/user/account/login/new", "E0000", "bad password")
    _stub_from_env(monkeypatch, _raise)
    res = _invoke("doctor", "--json")
    assert res.exit_code == 5
    assert json.loads(res.stderr)["error"]["code"] == "auth"


def test_doctor_unreachable_is_exit_6(monkeypatch):
    def _raise(cls, env_file=None):
        raise httpx.ConnectError("connection refused")
    _stub_from_env(monkeypatch, _raise)
    res = _invoke("doctor", "--json")
    assert res.exit_code == 6
    assert json.loads(res.stderr)["error"]["code"] == "unreachable"


def test_cloud_command_maps_auth_to_exit_5(monkeypatch):
    # The shared _cloud_errors wrapper: a Tier-B command (ls) that previously
    # let auth failures escape as exit 1 + traceback now exits 5.
    def _raise(cls, env_file=None):
        raise AuthError("/official/user/account/login/new", "E0000", "bad password")
    _stub_from_env(monkeypatch, _raise)
    res = _invoke("ls")
    assert res.exit_code == 5
    assert "authentication failed" in res.stderr


def test_cloud_command_maps_unreachable_to_exit_6(monkeypatch):
    def _raise(cls, env_file=None):
        raise httpx.ConnectError("connection refused")
    _stub_from_env(monkeypatch, _raise)
    res = _invoke("ls")
    assert res.exit_code == 6
    assert "unreachable" in res.stderr
