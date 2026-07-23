from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import click

from inkbridge.merge import merge_pdfs
from inkbridge.obs import configure_logging, get_logger


@click.group()
@click.version_option()
@click.option(
    "-v", "--verbose", count=True,
    help="Log per-invocation activity to stderr (repeat for DEBUG). Do NOT combine "
         "with a machine consumer parsing the --json stderr envelope; use --log-file "
         "for inspectable subprocess runs instead.")
@click.option(
    "--log-file", "log_file", envvar="INKBRIDGE_LOG",
    type=click.Path(path_type=Path), default=None,
    help="Also append per-invocation logs to this file (or set INKBRIDGE_LOG). File "
         "logging never touches stdout/stderr, so it is safe under --json.")
@click.pass_context
def main(ctx: click.Context, verbose: int, log_file: Path | None) -> None:
    """inkbridge: push documents to a Supernote Manta, pull annotations back."""
    configure_logging(verbose, log_file)
    # Log the subcommand being dispatched. (Click consumes the subcommand's own
    # arguments before this callback runs, and sys.argv would be the *embedding*
    # process's argv when inkbridge is driven in-process; ctx.invoked_subcommand
    # is the one faithful signal here. Specific argument values — remote paths,
    # doc_ids, cloud endpoint — surface in the transport-layer and exit-reason
    # logs below.)
    get_logger().info("invoke: inkbridge %s", ctx.invoked_subcommand or "")


def _split_remote(remote_path: str) -> tuple[str, str]:
    """'Document/f.pdf.mark' -> ('Document', 'f.pdf.mark'); nested folders
    split on the last slash: 'Document/Projects/f.pdf' -> ('Document/Projects', 'f.pdf')."""
    folder, _, name = remote_path.strip("/").rpartition("/")
    if not folder or not name:
        raise click.BadParameter(
            f"remote path must look like 'Document/file.pdf', got {remote_path!r}")
    return folder, name


@contextmanager
def _cloud_errors(as_json: bool = False):
    """Translate transport failures into the ADR-0002 exit taxonomy so a
    cloud command emits a typed exit instead of a bare traceback: rejected or
    expired credentials -> AUTH(5); the cloud being unreachable (DNS, connect,
    timeout) -> PRECONDITION(6). Anything else propagates unchanged.

    Wrap the network region of every command that logs in (``from_env``) or
    calls the cloud; without it those failures escape as an uncaught exception
    (exit 1 + traceback), which an agent cannot branch on.
    """
    import httpx

    from inkbridge.contract import CliError, Exit
    from inkbridge.transport import AuthError

    try:
        yield
    except AuthError as e:
        raise CliError(f"cloud authentication failed: {e}", code="auth",
                       exit_status=Exit.AUTH, as_json=as_json) from e
    except httpx.RequestError as e:
        raise CliError(f"cloud is unreachable: {e}", code="unreachable",
                       exit_status=Exit.PRECONDITION, as_json=as_json) from e


@contextmanager
def _mark_errors(as_json: bool = False):
    """Translate a sparse-mark refusal into the ADR-0002 exit taxonomy: a
    manifest page absent from the pulled mark (a sparse mark — blank/missing
    page — that can't be read positionally, ADR-0004) becomes a typed
    PRECONDITION(6), not an uncaught traceback an agent can't branch on.

    Wrap the region that decodes a ``.pdf.mark`` — ``read_mark`` directly
    (``readback``/``answers``) or via ``ops.collect``. This is the CLI-side
    home of the ``SparseMarkError`` mapping that ADR-0006 moved out of the
    shared read path so ``ops`` stays free of ``CliError``.
    """
    from inkbridge.contract import CliError, Exit
    from inkbridge.readback import SparseMarkError

    try:
        yield
    except SparseMarkError as e:
        raise CliError(str(e), code="sparse_mark", exit_status=Exit.PRECONDITION,
                       as_json=as_json) from e


