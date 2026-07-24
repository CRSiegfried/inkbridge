"""inkbridge: an agent-facing I/O control plane for the Supernote Manta.

Public API (D6). The in-process operations layer (:mod:`inkbridge.ops`)
and the transport seam (:mod:`inkbridge.transport`) are the
intended entry points for an embedder (e.g. the future MCP server) —
``inkbridge.ops.dispatch(...)`` etc. and the ``Transport`` protocol / ``connect``
factory. They are exposed lazily (PEP 562) so ``import inkbridge`` stays cheap:
the heavy render/decode dependencies load only when the surface is touched.

The bare ops function names are intentionally *not* re-exported at top level —
``dispatch`` collides with the ``inkbridge.dispatch`` submodule — so reach them
through ``inkbridge.ops``.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = [
    "Transport",   # the transport protocol
    "__version__",
    "connect",     # the zero-arg transport connector
    "ops",         # in-process operations layer (ops.dispatch/status/collect/...)
    "transport",   # transport seam (backends + connect factory)
]


def __getattr__(name: str):
    # PEP 562: resolve the public surface on first access, so the package's
    # __all__ advertises a real API without eagerly importing reportlab/numpy.
    if name in ("ops", "transport"):
        import importlib

        return importlib.import_module(f"inkbridge.{name}")
    if name in ("Transport", "connect"):
        from inkbridge import transport

        return getattr(transport, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
