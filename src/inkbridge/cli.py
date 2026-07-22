from __future__ import annotations

from pathlib import Path

import click

from inkbridge.merge import merge_pdfs


@click.group()
@click.version_option()
def main() -> None:
    """inkbridge: push documents to a Supernote Manta, pull annotations back."""


def _split_remote(remote_path: str) -> tuple[str, str]:
    """'Document/f.pdf.mark' -> ('Document', 'f.pdf.mark'); nested folders
    split on the last slash: 'Document/Projects/f.pdf' -> ('Document/Projects', 'f.pdf')."""
    folder, _, name = remote_path.strip("/").rpartition("/")
    if not folder or not name:
        raise click.BadParameter(
            f"remote path must look like 'Document/file.pdf', got {remote_path!r}")
    return folder, name


@main.command()
@click.argument("folder", required=False, default="")
def ls(folder: str) -> None:
    """List a private-cloud folder (the root if omitted; nested paths ok)."""
    from inkbridge.transport.private_cloud import PCClient

    client = PCClient.from_env()
    try:
        rows = client.ls(client.resolve_dir(folder)) if folder else client.ls()
    except FileNotFoundError as e:
        raise click.ClickException(str(e)) from e
    if not rows:
        click.echo("(empty)")
        return
    for r in sorted(rows, key=lambda r: (r["isFolder"] != "Y", r["fileName"].lower())):
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
def push(file: Path, remote_folder: str) -> None:
    """Push a document to the private cloud (synced to the device)."""
    from inkbridge.transport.private_cloud import PCClient

    try:
        info = PCClient.from_env().push(file, remote_folder)
    except (FileNotFoundError, FileExistsError) as e:
        raise click.ClickException(str(e)) from e
    click.echo(
        f"Pushed {file} -> {info['folder']}/{info['name']} "
        f"({info['size']} bytes, md5 {info['md5']}, verified in listing)"
    )


@main.command()
@click.argument("remote_path")
@click.option("-o", "--output", type=click.Path(path_type=Path), required=True)
def pull(remote_path: str, output: Path) -> None:
    """Pull a file back from the private cloud (e.g. Document/f.pdf.mark)."""
    from inkbridge.transport.private_cloud import PCClient

    folder, name = _split_remote(remote_path)
    try:
        info = PCClient.from_env().pull(folder, name, output)
    except FileNotFoundError as e:  # covers MissingBytesError phantoms too
        raise click.ClickException(str(e)) from e
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
def compose(source: Path, output: Path | None, manifest_path: Path | None,
            device: str, density: str, scale: float | None) -> None:
    """Render markdown to a row-grid PDF + input-area manifest (Phase 2.5)."""
    from inkbridge.compose import DENSITIES
    from inkbridge.compose import compose as compose_markdown

    output = output or source.with_suffix(".pdf")
    scale = scale if scale is not None else DENSITIES[density]
    try:
        result = compose_markdown(source, output, manifest_path,
                                  device=device, scale=scale)
    except ValueError as e:
        raise click.BadParameter(str(e)) from e
    click.echo(
        f"Wrote {result.pdf_path} ({result.pages} page(s), {device}, scale {scale:g}) "
        f"and {result.manifest_path} ({len(result.cells)} cells, doc_id {result.doc_id})"
    )


@main.command()
@click.argument("remote_paths", nargs=-1, required=True)
@click.confirmation_option(
    "-y", "--yes",
    prompt="Delete these files from the private cloud (and, on sync, the device)?")
def rm(remote_paths: tuple[str, ...]) -> None:
    """Delete files from the private cloud (e.g. Document/f.pdf)."""
    from inkbridge.transport.private_cloud import PCClient

    by_folder: dict[str, list[str]] = {}
    for rp in remote_paths:
        folder, name = _split_remote(rp)
        by_folder.setdefault(folder, []).append(name)
    client = PCClient.from_env()
    for folder, names in by_folder.items():
        try:
            deleted = client.delete(folder, names)
        except FileNotFoundError as e:
            raise click.ClickException(str(e)) from e
        for name in deleted:
            click.echo(f"Deleted {folder}/{name}")


