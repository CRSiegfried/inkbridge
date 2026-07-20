from __future__ import annotations

from pathlib import Path

import click

from inkbridge.merge import merge_pdfs


@click.group()
@click.version_option()
def main() -> None:
    """inkbridge: push documents to a Supernote Manta, pull annotations back."""


def _split_remote(remote_path: str) -> tuple[str, str]:
    """'Document/f.pdf.mark' -> ('Document', 'f.pdf.mark')."""
    folder, _, name = remote_path.strip("/").partition("/")
    if not folder or not name:
        raise click.BadParameter(
            f"remote path must look like 'Document/file.pdf', got {remote_path!r}")
    return folder, name


@main.command()
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option("--to", "remote_folder", default="Document",
              help="Root folder on the private cloud (device files go in Document).")
def push(file: Path, remote_folder: str) -> None:
    """Push a document to the private cloud (synced to the device)."""
    from inkbridge.transport.private_cloud import PCClient

    info = PCClient.from_env().push(file, remote_folder)
    click.echo(
        f"Pushed {file} -> {info['folder']}/{info['name']} "
        f"({info['size']} bytes, md5 {info['md5']}, verified in listing)"
    )


@main.command()
@click.argument("remote_path")
@click.option("-o", "--output", type=click.Path(path_type=Path), required=True)
def pull(remote_path: str, output: Path) -> None:
    """Pull a file back from the private cloud (e.g. Document/f.pdf.mark)."""
    from inkbridge.transport.private_cloud import MissingBytesError, PCClient

    folder, name = _split_remote(remote_path)
    try:
        info = PCClient.from_env().pull(folder, name, output)
    except MissingBytesError as e:
        raise click.ClickException(str(e)) from e
    match = "md5 verified" if info["match"] else (
        f"MD5 MISMATCH: listing {info['listing_md5']} != bytes {info['bytes_md5']}")
    click.echo(f"Pulled {remote_path} -> {output} ({info['size']} bytes, {match})")


@main.command()
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output", type=click.Path(path_type=Path), default=None)
@click.option("--manifest", "manifest_path", type=click.Path(path_type=Path), default=None)
def compose(source: Path, output: Path | None, manifest_path: Path | None) -> None:
    """Render markdown to a row-grid PDF + input-area manifest (Phase 2.5)."""
    from inkbridge.compose import compose as compose_markdown

    output = output or source.with_suffix(".pdf")
    result = compose_markdown(source, output, manifest_path)
    click.echo(
        f"Wrote {result.pdf_path} ({result.pages} page(s)) and "
        f"{result.manifest_path} ({len(result.cells)} cells, doc_id {result.doc_id})"
    )


@main.command()
@click.argument("remote_paths", nargs=-1, required=True)
@click.confirmation_option(
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
        for name in client.delete(folder, names):
            click.echo(f"Deleted {folder}/{name}")


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
