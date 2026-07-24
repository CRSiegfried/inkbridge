"""Named-profile config (G6): two profiles select the right credentials and the
right per-profile ledger by name (ADR-0010)."""

from __future__ import annotations

from pathlib import Path

import pytest

from inkbridge import config

_CONFIG = """
[device.tablet-a]
url = "https://a.example.com"
email = "a@example.com"
password = "pw-a"
ledger = "{ledger_a}"

[device.tablet-b]
url = "https://b.example.com"
email = "b@example.com"
password = "pw-b"
# no ledger -> per-profile default under the state dir
"""


@pytest.fixture()
def config_file(tmp_path, monkeypatch):
    ledger_a = tmp_path / "a-ledger.json"
    path = tmp_path / "config.toml"
    path.write_text(_CONFIG.format(ledger_a=ledger_a.as_posix()))
    monkeypatch.setenv("INKBRIDGE_CONFIG", str(path))
    # Pin the state dir so tablet-b's default ledger is predictable.
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    return ledger_a


def test_named_profiles_select_device_and_ledger(config_file):
    ledger_a = config_file

    a = config.get_profile("tablet-a")
    b = config.get_profile("tablet-b")

    # Right credentials per name.
    assert (a.url, a.email, a.password) == (
        "https://a.example.com", "a@example.com", "pw-a")
    assert (b.url, b.email, b.password) == (
        "https://b.example.com", "b@example.com", "pw-b")

    # Right ledger per name: a's explicit path, b's per-profile default —
    # distinct, so the two profiles never share a ledger.
    assert a.ledger == ledger_a
    assert b.ledger.parts[-3:] == ("profiles", "tablet-b", "ledger.json")
    assert a.ledger != b.ledger

    # Unknown profile is a clear KeyError naming what's configured.
    with pytest.raises(KeyError):
        config.get_profile("tablet-z")


def test_active_profile_selected_from_env(config_file, monkeypatch):
    from inkbridge.dispatch import default_ledger_path

    # $INKBRIDGE_PROFILE selects the active profile; the ledger default follows
    # it (credentials and ledger move together under one name).
    monkeypatch.setenv("INKBRIDGE_PROFILE", "tablet-a")
    monkeypatch.delenv("INKBRIDGE_LEDGER", raising=False)
    assert default_ledger_path() == config_file  # tablet-a's ledger

    # The explicit $INKBRIDGE_LEDGER override still wins over the profile.
    monkeypatch.setenv("INKBRIDGE_LEDGER", "pinned.json")
    assert default_ledger_path() == Path("pinned.json")


def test_no_config_file_is_empty_not_error(tmp_path, monkeypatch):
    monkeypatch.setenv("INKBRIDGE_CONFIG", str(tmp_path / "absent.toml"))
    assert config.load_profiles() == {}
    assert config.active_profile_name() is None


def test_connect_uses_profile_credentials(config_file, monkeypatch):
    # transport.connect(profile=) builds a client from the profile's url/creds
    # (no env INKBRIDGE_CLOUD_* needed). We stub login to capture what it used.
    from inkbridge import transport
    from inkbridge.transport.private_cloud import PCClient

    captured = {}

    def fake_login(self, email, password):
        captured["url"] = self.api
        captured["email"] = email
        captured["password"] = password

    monkeypatch.setattr(PCClient, "login", fake_login)
    transport.connect(profile="tablet-b")
    assert captured == {"url": "https://b.example.com/api",
                        "email": "b@example.com", "password": "pw-b"}