_LEDGER_OPT = click.option(
    "--ledger", "ledger_path", type=click.Path(path_type=Path), default=None,
    help="Dispatch ledger file [default: $INKBRIDGE_LEDGER or ./inkbridge-ledger.json].")


@main.command()
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option("--to", "remote_folder", default="Document",
              help="Destination folder on the private cloud (nested ok; must exist).")
@click.option("--manifest", "manifest_path",
              type=click.Path(exists=True, path_type=Path), default=None,
              help="Compose manifest for FILE [default: FILE's sibling "
                   ".manifest.json, when present].")
@_LEDGER_OPT
def dispatch(file: Path, remote_folder: str, manifest_path: Path | None,
             ledger_path: Path | None) -> None:
    """Push FILE and record it in the dispatch ledger as awaiting a
    response — the .pdf.mark sidecar the device syncs back once inked.
    'inkbridge status' polls for it; 'inkbridge collect' reads it back.
    """
    import json as jsonlib

    from inkbridge.dispatch import Ledger, entry_for
    from inkbridge.transport.private_cloud import PCClient

    if manifest_path is None:
        sibling = file.with_suffix(".manifest.json")
        manifest_path = sibling if sibling.exists() else None
    manifest = jsonlib.loads(manifest_path.read_text()) if manifest_path else None
    try:
        info = PCClient.from_env().push(file, remote_folder)
    except (FileNotFoundError, FileExistsError) as e:
        raise click.ClickException(str(e)) from e
    ledger = Ledger(ledger_path)
    entry = entry_for(file, info, manifest, manifest_path)
    ledger.upsert(entry)
    ledger.save()
    detail = (
        f"{len(entry['response_cells'])} response cell(s), "
        f"{len(entry['trigger_cells'])} trigger(s)"
        if manifest else "no manifest — arrival tracking only")
    click.echo(
        f"Dispatched {file} -> {info['folder']}/{info['name']} "
        f"(doc_id {entry['doc_id']}, {detail}); ledger: {ledger.path}")


@main.command()
@_LEDGER_OPT
@click.option("--update", is_flag=True,
              help="Acknowledge responded/changed marks: later runs report "
                   "'seen' until new ink lands on top.")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