@main.command()
@click.argument("folder", required=False, default="")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def ls(folder: str, as_json: bool) -> None:
    """List a private-cloud folder (the root if omitted; nested paths ok).

    Contract (ADR-0002): the --json result is an ls.v1 document with the folder
    and its entries. Exit 4 if the folder does not exist, 5 auth, 6 unreachable.
    """
    from inkbridge import transport
    from inkbridge.contract import CliError, Exit, emit_result

    with _cloud_errors(as_json):
        client = transport.connect()
        try:
            rows = client.ls(client.resolve_dir(folder)) if folder else client.ls()
        except FileNotFoundError as e:
            raise CliError(str(e), code="not_found", exit_status=Exit.NOT_FOUND,
                           as_json=as_json) from e
    ordered = sorted(rows, key=lambda r: (r["isFolder"] != "Y", r["fileName"].lower()))
    if as_json:
        emit_result({
            "folder": folder,
            "entries": [{
                "name": r["fileName"],
                "is_folder": r["isFolder"] == "Y",
                "size": r["size"],
                "md5": r.get("md5", ""),
            } for r in ordered],
        }, "ls.v1")
        return
    if not rows:
        click.echo("(empty)")
        return
    for r in ordered:
        if r["isFolder"] == "Y":
            click.echo(f"{'<dir>':>10}  {'':32}  {r['fileName']}/")
        else:
            click.echo(f"{r['size']:>10}  {r.get('md5', ''):32}  {r['fileName']}")


@main.command()
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option("--to", "remote_folder", default="Document",
              help="Destination folder on the private cloud (device files go in "
                   "Document; nested paths like Document/Projects ok — the folder "
                   "must already exist).")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def push(file: Path, remote_folder: str, as_json: bool) -> None:
    """Push a document to the private cloud (synced to the device).

    Contract (ADR-0002): the --json result is a push.v1 document with the remote
    location, size, and md5. Exit 4 if the folder is missing, 1 if the name is
    already taken (no overwrite), 5 auth, 6 unreachable.
    """
    from inkbridge import transport
    from inkbridge.contract import CliError, Exit, emit_result

    with _cloud_errors(as_json):
        try:
            info = transport.connect().push(file, remote_folder)
        except FileNotFoundError as e:
            raise CliError(str(e), code="not_found", exit_status=Exit.NOT_FOUND,
                           as_json=as_json) from e
        except FileExistsError as e:
            raise CliError(str(e), code="already_exists", exit_status=Exit.ERROR,
                           as_json=as_json) from e
    if as_json:
        emit_result({
            "source": str(file),
            "folder": info["folder"],
            "name": info["name"],
            "size": info["size"],
            "md5": info["md5"],
        }, "push.v1")
        return
    click.echo(
        f"Pushed {file} -> {info['folder']}/{info['name']} "
        f"({info['size']} bytes, md5 {info['md5']}, verified in listing)"
    )


@main.command()
@click.argument("remote_path")
@click.option("-o", "--output", type=click.Path(path_type=Path), required=True)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def pull(remote_path: str, output: Path, as_json: bool) -> None:
    """Pull a file back from the private cloud (e.g. Document/f.pdf.mark).

    Contract (ADR-0002): the --json result is a pull.v1 document with the output
    path, size, and md5-match. Exit 4 if the remote file is absent, 5 auth,
    6 unreachable.
    """
    from inkbridge import transport
    from inkbridge.contract import CliError, Exit, emit_result

    folder, name = _split_remote(remote_path)
    with _cloud_errors(as_json):
        try:
            info = transport.connect().pull(folder, name, output)
        except FileNotFoundError as e:  # covers MissingBytesError phantoms too
            raise CliError(str(e), code="not_found", exit_status=Exit.NOT_FOUND,
                           as_json=as_json) from e
    if as_json:
        emit_result({
            "remote": remote_path,
            "output": str(output),
            "size": info["size"],
            "listing_md5": info["listing_md5"],
            "bytes_md5": info["bytes_md5"],
            "match": info["match"],
        }, "pull.v1")
        return
    match = "md5 verified" if info["match"] else (
        f"MD5 MISMATCH: listing {info['listing_md5']} != bytes {info['bytes_md5']}")
    click.echo(f"Pulled {remote_path} -> {output} ({info['size']} bytes, {match})")


@main.command()
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output", type=click.Path(path_type=Path), default=None)
@click.option("--manifest", "manifest_path", type=click.Path(path_type=Path), default=None)
@click.option("--device", default="manta", show_default=True,
              type=click.Choice(["manta", "nomad"]),
              help="Target device profile. The nomad profile's chrome envelope "
                   "is assumed, not device-calibrated.")
@click.option("--density", default="dense", show_default=True,
              type=click.Choice(["normal", "compact", "dense"]),
              help="Layout density preset. Tighter presets shrink fonts, rows, "
                   "and tickable boxes uniformly to fit more per page. 'dense' is "
                   "the device-validated default; 'normal' is the calibrated 1.0 "
                   "baseline. Overridden by --scale.")
