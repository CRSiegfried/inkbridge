"""Supernote Cloud transport backend, built on `sncloud`.

Phase 1/2 work on the roadmap. Not yet implemented against a real
account.
"""

from __future__ import annotations

from pathlib import Path


def push(local_path: Path, remote_folder: str) -> str:
    """Upload a file to Supernote Cloud. Returns the remote path."""
    raise NotImplementedError("Phase 2: wire up sncloud's put()")


def pull(remote_path: str, local_path: Path) -> Path:
    """Download a file from Supernote Cloud to local_path."""
    raise NotImplementedError("Phase 1: wire up sncloud's get()")


def list_remote(remote_folder: str = "/") -> list[str]:
    """List files/folders under remote_folder on Supernote Cloud."""
    raise NotImplementedError("Phase 1: wire up sncloud's ls()")