def status(ledger_path: Path | None, update: bool, as_json: bool) -> None:
    """Poll the private cloud for responses to dispatched documents:
    waiting / RESPONDED / CHANGED / seen / missing per ledger entry.
    """
    import json as jsonlib

    from inkbridge.dispatch import Ledger, acknowledge, check_entries
    from inkbridge.transport.private_cloud import PCClient

    ledger = Ledger(ledger_path)
    if not ledger.entries:
        click.echo(f"ledger {ledger.path} is empty — nothing dispatched yet")
        return
    results = check_entries(ledger.entries, PCClient.from_env())
    if update:
        for r in results:
            if r["state"] in ("responded", "changed"):
                acknowledge(r["entry"], r["mark_md5"])
        ledger.save()
    if as_json:
        click.echo(jsonlib.dumps([
            {k: r[k] for k in ("doc_id", "remote", "state", "mark_md5", "base_changed")}
            for r in results], indent=2))
        return
    for r in results:
        state = r["state"].upper() if r["state"] in ("responded", "changed") else r["state"]
        if update and state in ("RESPONDED", "CHANGED"):
            state += " (acknowledged)"
        note = "  [base md5 drifted — join untrustworthy]" if r["base_changed"] else ""
        click.echo(f"{r['doc_id']:32} {r['remote']:44} {state}{note}")


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
    unknown doc_id, 6 when the doc was dispatched without a manifest.
    """
    import json as jsonlib

    from inkbridge.answers import ANSWERS_SCHEMA, answers_payload, resolve_answers
    from inkbridge.contract import CliError, Exit, emit_result
    from inkbridge.dispatch import Ledger
    from inkbridge.readback import read_mark
    from inkbridge.transport.private_cloud import PCClient

    ledger = Ledger(ledger_path)
    entry = ledger.find(doc_id)
    if entry is None:
        raise CliError(f"no ledger entry for doc_id {doc_id!r} in {ledger.path}",
                       code="unknown_doc", exit_status=Exit.NOT_FOUND, as_json=as_json)
    if not entry["manifest"]:
        raise CliError(
            f"{doc_id} was dispatched without a manifest — nothing to resolve the "
            "ink against; pull the .mark directly with 'inkbridge pull'",
            code="no_manifest", exit_status=Exit.PRECONDITION, as_json=as_json)

    folder, name = entry["remote"]["folder"], entry["remote"]["name"]
    output_dir = Path(output_dir)
    dest = output_dir / (name + ".mark")
    try:
        info = PCClient.from_env().pull(folder, name + ".mark", dest)
    except FileNotFoundError as e:
        raise CliError(f"no response yet for {doc_id}: {e}", code="no_response",
                       exit_status=Exit.NO_CHANGE, as_json=as_json) from e

    manifest = jsonlib.loads(Path(entry["manifest"]).read_text())
    resolved = resolve_answers(read_mark(manifest, dest))
    # Provenance = the listing md5, the same ink signal 'status' reports, so a
    # consumer diffs sidecar.mark_md5 against status to detect staleness.
    payload = answers_payload(doc_id, dest, resolved, mark_md5=info["listing_md5"])

    sidecar = output_dir / f"{doc_id}.answers.json"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(
        jsonlib.dumps({"schema_version": ANSWERS_SCHEMA, **payload}, indent=2) + "\n")

    if as_json:
        emit_result({**payload, "answers_file": str(sidecar)}, "collect.v1")
        return
    click.echo(f"doc:     {doc_id}\nmark:    {dest} (md5 {info['listing_md5']})")
    click.echo(f"answers: {sidecar}\n")
    click.echo(f"{'question':32} {'type':10} {'status':13} answer")
    for a in resolved:
        click.echo(f"{a.id:32} {a.type:10} {a.status.value:13} {_answer_text(a)}")


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

    from inkbridge.readback import InkHashStore, read_mark

    manifest_data = jsonlib.loads(manifest.read_text())
    doc_id = manifest_data["doc_id"]
    pages = read_mark(manifest_data, mark_file)

    store = InkHashStore(hash_store_path) if hash_store_path else None
    changed: dict[int, bool] = {}
    for p in pages:
        if store:
            changed[p.page] = store.changed(doc_id, p.page, p.ink_hash)
            if update_hashes:
                store.update(doc_id, p.page, p.ink_hash)

    if as_json:
        click.echo(jsonlib.dumps({
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
        }, indent=2))
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
def composite(base_pdf: Path, mark_file: Path, page: int, output: Path,
              cell_id: str | None, manifest_path: Path | None) -> None:
    """Overlay decoded .pdf.mark ink onto the rendered base PDF page —
    the capture render sent to a VLM (0012 F5). Never a coverage target.
    """
    import json as jsonlib

    from inkbridge.composite import composite_page, composite_region

    if cell_id:
        if not manifest_path:
            raise click.UsageError("--cell requires --manifest")
        cells = jsonlib.loads(manifest_path.read_text())["cells"]
        match = next((c for c in cells if c["id"] == cell_id), None)
        if match is None:
            raise click.ClickException(f"no cell {cell_id!r} in {manifest_path}")
        img = composite_region(
            base_pdf, mark_file, match["page"], tuple(match["bbox_norm"]))
    else:
        img = composite_page(base_pdf, mark_file, page)
    output.parent.mkdir(parents=True, exist_ok=True)
    img.save(output)
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
def merge(base: Path, addition: Path, output: Path, position: str) -> None:
    """Merge a PDF and/or .note file into one PDF.

    BASE and ADDITION may each be a .pdf or a .note file.
    """
    result = merge_pdfs(base, addition, output, position=position)
    click.echo(f"Wrote {result}")


if __name__ == "__main__":
    main()