@click.option("--scale", type=float, default=None,
              help="Exact density scale (1.0 = baseline; <1 packs tighter). "
                   "Overrides --density; for previewing arbitrary values.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def compose(source: Path, output: Path | None, manifest_path: Path | None,
            device: str, density: str, scale: float | None, as_json: bool) -> None:
    """Render markdown to a row-grid PDF + input-area manifest (Phase 2.5).

    Contract-compliant (ADR-0002): the --json result is a compose.v1 document
    carrying the generated doc_id, output paths, and cell/page counts. Exit 1
    on unrenderable source.
    """
    from inkbridge.compose import DENSITIES
    from inkbridge.compose import compose as compose_markdown
    from inkbridge.contract import CliError, Exit, emit_result

    output = output or source.with_suffix(".pdf")
    scale = scale if scale is not None else DENSITIES[density]
    try:
        result = compose_markdown(source, output, manifest_path,
                                  device=device, scale=scale)
    except ValueError as e:
        raise CliError(str(e), code="invalid_source", exit_status=Exit.ERROR,
                       as_json=as_json) from e
    if as_json:
        emit_result({
            "doc_id": result.doc_id,
            "pdf": str(result.pdf_path),
            "manifest": str(result.manifest_path),
            "pages": result.pages,
            "cells": len(result.cells),
            "device": device,
            "scale": scale,
        }, "compose.v1")
        return
    click.echo(
        f"Wrote {result.pdf_path} ({result.pages} page(s), {device}, scale {scale:g}) "
        f"and {result.manifest_path} ({len(result.cells)} cells, doc_id {result.doc_id})"
    )


@main.command()
@click.argument("remote_paths", nargs=-1, required=True)
@click.option("-y", "--yes", "yes", is_flag=True,
              help="Confirm the deletion non-interactively (required under --json "
                   "or when stdin is not a TTY).")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def rm(remote_paths: tuple[str, ...], yes: bool, as_json: bool) -> None:
    """Delete files from the private cloud (e.g. Document/f.pdf).

    Destructive, so it needs confirmation — but never by blocking on stdin
    (CT2): an agent that omits ``-y`` under ``--json`` or a non-TTY stdin gets a
    typed ``confirmation_required`` exit (6), not a hung prompt. Only an
    interactive human (a TTY, human mode) is prompted. Pass ``-y``/``--yes`` to
    delete non-interactively.
    """
    from inkbridge import transport
    from inkbridge.contract import CliError, Exit, emit_result

    if not yes:
        interactive = sys.stdin.isatty() and not as_json
        if not interactive:
            raise CliError(
                "refusing to delete without confirmation: pass -y/--yes "
                "(no interactive prompt under --json or a non-TTY stdin)",
                code="confirmation_required", exit_status=Exit.PRECONDITION,
                as_json=as_json)
        if not click.confirm(
                "Delete these files from the private cloud (and, on sync, "
                "the device)?"):
            raise click.Abort()

    by_folder: dict[str, list[str]] = {}
    for rp in remote_paths:
        folder, name = _split_remote(rp)
        by_folder.setdefault(folder, []).append(name)
    deleted_all: list[str] = []
    with _cloud_errors(as_json):
        client = transport.connect()
        for folder, names in by_folder.items():
            try:
                deleted = client.delete(folder, names)
            except FileNotFoundError as e:
                raise CliError(str(e), code="not_found", exit_status=Exit.NOT_FOUND,
                               as_json=as_json) from e
            for name in deleted:
                deleted_all.append(f"{folder}/{name}")
                if not as_json:
                    click.echo(f"Deleted {folder}/{name}")
    if as_json:
        emit_result({"deleted": deleted_all}, "rm.v1")


_LEDGER_OPT = click.option(
    "--ledger", "ledger_path", type=click.Path(path_type=Path), default=None,
    help="Dispatch ledger file [default: $INKBRIDGE_LEDGER, else a per-user "
         "state dir (XDG_STATE_HOME/inkbridge/ledger.json) — never cwd-relative].")


@main.command()
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option("--to", "remote_folder", default="Document",
              help="Destination folder on the private cloud (nested ok; must exist).")
@click.option("--manifest", "manifest_path",
              type=click.Path(exists=True, path_type=Path), default=None,
              help="Compose manifest for FILE [default: FILE's sibling "
                   ".manifest.json, when present].")
@click.option("--replace", is_flag=True,
              help="Delete any existing remote copy first, then push (idempotent "
                   "re-dispatch — the private cloud has no overwrite, so a plain "
                   "re-dispatch would fail 'already exists').")
