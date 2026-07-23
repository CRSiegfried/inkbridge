"""Dispatch ledger: the bookkeeping between compose's manifest and
readback's decode (vision pillar 4).

A ledger entry records what was pushed, from which manifest, and that a
response is expected, so a later poll can go from a remote listing row back
to the manifest without human memory. The identity join is content-hash based:
the base row is anchored by its content ``md5`` (static across annotation —
the ink-pure signal), the response is the sibling ``<name>.mark`` row, and
that row's ``md5`` is the ink signal: 0→1 on first ink, then churn on
further strokes. ``mark_md5`` in an entry is the last *acknowledged* ink
state; ``status`` reports ``changed`` relative to it.

The ledger is instance data — which documents this operator dispatched —
so the file lives outside the public tree: a stable per-user state dir by
default (A5 — never cwd-relative, or the same command run from two directories
silently sees two different worlds), or an explicit ``$INKBRIDGE_LEDGER``.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from inkbridge.atomicio import atomic_write_text, file_lock

# Basename of the ledger inside the resolved state dir (and the historical
# cwd-relative name $INKBRIDGE_LEDGER may still point at).
LEDGER_NAME = "ledger.json"

# Cell types a human answers; capture_trigger is the page-level AI-parse box.
TRIGGER_TYPE = "capture_trigger"


def _state_dir() -> Path:
    """The per-user state directory inkbridge stores instance data under —
    stable regardless of the current working directory (A5). Honors
    ``XDG_STATE_HOME`` (the freedesktop base-dir spec), falls back to
    ``~/.local/state`` on POSIX, and to ``%LOCALAPPDATA%`` on Windows."""
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "inkbridge"
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local")
        return Path(base) / "inkbridge"
    return Path.home() / ".local" / "state" / "inkbridge"


def default_ledger_path() -> Path:
    """The ledger path when none is passed. Precedence: the explicit
    ``$INKBRIDGE_LEDGER`` override (may be relative); else the active named
    profile's per-profile ledger when ``$INKBRIDGE_PROFILE`` is set (G6), so
    credentials and ledger move together under one name; else a cwd-independent
    path in the per-user state dir. Resolved so two runs from different
    directories address the same ledger."""
    override = os.environ.get("INKBRIDGE_LEDGER")
    if override:
        return Path(override)
    from inkbridge.config import active_profile_name, get_profile

    name = active_profile_name()
    if name:
        return get_profile(name).ledger
    return _state_dir() / LEDGER_NAME


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Ledger:
    """JSON-file list of dispatch entries, keyed by remote folder/name."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else default_ledger_path()
        self.entries: list[dict] = []
        if self.path.exists():
            self.entries = json.loads(self.path.read_text())["entries"]

    def find(self, doc_id: str) -> dict | None:
        return next((e for e in self.entries if e["doc_id"] == doc_id), None)

    def upsert(self, entry: dict) -> None:
        """Add or replace the entry for the same remote folder/name — a
        re-dispatch under the same name supersedes the old expectation."""
        self.entries = [
            e for e in self.entries if e["remote"] != entry["remote"]
        ] + [entry]

    def save(self) -> None:
        """Persist the ledger crash-safely (A3): under an advisory lock, so a
        concurrent writer is serialized rather than clobbering this one, and via
        an atomic temp-then-rename, so a crash mid-write can't corrupt the file
        (a reader always sees the whole old or whole new ledger)."""
        with file_lock(self.path):
            atomic_write_text(
                self.path, json.dumps({"entries": self.entries}, indent=2) + "\n")


def entry_for(
    file: Path,
    push_info: dict,
    manifest: dict | None = None,
    manifest_path: Path | None = None,
) -> dict:
    """Build a ledger entry from a completed push and (if the file was
    composed) its manifest. Without a manifest the doc is still tracked —
    the .mark join needs only the remote name — but readback needs the
    manifest, so ``collect`` will refuse.
    """
    if manifest:
        doc_id = manifest["doc_id"]
        cells = manifest["cells"]
        response_cells = [c["id"] for c in cells if c["type"] != TRIGGER_TYPE]
        trigger_cells = [c["id"] for c in cells if c["type"] == TRIGGER_TYPE]
    else:
        from inkbridge.compose.render import _slug

        doc_id = f"{_slug(file.stem)}-{push_info['md5'][:8]}"
        response_cells, trigger_cells = [], []
    return {
        "doc_id": doc_id,
        "remote": {"folder": push_info["folder"], "name": push_info["name"]},
        "base_md5": push_info["md5"],
        "size": push_info["size"],
        "dispatched_at": _now(),
        "manifest": str(manifest_path) if manifest_path else None,
        "response_cells": response_cells,
        "trigger_cells": trigger_cells,
        "mark_md5": None,
        "acknowledged_at": None,
    }


def acknowledge(entry: dict, mark_md5: str) -> None:
    """Record a response's ink state as seen; ``status`` then reports
    ``changed`` only when new ink lands on top of it."""
    entry["mark_md5"] = mark_md5
    entry["acknowledged_at"] = _now()


def check_entries(entries: list[dict], client) -> list[dict]:
    """The G2 poll: one listing per distinct folder, then the 0011 join per
    entry. States:

    - ``waiting``   — base listed, no ``.mark`` sibling yet (no ink ever)
    - ``responded`` — ``.mark`` exists and was never acknowledged
    - ``changed``   — ``.mark`` md5 differs from the acknowledged one
    - ``seen``      — ``.mark`` md5 equals the acknowledged one
    - ``missing``   — base row (or its whole folder) is gone

    ``base_changed`` flags a base-row md5 drift — the ink-pure signal says
    annotation never touches the base, so drift means rename/replace/export
    and the join is no longer trustworthy for that entry.
    """
    cache: dict[str, dict[str, dict] | None] = {}

    def rows_for(folder: str) -> dict[str, dict] | None:
        if folder not in cache:
            try:
                cache[folder] = {
                    r["fileName"]: r for r in client.ls(client.resolve_dir(folder))}
            except FileNotFoundError:
                cache[folder] = None
        return cache[folder]

    results = []
    for entry in entries:
        folder, name = entry["remote"]["folder"], entry["remote"]["name"]
        rows = rows_for(folder)
        base = rows.get(name) if rows is not None else None
        mark = rows.get(name + ".mark") if rows is not None else None
        if base is None:
            state = "missing"
        elif mark is None:
            state = "waiting"
        elif entry["mark_md5"] is None:
            state = "responded"
        elif mark["md5"] != entry["mark_md5"]:
            state = "changed"
        else:
            state = "seen"
        results.append({
            "doc_id": entry["doc_id"],
            "remote": f"{folder}/{name}",
            "state": state,
            "mark_md5": mark["md5"] if mark else None,
            "base_changed": bool(base) and base["md5"] != entry["base_md5"],
            "entry": entry,
        })
    return results
