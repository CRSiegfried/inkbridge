"""The transport seam (ADR-0007): a backend-neutral ``Transport`` protocol and
the transport-neutral exceptions the CLI's exit taxonomy maps.

``Transport`` is the **post-connection** surface the CLI and ``ops`` actually
call — ``ls``/``resolve_dir``/``push``/``pull``/``delete``. It deliberately
omits ``login``/``from_env``: construction and credentials are the connector's
job (``transport.connect``, ADR-0006's zero-arg seam), and login shape is
backend-specific. A directory is an opaque :data:`DirHandle` that
``resolve_dir`` mints and ``ls`` consumes — the private cloud's handle happens
to be an ``int``; nothing here commits to that.

The neutral exceptions are **bases**: each backend's own error subclasses these
(``private_cloud.AuthError(PrivateCloudError, AuthError)``), so
``_cloud_errors`` catches the neutral type while every backend keeps its own
dialect-typed error and message. ``MissingBytesError`` stays a
``FileNotFoundError`` so the phantom-row path still maps to NO_CHANGE.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# Opaque, backend-defined directory token: whatever ``resolve_dir`` returns and
# ``ls`` accepts. The private cloud uses an ``int`` directory id; a folder
# backend would use a path. Callers must not inspect it.
DirHandle = Any


class AuthError(Exception):
    """Transport-neutral: credentials rejected or a token expired
    (CLI → AUTH exit). Each backend's auth failure subclasses this."""


class MissingBytesError(FileNotFoundError):
    """Transport-neutral: a listing row exists but the bytes can't be served
    (a benign "not there yet"). A ``FileNotFoundError`` so the CLI's
    phantom-row handling maps it to NO_CHANGE without inspecting strings."""


@runtime_checkable
class Transport(Protocol):
    """The post-connection surface the CLI and ``ops`` depend on. A connected
    client (built by ``transport.connect``) satisfies this structurally; the
    conformance suite (``tests/test_transport_contract.py``) pins the payload
    shapes and error semantics a bare ``Protocol`` can't express."""

    def ls(self, directory: DirHandle = ...) -> list[dict]:
        """List a directory (its root when called with no handle). Rows carry
        at least ``fileName``/``isFolder``/``size``/``md5``."""
        ...

    def resolve_dir(self, folder: str) -> DirHandle:
        """Resolve a folder path (e.g. ``"Document/Projects"``) to an opaque
        handle, or raise ``FileNotFoundError`` if a segment is missing."""
        ...

    def push(self, path: Path, folder: str = "Document", *, verify: bool = True) -> dict:
        """Upload ``path`` into ``folder``; return ``{md5,size,folder,name}``.
        Raise ``FileNotFoundError`` (folder missing) / ``FileExistsError``
        (already present, no overwrite)."""
        ...

    def pull(self, folder: str, filename: str, dest: Path) -> dict:
        """Download ``folder/filename`` to ``dest``; return
        ``{listing_md5,bytes_md5,match,size,dest}``. Raise ``FileNotFoundError``
        (no row) / ``MissingBytesError`` (row without bytes)."""
        ...

    def delete(self, folder: str, filenames: str | list[str]) -> list[str]:
        """Delete named files from ``folder``, returning the names deleted.
        Refuse atomically (raise ``FileNotFoundError``) if any name is absent."""
        ...
