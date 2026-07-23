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


def connect() -> Transport:
    """Return a connected transport for the configured backend.

    Zero-arg (the ops layer's connector shape), invoked lazily by ``ops`` / the CLI
    so a precondition failure never authenticates. ``PCClient.from_env`` is
    resolved at **call time** — not captured at import — so a test that
    monkeypatches ``from_env`` is honored and credentials read lazily; a missing
    ``INKBRIDGE_CLOUD_*`` config surfaces as the ``KeyError`` ``doctor`` maps to
    PRECONDITION.

    One backend today (the private cloud); config-driven selection across named
    profiles is deferred to G6 — a single selectable value needs no registry.
    """
    from inkbridge.transport.private_cloud import PCClient

    return PCClient.from_env()
