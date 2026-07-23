"""Packaging hygiene (D6): the package ships a py.typed marker and advertises
its public API, so a typed consumer sees the intended surface."""

from __future__ import annotations

import importlib
from pathlib import Path


def test_py_typed_marker_present():
    import inkbridge

    marker = Path(inkbridge.__file__).parent / "py.typed"
    assert marker.is_file(), "py.typed marker missing — package ships untyped"


def test_public_api_advertised_and_importable():
    import inkbridge

    assert inkbridge.__version__
    assert inkbridge.__all__
    # Every advertised name resolves (the ops/transport surface, lazily).
    for name in inkbridge.__all__:
        assert getattr(inkbridge, name) is not None


def test_ops_and_transport_are_the_public_surface():
    import inkbridge

    # The ops functions are reachable through the advertised ops module.
    assert "ops" in inkbridge.__all__
    for fn in ("dispatch", "status", "collect", "reconcile", "wait"):
        assert callable(getattr(inkbridge.ops, fn))
    # The transport protocol is re-exported at top level.
    assert inkbridge.Transport is importlib.import_module(
        "inkbridge.transport").Transport
    assert callable(inkbridge.connect)