@_LEDGER_OPT
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def dispatch(file: Path, remote_folder: str, manifest_path: Path | None,
             replace: bool, ledger_path: Path | None, as_json: bool) -> None:
    """Push FILE and record it in the dispatch ledger as awaiting a
    response — the .pdf.mark sidecar the device syncs back once inked.
    'inkbridge status' polls for it; 'inkbridge collect' reads it back.

    Contract-compliant (ADR-0002): the --json result is a dispatch.v1 document
    carrying the recorded doc_id, remote location, cell counts, and ledger
    path. Exit 4 when the remote folder does not exist, 1 already_exists (use
    --replace to re-dispatch idempotently), 5 auth, 6 unreachable.
    """
    from inkbridge import ops, transport
    from inkbridge.contract import CliError, Exit, emit_result
    from inkbridge.dispatch import Ledger

    if manifest_path is None:
        sibling = file.with_suffix(".manifest.json")
        manifest_path = sibling if sibling.exists() else None
    ledger = Ledger(ledger_path)
    with _cloud_errors(as_json):
        try:
            payload = ops.dispatch(transport.connect, ledger, file,
                                   remote_folder=remote_folder,
                                   manifest_path=manifest_path, replace=replace)
        except FileNotFoundError as e:
            raise CliError(str(e), code="not_found", exit_status=Exit.NOT_FOUND,
                           as_json=as_json) from e
        except FileExistsError as e:
            raise CliError(str(e), code="already_exists", exit_status=Exit.ERROR,
                           as_json=as_json) from e
    if as_json:
        emit_result(payload, "dispatch.v1")
        return
    detail = (
        f"{payload['response_cells']} response cell(s), "
        f"{payload['trigger_cells']} trigger(s)"
        if payload["manifest"] else "no manifest — arrival tracking only")
    click.echo(
        f"Dispatched {file} -> {payload['remote']['folder']}/{payload['remote']['name']} "
        f"(doc_id {payload['doc_id']}, {detail}); ledger: {payload['ledger']}")


@main.command()
@click.argument("remote_path")
@click.option("--manifest", "manifest_path",
              type=click.Path(exists=True, path_type=Path), default=None,
              help="Compose manifest for the adopted file (so 'collect' can "
                   "resolve its ink); without it the doc is tracked for arrival "
                   "only.")
@_LEDGER_OPT
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def reconcile(remote_path: str, manifest_path: Path | None,
              ledger_path: Path | None, as_json: bool) -> None:
    """Adopt an orphaned remote file into the ledger: a file present on the
    cloud (e.g. REMOTE_PATH = Document/f.pdf) with no ledger entry — a dispatch
    that pushed then crashed before saving, or a file pushed out of band — so
    'status'/'collect' can track it again.

    Contract (ADR-0002): the --json result is a reconcile.v1 document with the
    recorded doc_id, remote, base_md5, and ledger path. Exit 3 when the file is
    already tracked (not an orphan), 4 when no such remote file exists, 5 auth,
    6 unreachable.
    """
    from inkbridge import ops, transport
    from inkbridge.contract import CliError, Exit, emit_result
    from inkbridge.dispatch import Ledger

    folder, name = _split_remote(remote_path)
    ledger = Ledger(ledger_path)
    with _cloud_errors(as_json):
        try:
            payload = ops.reconcile(transport.connect, ledger, folder, name,
                                    manifest_path=manifest_path)
        except ops.AlreadyTrackedError as e:
            raise CliError(str(e), code="already_tracked",
                           exit_status=Exit.NO_CHANGE, as_json=as_json) from e
        except FileNotFoundError as e:
            raise CliError(str(e), code="not_found", exit_status=Exit.NOT_FOUND,
                           as_json=as_json) from e
    if as_json:
        emit_result(payload, "reconcile.v1")
        return
    click.echo(
        f"Reconciled {payload['remote']['folder']}/{payload['remote']['name']} "
        f"-> doc_id {payload['doc_id']} (base md5 {payload['base_md5']}); "
        f"ledger: {payload['ledger']}")


