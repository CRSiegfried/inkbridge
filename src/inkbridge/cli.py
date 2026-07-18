from __future__ import annotations

from pathlib import Path

import click

from inkbridge.merge import merge_pdfs


@click.group()
@click.version_option()
def main() -> None:
    """inkbridge: push documents to a Supernote Manta, pull annotations back."""


@main.command()
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option("--to", "remote_folder", default="/", help="Remote folder on the device/cloud.")
def push(file: Path, remote_folder: str) -> None:
    """Push a document to the device. (Phase 2 — not yet implemented.)"""
    from inkbridge.transport.cloud import push as cloud_push

    remote_path = cloud_push(file, remote_folder)
    click.echo(f"Pushed {file} -> {remote_path}")


@main.command()
@click.argument("remote_path")
@click.option("-o", "--output", type=click.Path(path_type=Path), required=True)
def pull(remote_path: str, output: Path) -> None:
    """Pull a notebook/file back from the device. (Phase 1 — not yet implemented.)"""
    from inkbridge.transport.cloud import pull as cloud_pull

    cloud_pull(remote_path, output)
    click.echo(f"Pulled {remote_path} -> {output}")


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
