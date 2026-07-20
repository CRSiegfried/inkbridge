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
