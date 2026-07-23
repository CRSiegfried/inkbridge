"""Crash-safe, serialized state writes (A3).

Both on-disk state files — the dispatch :class:`~inkbridge.dispatch.Ledger` and
the readback :class:`~inkbridge.readback.InkHashStore` — are read-modify-write
JSON. A bare ``write_text`` truncates in place: a crash mid-write leaves a
half-written (unparseable) file, and two processes (two agents — the stated
goal) racing the write interleave or clobber.

Two primitives fix that:

- :func:`atomic_write_text` writes to a temp file in the *same directory* then
  ``os.replace``\\s it over the target. ``os.replace`` is atomic on POSIX and
  Windows, so a reader sees either the whole old file or the whole new one,
  never a torn mix, and a crash before the rename leaves the original intact.
- :func:`file_lock` takes an exclusive advisory lock (``fcntl`` on POSIX,
  ``msvcrt`` on Windows) on a sidecar ``.lock`` file. Held across the whole
  read-modify-write, it serializes concurrent writers so a load→modify→save
  cycle can't be clobbered by another process mid-cycle. Best-effort: if the
  platform lock primitive is unavailable it degrades to a no-op (the atomic
  replace still prevents torn files).
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path


def atomic_write_text(path: Path, data: str, *, encoding: str = "utf-8") -> None:
    """Write ``data`` to ``path`` atomically: a temp file in the same directory,
    flushed and ``fsync``\\ed, then ``os.replace``\\d over ``path``. The parent
    is created if missing; the temp file is cleaned up on any failure before
    the rename, so the original ``path`` is never left truncated."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Same-directory temp so os.replace is a same-filesystem (atomic) rename.
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with open(tmp, "w", encoding=encoding) as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        # Leave path untouched; drop the partial temp (KeyboardInterrupt too).
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


@contextmanager
def file_lock(path: Path):
    """Hold an exclusive advisory lock for the duration of the ``with`` block,
    keyed on ``<path>.lock`` (a sidecar so the lock outlives an atomic replace
    of ``path`` itself). Serializes concurrent read-modify-write cycles across
    processes. Best-effort: a no-op where no platform lock primitive exists."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f"{path.name}.lock")
    lock_file = open(lock_path, "w")
    try:
        _acquire(lock_file)
        yield
    finally:
        _release(lock_file)
        lock_file.close()


def _acquire(lock_file) -> None:
    try:
        import fcntl

        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        return
    except (ImportError, OSError):
        pass
    try:
        import msvcrt

        msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
    except (ImportError, OSError):
        pass  # best-effort: no advisory lock on this platform


def _release(lock_file) -> None:
    try:
        import fcntl

        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        return
    except (ImportError, OSError):
        pass
    try:
        import msvcrt

        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
    except (ImportError, OSError):
        pass