@main.command()
@_LEDGER_OPT
@click.option("--update", is_flag=True,
              help="Acknowledge responded/changed marks: later runs report "
                   "'seen' until new ink lands on top.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def status(ledger_path: Path | None, update: bool, as_json: bool) -> None:
    """Poll the private cloud for responses to dispatched documents:
    waiting / RESPONDED / CHANGED / seen / missing per ledger entry.

    Contract (ADR-0002): the --json result is a status.v1 document carrying the
    ledger path and one row per entry (through the schema_version envelope, not
    a bare list). Exit 5 auth, 6 unreachable.
    """
    from inkbridge import ops, transport
    from inkbridge.contract import emit_result
    from inkbridge.dispatch import Ledger

    ledger = Ledger(ledger_path)
    if not ledger.entries:
        if as_json:
            emit_result({"ledger": str(ledger.path), "entries": []}, "status.v1")
            return
        click.echo(f"ledger {ledger.path} is empty — nothing dispatched yet")
        return
    with _cloud_errors(as_json):
        rows = ops.status(transport.connect, ledger, acknowledge=update)
    if as_json:
        emit_result({"ledger": str(ledger.path), "entries": rows}, "status.v1")
        return
    for r in rows:
        state = r["state"].upper() if r["state"] in ("responded", "changed") else r["state"]
        if update and state in ("RESPONDED", "CHANGED"):
            state += " (acknowledged)"
        note = "  [base md5 drifted — join untrustworthy]" if r["base_changed"] else ""
        click.echo(f"{r['doc_id']:32} {r['remote']:44} {state}{note}")


@main.command()
@click.argument("doc_id")
@_LEDGER_OPT
@click.option("--timeout", default=300.0, show_default=True,
              help="Seconds to wait for a mark before giving up (exit 3).")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def wait(doc_id: str, ledger_path: Path | None, timeout: float,
         as_json: bool) -> None:
    """Block until DOC_ID's .pdf.mark response arrives, then exit 0 — the
    synchronizing verb of the dispatch → (human inks) → collect loop (D1).
    Bounded long-poll with exponential backoff; exit 3 (no change) on timeout,
    4 for an unknown doc_id.

    Contract (ADR-0002): the --json result is a wait.v1 status row (doc_id,
    remote, state, mark_md5, base_changed).
    """
    from inkbridge import ops, transport
    from inkbridge.contract import CliError, Exit, emit_result
    from inkbridge.dispatch import Ledger

    ledger = Ledger(ledger_path)
    with _cloud_errors(as_json):
        try:
            payload = ops.wait(transport.connect, ledger, doc_id, timeout=timeout)
        except ops.UnknownDocError as e:
            raise CliError(str(e), code="unknown_doc", exit_status=Exit.NOT_FOUND,
                           as_json=as_json) from e
        except ops.WaitTimeout as e:
            raise CliError(str(e), code="timeout", exit_status=Exit.NO_CHANGE,
                           as_json=as_json) from e
    if as_json:
        emit_result(payload, "wait.v1")
        return
    click.echo(f"{payload['doc_id']} {payload['remote']} "
               f"{payload['state'].upper()} (md5 {payload['mark_md5']})")


@main.command()
@click.argument("doc_id")
@_LEDGER_OPT
@click.option("-o", "--output-dir", type=click.Path(path_type=Path),
              default=Path("responses"), show_default=True,
              help="Where the pulled .pdf.mark and .answers.json sidecar land.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def collect(doc_id: str, ledger_path: Path | None, output_dir: Path,
            as_json: bool) -> None:
    """Pull DOC_ID's .pdf.mark response and materialize its answers: resolve
    the ink against the compose manifest and write a `<doc>.answers.json`
    sidecar (the answers.v1 document plus the mark md5 it reflects) beside the
    pulled mark. Reading state is then just parsing that file (ADR-0003).

    Unlike before, collect does NOT acknowledge or advance the ledger —
    reacting is left to the agent loop / an external watcher diffing the
    sidecar's mark_md5 against 'inkbridge status'. Contract-compliant
    (ADR-0002): exit 3 (no change) when there's no response yet, 4 for an
    unknown doc_id, 6 when the doc was dispatched without a manifest or the
    pulled mark is sparse (a blank page can't be read positionally, ADR-0004).
    """
    from inkbridge import ops
    from inkbridge.contract import CliError, Exit, emit_result
    from inkbridge.dispatch import Ledger
    from inkbridge import transport

    ledger = Ledger(ledger_path)
    try:
        with _cloud_errors(as_json), _mark_errors(as_json):
            payload = ops.collect(transport.connect, ledger, doc_id,
                                  output_dir=Path(output_dir))
    except ops.UnknownDocError as e:
        raise CliError(str(e), code="unknown_doc", exit_status=Exit.NOT_FOUND,
                       as_json=as_json) from e
    except ops.NoManifestError as e:
        raise CliError(str(e), code="no_manifest", exit_status=Exit.PRECONDITION,
                       as_json=as_json) from e
    except ops.NoResponseError as e:
        raise CliError(str(e), code="no_response", exit_status=Exit.NO_CHANGE,
                       as_json=as_json) from e

    if as_json:
        emit_result(payload, "collect.v1")
        return
    click.echo(f"doc:     {payload['doc_id']}\n"
               f"mark:    {payload['mark_file']} (md5 {payload['mark_md5']})")
    click.echo(f"answers: {payload['answers_file']}\n")
    click.echo(f"{'question':32} {'type':10} {'status':13} answer")
    for a in payload["answers"]:
        click.echo(f"{a['id']:32} {a['type']:10} {a['status']:13} {_answer_line(a)}")


@main.command()
@click.argument("manifest", type=click.Path(exists=True, path_type=Path))
@click.argument("mark_file", type=click.Path(exists=True, path_type=Path))
@click.option("--hash-store", "hash_store_path", type=click.Path(path_type=Path),
              default=None,
              help="JSON ink-hash store; reports per-page changed/unchanged "
                   "for re-dispatch idempotency (0012 F6).")
@click.option("--update-hashes/--no-update-hashes", default=True,
              help="Record the current page hashes into --hash-store.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def readback(manifest: Path, mark_file: Path, hash_store_path: Path | None,
             update_hashes: bool, as_json: bool) -> None:
    """Read a pulled .pdf.mark against its compose manifest: per-cell
    blank / ANSWERED / AMBIGUOUS decisions over the isolated ink decode.
    """
    import json as jsonlib

    from inkbridge.contract import emit_result
    from inkbridge.readback import InkHashStore, read_mark

    manifest_data = jsonlib.loads(manifest.read_text())
    doc_id = manifest_data["doc_id"]
    with _mark_errors(as_json):
        pages = read_mark(manifest_data, mark_file)

    store = InkHashStore(hash_store_path) if hash_store_path else None
    changed: dict[int, bool] = {}
    for p in pages:
        if store:
            changed[p.page] = store.changed(doc_id, p.page, p.ink_hash)
            if update_hashes:
                store.update(doc_id, p.page, p.ink_hash)

    if as_json:
        emit_result({
            "doc_id": doc_id,
            "mark_file": str(mark_file),
            "pages": [{
                "page": p.page,
                "ink_hash": p.ink_hash,
                **({"changed": changed[p.page]} if store else {}),
                "cells": [{
                    "id": c.id, "type": c.type, "label": c.label,
                    "coverage": c.coverage, "decision": c.decision.value,
                } for c in p.cells],
            } for p in pages],
        }, "readback.v1")
        return

    click.echo(f"doc:  {doc_id}\nmark: {mark_file}\n")
    click.echo(f"{'cell':24} {'type':12} {'coverage %':>10}  decision")
    for p in pages:
        note = ""
        if store:
            note = "  [changed since last poll]" if changed[p.page] else "  [unchanged]"
        click.echo(f"-- page {p.page}{note}")
        for c in p.cells:
            shown = {"blank": "blank", "ambiguous": "AMBIGUOUS -> escalate",
                     "answered": "ANSWERED"}[c.decision.value]
            click.echo(f"{c.id:24} {c.type:12} {c.coverage * 100:>10.4f}  {shown}")


@main.command()
@click.argument("manifest", type=click.Path(path_type=Path))
@click.argument("mark_file", type=click.Path(path_type=Path))
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def answers(manifest: Path, mark_file: Path, as_json: bool) -> None:
    """Semantic, question-level results for a pulled .pdf.mark read against
    its compose MANIFEST: each question resolved to its answer — single-choice
    winner or conflict, checkbox/ack boolean, comb/capture presence — or
    needs_review carrying the cell id to composite.

    A pure read (ADR-0002): it never touches ledger, remote, or local state,
    so an agent can re-inspect a response as often as it likes. This is the
    on-the-fly resolver; 'inkbridge collect' persists the same payload as a
    `<doc>.answers.json` sidecar. Run 'inkbridge readback' for the raw cells.
    """
    import json as jsonlib

    from inkbridge.answers import ANSWERS_SCHEMA, answers_payload, resolve_answers
    from inkbridge.contract import CliError, Exit, emit_result
    from inkbridge.readback import read_mark

    for kind, path in (("manifest", manifest), ("mark file", mark_file)):
        if not path.exists():
            raise CliError(f"{kind} not found: {path}", code="not_found",
                           exit_status=Exit.NOT_FOUND, as_json=as_json)

    try:
        manifest_data = jsonlib.loads(manifest.read_text())
    except jsonlib.JSONDecodeError as e:
        raise CliError(f"manifest is not valid JSON: {manifest} ({e})",
                       code="invalid_manifest", exit_status=Exit.ERROR,
                       as_json=as_json) from e
    doc_id = manifest_data.get("doc_id")
    with _mark_errors(as_json):
        resolved = resolve_answers(read_mark(manifest_data, mark_file))

    if as_json:
        emit_result(answers_payload(doc_id, mark_file, resolved), ANSWERS_SCHEMA)
        return

    click.echo(f"doc:  {doc_id}\nmark: {mark_file}\n")
    if not resolved:
        click.echo("(no answerable questions in this manifest)")
        return
    click.echo(f"{'question':32} {'type':10} {'status':13} answer")
    for a in resolved:
        click.echo(f"{a.id:32} {a.type:10} {a.status.value:13} {_answer_text(a)}")


def _answer_line(a: dict) -> str:
    """One-column rendering of a resolved answer in its ``answers.v1`` dict
    shape — the dict-shaped twin of :func:`_answer_text`, used by ``collect``
    which renders from the ``ops.collect`` payload rather than live ``Answer``
    objects. Kept byte-for-byte in step with ``_answer_text``."""
    status = a["status"]
    if status == "needs_review":
        return f"-> composite {', '.join(a.get('cells') or [])}"
    if status == "conflict":
        return f"conflict: {', '.join(a.get('value') or [])}"
    if status == "unanswered":
        return "-"
    # answered
    if a["type"] in ("checkbox", "ack"):
        return "yes" if a["value"] else "no"
    if a["value"] is None:  # presence-only comb/capture
        return "(present — composite to read)"
    return str(a["value"])


def _answer_text(a) -> str:
    """One-column human rendering of an Answer's outcome."""
    from inkbridge.answers import Status

    if a.status is Status.NEEDS_REVIEW:
        return f"-> composite {', '.join(a.cells or [])}"
    if a.status is Status.CONFLICT:
        return f"conflict: {', '.join(a.value or [])}"
    if a.status is Status.UNANSWERED:
        return "-"
    # ANSWERED
    if a.type in ("checkbox", "ack"):
        return "yes" if a.value else "no"
    if a.value is None:  # presence-only comb/capture
        return "(present — composite to read)"
    return str(a.value)


@main.command()
@click.argument("base_pdf", type=click.Path(exists=True, path_type=Path))
@click.argument("mark_file", type=click.Path(exists=True, path_type=Path))
@click.option("-p", "--page", default=1, show_default=True, help="1-indexed page.")
@click.option("-o", "--output", type=click.Path(path_type=Path), required=True)
@click.option("--cell", "cell_id", default=None,
              help="Crop to this manifest cell id (requires --manifest).")
@click.option("--manifest", "manifest_path",
              type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def composite(base_pdf: Path, mark_file: Path, page: int, output: Path,
              cell_id: str | None, manifest_path: Path | None,
              as_json: bool) -> None:
    """Overlay decoded .pdf.mark ink onto the rendered base PDF page —
    the capture render sent to a VLM (0012 F5). Never a coverage target.

    Contract (ADR-0002): the --json result is a composite.v1 document with the
    output path and pixel dimensions. Exit 4 when --cell names no such cell.
    """
    import json as jsonlib

    from inkbridge.composite import composite_page, composite_region
    from inkbridge.contract import CliError, Exit, emit_result

    if cell_id:
        if not manifest_path:
            raise click.UsageError("--cell requires --manifest")
        cells = jsonlib.loads(manifest_path.read_text())["cells"]
        match = next((c for c in cells if c["id"] == cell_id), None)
        if match is None:
            raise CliError(f"no cell {cell_id!r} in {manifest_path}", code="not_found",
                           exit_status=Exit.NOT_FOUND, as_json=as_json)
        img = composite_region(
            base_pdf, mark_file, match["page"], tuple(match["bbox_norm"]))
    else:
        img = composite_page(base_pdf, mark_file, page)
    output.parent.mkdir(parents=True, exist_ok=True)
    img.save(output)
    if as_json:
        emit_result({
            "output": str(output),
            "width": img.size[0],
            "height": img.size[1],
        }, "composite.v1")
        return
    click.echo(f"Wrote {output} ({img.size[0]}x{img.size[1]})")


@main.command()
@click.argument("manifest", type=click.Path(path_type=Path))
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
@click.pass_context
def proof(ctx: click.Context, manifest: Path, as_json: bool) -> None:
    """Device-free self-test (Analysis 0017 F8): stamp synthetic ink into
    every cell of MANIFEST, read it back, and assert every cell reads
    ANSWERED. Catches manifest/readback drift with no device and no human.

    Contract (ADR-0002): exit 0 when every cell passes, 1 when any cell fails
    to read ANSWERED, 4 for a missing manifest. The --json result carries the
    per-cell failures.
    """
    import json as jsonlib

    from inkbridge.contract import CliError, Exit, emit_result
    from inkbridge.proof import proof as run_proof
    from inkbridge.proof import proof_payload

    if not manifest.exists():
        raise CliError(f"manifest not found: {manifest}", code="not_found",
                       exit_status=Exit.NOT_FOUND, as_json=as_json)
    try:
        manifest_data = jsonlib.loads(manifest.read_text())
    except jsonlib.JSONDecodeError as e:
        raise CliError(f"manifest is not valid JSON: {manifest} ({e})",
                       code="invalid_manifest", exit_status=Exit.ERROR,
                       as_json=as_json) from e

    result = run_proof(manifest_data)
    if as_json:
        emit_result(proof_payload(result), "proof.v1")
    else:
        click.echo(f"doc:   {result.doc_id}")
        click.echo(f"cells: {result.cells} across {result.pages} page(s)")
        if result.ok:
            click.echo("PASS — every cell read ANSWERED")
        else:
            click.echo(f"FAIL — {len(result.failures)} cell(s) did not read ANSWERED:")
            for f in result.failures:
                click.echo(
                    f"  p{f.page} {f.id} ({f.type}): {f.decision} "
                    f"@ {f.coverage * 100:.4f}%")
    if not result.ok:
        ctx.exit(int(Exit.ERROR))


@main.command()
@click.argument("base", type=click.Path(exists=True, path_type=Path))
@click.argument("addition", type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output", type=click.Path(path_type=Path), required=True)
@click.option(
    "--position",
    type=click.Choice(["append", "prepend"]),
    default="append",
    help="Whether addition's pages go after or before base's.",
)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def merge(base: Path, addition: Path, output: Path, position: str,
          as_json: bool) -> None:
    """Merge a PDF and/or .note file into one PDF.

    BASE and ADDITION may each be a .pdf or a .note file. Contract (ADR-0002):
    the --json result is a merge.v1 document with the output path. Exit 1 on
    an unmergeable input.
    """
    from inkbridge.contract import CliError, Exit, emit_result

    try:
        result = merge_pdfs(base, addition, output, position=position)
    except ValueError as e:
        raise CliError(str(e), code="invalid_input", exit_status=Exit.ERROR,
                       as_json=as_json) from e
    if as_json:
        emit_result({"output": str(result)}, "merge.v1")
        return
    click.echo(f"Wrote {result}")


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def doctor(as_json: bool) -> None:
    """Check the integration is ready before dispatching: cloud configured,
    reachable, and the credentials accepted (ADR-0002 doctor-class).

    Unlike 'proof' (a device-free manifest/readback self-test that never
    contacts the cloud), doctor is the cloud/auth/connectivity probe: it logs
    in and lists the root — read-only, no device needed. Contract exits:
    0 ready, 5 auth (credentials rejected or expired), 6 precondition
    (missing INKBRIDGE_CLOUD_* config, or the cloud is unreachable). The
    --json result is a doctor.v1 document listing each check.
    """
    from inkbridge.contract import CliError, Exit, emit_result
    from inkbridge import transport

    checks: list[dict] = []
    with _cloud_errors(as_json):
        try:
            client = transport.connect()
        except KeyError as e:
            raise CliError(f"missing cloud configuration: {e}", code="config_missing",
                           exit_status=Exit.PRECONDITION, as_json=as_json) from e
        checks.append({"name": "authentication", "ok": True,
                       "detail": "credentials accepted"})
        rows = client.ls()
        checks.append({"name": "connectivity", "ok": True,
                       "detail": f"root listing returned {len(rows)} item(s)"})

    payload = {"ok": True, "url": client.api, "checks": checks}
    if as_json:
        emit_result(payload, "doctor.v1")
        return
    click.echo(f"doctor: OK — {client.api} reachable, credentials accepted")
    for c in checks:
        click.echo(f"  [pass] {c['name']}: {c['detail']}")


if __name__ == "__main__":
    main()
