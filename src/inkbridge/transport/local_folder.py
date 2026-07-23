"""A local-folder transport backend (D3): a watched directory tree standing in
for the cloud, implementing the same :class:`~inkbridge.transport.base.Transport`
protocol. It needs no network — the cheapest proof the transport seam
is real, and a de-risking of the single-backend assumption.

The root directory is the "cloud"; its immediate subdirectories are "folders"
(``Document``, ``Document/Projects``). Semantics mirror the private cloud's
where they are load-bearing: a missing folder is a ``FileNotFoundError``, a
same-name push is refused with ``FileExistsError`` (no overwrite, so
``dispatch --replace`` behaves identically), and ``delete`` refuses atomically
if any name is absent. Listing rows carry the same ``fileName``/``isFolder``/
``size``/``md5`` shape the CLI renders and ``check_entries`` joins on.
"""

from __future__ import annotations

import hashlib
import shutil
import time
from pathlib import Path

from inkbridge.obs import get_logger
from inkbridge.transport.base import DirHandle

_log = get_logger("local")


def _md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


class LocalFolder:
    """Filesystem-backed :class:`Transport`. ``root`` is the store root; folders
    are subdirectories of it."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def _row(self, entry: Path) -> dict:
        if entry.is_dir():
            return {"fileName": entry.name, "isFolder": "Y", "md5": "", "size": 0}
        data = entry.read_bytes()
        return {"fileName": entry.name, "isFolder": "N",
                "md5": _md5(data), "size": len(data)}

    def resolve_dir(self, folder: str) -> DirHandle:
        """Resolve a folder path to its directory (the opaque handle ``ls``
        consumes); the root when empty. Raise ``FileNotFoundError`` if a segment
        is missing."""
        d = self.root
        for seg in folder.strip("/").split("/") if folder.strip("/") else []:
            d = d / seg
        if not d.is_dir():
            raise FileNotFoundError(f"no such folder: {folder!r}")
        return d

    def ls(self, directory: DirHandle = None) -> list[dict]:
        d = Path(directory) if directory is not None else self.root
        start = time.monotonic()
        rows = [self._row(e) for e in sorted(d.iterdir())]
        _log.info("LS %s -> %d entries (%.0fms)", d,
                  len(rows), (time.monotonic() - start) * 1000)
        return rows

    def push(self, path: Path, folder: str = "Document", *, verify: bool = True) -> dict:
        """Copy ``path`` into ``folder``. Raise ``FileNotFoundError`` (folder
        missing) / ``FileExistsError`` (name already present — no overwrite)."""
        path = Path(path)
        dest_dir = self.resolve_dir(folder)
        dest = dest_dir / path.name
        if dest.exists():
            raise FileExistsError(
                f"{folder}/{path.name} already exists (no overwrite; use "
                "dispatch --replace or delete it first)")
        blob = path.read_bytes()
        start = time.monotonic()
        shutil.copyfile(path, dest)
        _log.info("PUT %s/%s (%d bytes, %.0fms)", folder, path.name,
                  len(blob), (time.monotonic() - start) * 1000)
        return {"md5": _md5(blob), "size": len(blob), "folder": folder, "name": path.name}

    def pull(self, folder: str, filename: str, dest: Path) -> dict:
        """Copy ``folder/filename`` to ``dest``. Raise ``FileNotFoundError`` if
        absent. Local bytes are authoritative, so the listing and byte md5s
        always match."""
        src = self.resolve_dir(folder) / filename
        if not src.is_file():
            raise FileNotFoundError(f"{folder}/{filename} not in {self.root}")
        blob = src.read_bytes()
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        start = time.monotonic()
        dest.write_bytes(blob)
        md5 = _md5(blob)
        _log.info("GET %s/%s (%d bytes, %.0fms)", folder, filename,
                  len(blob), (time.monotonic() - start) * 1000)
        return {"listing_md5": md5, "bytes_md5": md5, "match": True,
                "size": len(blob), "dest": str(dest)}

    def delete(self, folder: str, filenames: str | list[str]) -> list[str]:
        """Delete named files from ``folder``. Refuse atomically (raise
        ``FileNotFoundError`` before removing anything) if any name is absent."""
        if isinstance(filenames, str):
            filenames = [filenames]
        d = self.resolve_dir(folder)
        missing = [n for n in filenames if not (d / n).is_file()]
        if missing:
            raise FileNotFoundError(
                f"not in {folder}: {', '.join(missing)}")
        for n in filenames:
            (d / n).unlink()
        _log.info("DELETE %s/[%s]", folder, ", ".join(filenames))
        return list(filenames)
