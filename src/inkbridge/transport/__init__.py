"""Backends for getting files on/off a Supernote Manta.

Backends trade off between Cloud, Browse & Access, and USB. The private
Cloud dialect is implemented; the ``Transport`` protocol + neutral errors
(:mod:`inkbridge.transport.base`) are the seam a second backend
implements against.

``connect`` is the transport connector — the zero-arg callable the
``ops`` layer consumes and the CLI passes down. It is the *only* place the CLI
touches a concrete backend, so a config-driven registry (named profiles, G6)
drops in here without the commands changing.
"""

from __future__ import annotations

from inkbridge.transport.base import AuthError, DirHandle, MissingBytesError, Transport

__all__ = ["AuthError", "DirHandle", "MissingBytesError", "Transport", "connect"]


def connect(profile: str | None = None) -> Transport:
    """Return a connected transport for the selected profile (G6).

    The profile is the explicit ``profile`` argument, else the
    ``$INKBRIDGE_PROFILE`` environment default; a named profile's credentials
    come from ``~/.config/inkbridge/config.toml``. With no profile,
    the unnamed single-account ``PCClient.from_env`` path (env vars / ``.env``)
    is used unchanged — so the bare ``transport.connect`` the ops layer/CLI pass
    around keeps working, and ``from_env`` is one source among several.

    Stays effectively zero-arg for the ops connector shape and resolves
    credentials at **call time**, not import — so a monkeypatched ``from_env``
    is honored and a missing config surfaces as the ``KeyError`` ``doctor`` maps
    to PRECONDITION.
    """
    from inkbridge.transport.private_cloud import PCClient

    from inkbridge.config import active_profile_name

    name = profile or active_profile_name()
    if name:
        from inkbridge.config import get_profile

        p = get_profile(name)
        client = PCClient(p.url)
        client.login(p.email, p.password)
        return client
    return PCClient.from_env()
