"""Named-profile configuration (G6): several devices/accounts, each with its own
credentials and its own ledger, selected by name.

The config file is ``~/.config/inkbridge/config.toml`` (honoring
``XDG_CONFIG_HOME``, overridable with ``$INKBRIDGE_CONFIG``), one section per
profile::

    [device.tablet-a]
    url = "https://sn.example.com"
    email = "a@example.com"
    password = "..."
    ledger = "..."        # optional; per-profile default otherwise

A profile is selected by name — the explicit argument to
``transport.connect`` / this module's helpers, else the ``$INKBRIDGE_PROFILE``
environment default. With no profile the single-account ``PCClient.from_env``
path (env vars / ``.env``) is used unchanged, so ``from_env`` is one source
among several.
"""

from __future__ import annotations

import os
import tomllib as _toml  # stdlib on 3.11+ (project floor)
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Profile:
    """One named device/account: its cloud credentials and its ledger."""

    name: str
    url: str
    email: str
    password: str
    ledger: Path


def config_path() -> Path:
    """The config file location: ``$INKBRIDGE_CONFIG`` if set, else
    ``$XDG_CONFIG_HOME/inkbridge/config.toml`` (``~/.config`` default)."""
    override = os.environ.get("INKBRIDGE_CONFIG")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "inkbridge" / "config.toml"


def _profile_ledger_default(name: str) -> Path:
    """Per-profile ledger under the state dir, so two profiles never share a
    ledger by accident (A5's state dir, one subdir per profile)."""
    from inkbridge.dispatch import _state_dir

    return _state_dir() / "profiles" / name / "ledger.json"


def load_profiles(path: Path | None = None) -> dict[str, Profile]:
    """Parse every ``[device.<name>]`` section into a :class:`Profile`. Returns
    an empty mapping when the config file is absent."""
    path = Path(path) if path else config_path()
    if not path.exists():
        return {}
    data = _toml.loads(path.read_text())
    profiles: dict[str, Profile] = {}
    for name, sec in (data.get("device") or {}).items():
        ledger = sec.get("ledger")
        profiles[name] = Profile(
            name=name,
            url=sec["url"],
            email=sec["email"],
            password=sec["password"],
            ledger=Path(ledger) if ledger else _profile_ledger_default(name),
        )
    return profiles


def get_profile(name: str, path: Path | None = None) -> Profile:
    """Resolve one profile by name, or raise ``KeyError`` naming what is
    configured."""
    profiles = load_profiles(path)
    if name not in profiles:
        raise KeyError(
            f"no profile {name!r} in {path or config_path()}; "
            f"configured: {', '.join(sorted(profiles)) or '(none)'}")
    return profiles[name]


def active_profile_name() -> str | None:
    """The profile selected by the environment (``$INKBRIDGE_PROFILE``), or
    ``None`` for the unnamed single-account default."""
    return os.environ.get("INKBRIDGE_PROFILE") or None
