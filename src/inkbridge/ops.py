"""In-process operations layer (ADR-0006): the orchestration that composes
the primitives (`dispatch`, `answers`, `readback`, the transport client) for
the three verbs an agent drives — dispatch, status, collect — reachable
WITHOUT Click.

Each function RETURNS the bare payload dict the CLI wraps today (the
``dispatch.v1`` / ``collect.v1`` bodies, the status-row list); there is no
``echo``, ``emit_result``, ``schema_version`` envelope, or exit code here —
presentation stays in the front-end (the CLI now, the MCP server later). This
is the single seam that lets an in-process caller get typed payloads and typed
errors instead of shelling out to the CLI and re-parsing ``--json``.

Dependencies are injected, not constructed. ``connect`` is the CLI's transport
connector — a zero-arg callable returning a *connected* client (the CLI passes
``PCClient.from_env``); ``ops`` invokes it **lazily**, only once the operation
actually needs the cloud, so a precondition failure (unknown doc, no manifest)
never authenticates. The ``ledger`` is passed in too; ``ops`` owns the domain
writes over it (the ledger ``upsert``/``save`` and collect's ``answers.json``
sidecar under the caller's ``output_dir``).

Failures are TYPED domain exceptions, never ``CliError`` (that would drag Click
and the exit-code taxonomy into the domain layer). The front-end maps them:
``UnknownDocError`` → NOT_FOUND(4), ``NoManifestError`` → PRECONDITION(6),
``NoResponseError`` → NO_CHANGE(3); the existing ``SparseMarkError`` (from
``readback``) and the stdlib ``FileNotFoundError`` / ``FileExistsError`` the
push/pull paths already raise propagate unchanged for the CLI to map too.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from inkbridge import readback as _readback
from inkbridge.answers import ANSWERS_SCHEMA, answers_payload, resolve_answers
from inkbridge.dispatch import acknowledge as _acknowledge
from inkbridge.dispatch import check_entries, entry_for


class UnknownDocError(Exception):
    """No ledger entry exists for the requested doc_id (CLI → NOT_FOUND)."""


class NoManifestError(Exception):
    """The dispatched doc carries no manifest, so its ink can't be resolved
    to answers (CLI → PRECONDITION)."""


class NoResponseError(Exception):
    """No ``.mark`` response has synced back for the doc yet (CLI → NO_CHANGE)."""


class AlreadyTrackedError(Exception):
    """The remote file reconcile was asked to adopt is already in the ledger —
    it is not an orphan (CLI → NO_CHANGE)."""


class WaitTimeout(Exception):
    """``wait`` polled to its deadline without a mark arriving (CLI → NO_CHANGE)."""


def dispatch(connect, ledger, file, *, remote_folder, manifest_path, replace=False):
    """Push ``file`` and record it in ``ledger`` as awaiting a response.

    Returns the ``dispatch.v1`` body. ``connect().push`` may raise
    ``FileNotFoundError`` (remote folder missing) or ``FileExistsError`` (the
    private cloud has no overwrite) — both propagate for the CLI to map.

    ``replace`` makes dispatch idempotent (A4): the remote name is deleted first
    (delete-then-push), so re-dispatching an already-present doc succeeds and
    leaves exactly one remote copy instead of dying on the no-overwrite
    ``FileExistsError``. A missing remote name is not an error under ``replace``
    — the delete is best-effort and the push then surfaces any folder problem.
    """
    manifest = json.loads(Path(manifest_path).read_text()) if manifest_path else None
    client = connect()
    if replace:
        try:
            client.delete(remote_folder, Path(file).name)
        except FileNotFoundError:
            pass  # nothing to replace (first dispatch, or folder push will flag)
    info = client.push(file, remote_folder)
    entry = entry_for(file, info, manifest, manifest_path)
    ledger.upsert(entry)
    ledger.save()
    return {
        "doc_id": entry["doc_id"],
        "remote": entry["remote"],
        "manifest": entry["manifest"],
        "response_cells": len(entry["response_cells"]),
        "trigger_cells": len(entry["trigger_cells"]),
        "ledger": str(ledger.path),
    }


def reconcile(connect, ledger, folder, name, *, manifest_path):
    """Adopt an orphaned remote file — one present on the cloud with no ledger
    entry (e.g. a dispatch that pushed then crashed before saving the ledger, or
    a file pushed out of band) — into ``ledger`` so ``status``/``collect`` can
    track it. Returns the ``reconcile.v1`` body.

    Raises ``AlreadyTrackedError`` when the remote is already in the ledger (not
    an orphan), or ``FileNotFoundError`` when no such remote file exists.
    """
    remote = {"folder": folder, "name": name}
    if any(e["remote"] == remote for e in ledger.entries):
        raise AlreadyTrackedError(
            f"{folder}/{name} is already tracked in {ledger.path} — not an orphan")
    client = connect()
    rows = {r["fileName"]: r for r in client.ls(client.resolve_dir(folder))}
    row = rows.get(name)
    if row is None:
        raise FileNotFoundError(
            f"{folder}/{name} is not on the server — nothing to reconcile")
    manifest = json.loads(Path(manifest_path).read_text()) if manifest_path else None
    # Synthesize the push-info entry_for expects from the listing row (the same
    # md5/size a completed push would have recorded).
    push_info = {"folder": folder, "name": name,
                 "md5": row["md5"], "size": row["size"]}
    entry = entry_for(Path(name), push_info, manifest, manifest_path)
    ledger.upsert(entry)
    ledger.save()
    return {
        "doc_id": entry["doc_id"],
        "remote": entry["remote"],
        "manifest": entry["manifest"],
        "base_md5": entry["base_md5"],
        "ledger": str(ledger.path),
    }


def status(connect, ledger, *, acknowledge):
    """Poll the cloud for every ledger entry and return the status-row list
    (``doc_id``/``remote``/``state``/``mark_md5``/``base_changed`` per entry).

    When ``acknowledge`` is set, mark responded/changed entries as seen and
    persist the ledger (the domain write) before returning.
    """
    results = check_entries(ledger.entries, connect())
    if acknowledge:
        for r in results:
            if r["state"] in ("responded", "changed"):
                _acknowledge(r["entry"], r["mark_md5"])
        ledger.save()
    return [
        {k: r[k] for k in ("doc_id", "remote", "state", "mark_md5", "base_changed")}
        for r in results
    ]


def collect(connect, ledger, doc_id, *, output_dir):
    """Pull ``doc_id``'s ``.pdf.mark``, resolve its answers against the compose
    manifest, and materialize the ``<doc>.answers.json`` sidecar under
    ``output_dir`` (ADR-0003). Returns the ``collect.v1`` body. Does NOT mutate
    the ledger.

    Raises ``UnknownDocError`` (no such doc_id), ``NoManifestError`` (dispatched
    without a manifest), ``NoResponseError`` (no ``.mark`` yet), or lets
    ``SparseMarkError`` from the decode propagate — all for the CLI to map.
    """
    entry = ledger.find(doc_id)
    if entry is None:
        raise UnknownDocError(
            f"no ledger entry for doc_id {doc_id!r} in {ledger.path}")
    if not entry["manifest"]:
        raise NoManifestError(
            f"{doc_id} was dispatched without a manifest — nothing to resolve the "
            "ink against; pull the .mark directly with 'inkbridge pull'")

    folder, name = entry["remote"]["folder"], entry["remote"]["name"]
    output_dir = Path(output_dir)
    dest = output_dir / (name + ".mark")
    try:
        info = connect().pull(folder, name + ".mark", dest)
    except FileNotFoundError as e:  # covers MissingBytesError phantoms too
        raise NoResponseError(f"no response yet for {doc_id}: {e}") from e

    manifest = json.loads(Path(entry["manifest"]).read_text())
    # Module-attribute access (not a bound import) so a monkeypatched
    # inkbridge.readback.read_mark is honored; SparseMarkError propagates.
    resolved = resolve_answers(_readback.read_mark(manifest, dest))
    # Provenance = the listing md5, the same ink signal 'status' reports, so a
    # consumer diffs sidecar.mark_md5 against status to detect staleness.
    payload = answers_payload(doc_id, dest, resolved, mark_md5=info["listing_md5"])

    sidecar = output_dir / f"{doc_id}.answers.json"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(
        json.dumps({"schema_version": ANSWERS_SCHEMA, **payload}, indent=2) + "\n")
    return {**payload, "answers_file": str(sidecar)}


def wait(connect, ledger, doc_id, *, timeout, poll_interval=2.0, max_interval=30.0,
         sleep=time.sleep, monotonic=time.monotonic):
    """Bounded long-poll for ``doc_id``'s mark to arrive — the synchronizing
    verb of the dispatch→(human inks)→collect loop (D1). Polls ``status`` with
    exponential backoff (``poll_interval`` doubling to ``max_interval``) until a
    mark lands (state ``responded``/``changed``) or the ``timeout`` window
    elapses. Returns a status-row dict on arrival; raises ``WaitTimeout`` if none
    arrives, or ``UnknownDocError`` for an unknown doc.

    ``sleep``/``monotonic`` are injectable so a test drives the backoff loop
    deterministically without real waiting.
    """
    entry = ledger.find(doc_id)
    if entry is None:
        raise UnknownDocError(
            f"no ledger entry for doc_id {doc_id!r} in {ledger.path}")

    client = connect()  # one login for the whole poll, not one per tick
    deadline = monotonic() + timeout
    interval = poll_interval
    while True:
        (row,) = check_entries([entry], client)
        if row["state"] in ("responded", "changed"):
            return {k: row[k] for k in
                    ("doc_id", "remote", "state", "mark_md5", "base_changed")}
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise WaitTimeout(
                f"no mark for {doc_id} within {timeout:g}s (last state: {row['state']})")
        sleep(min(interval, remaining))
        interval = min(interval * 2, max_interval)
