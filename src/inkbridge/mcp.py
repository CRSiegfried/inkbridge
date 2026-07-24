"""MCP server (stdio): the agent round-trip loop as MCP tools.

This is the *second* front-end for the in-process operations layer
(:mod:`inkbridge.ops`) — the one its docstring anticipates ("the CLI now, the
MCP server later"). Each tool is a thin wrapper: parse args, call ``ops`` /
``compose`` / ``composite`` with the transport ``connect`` seam and a freshly
constructed :class:`~inkbridge.dispatch.Ledger` injected, and return the bare
payload dict the CLI wraps under ``--json``. It never reaches into
:mod:`inkbridge.cli`.

The exit-code taxonomy lives in the CLI, not in ``ops``; the MCP layer keeps
the stable ``code`` *strings* (the CLI maps those to numeric exits) by
re-raising every typed domain error as a :class:`ToolError` whose message is
``"[<code>] <detail>"`` — the same code strings ``cli.py`` uses.

Credentials never appear in tool arguments: the transport resolves them exactly
as the CLI does (env / ``.env`` / a named profile), selected by ``--profile``
on the server command or ``$INKBRIDGE_PROFILE``. Tools exchange filesystem
paths, which is correct for a stdio server co-located with the agent.
"""

from __future__ import annotations

import io
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP, Image
from mcp.server.fastmcp.exceptions import ToolError

from inkbridge import ops, transport
from inkbridge.dispatch import Ledger
from inkbridge.readback import SparseMarkError
from inkbridge.transport import AuthError

server = FastMCP("inkbridge")

# Longest window a single wait_for_response call polls before returning; MCP
# clients time out long tool calls, so an agent loops status/short waits past
# this rather than blocking one call for minutes.
WAIT_CAP_S = 120.0

# Server-wide config, set once by main() from the command line. Tools resolve
# the transport lazily through _connect so a precondition failure never logs in.
_PROFILE: str | None = None
_LEDGER_PATH: str | None = None


def _connect():
    """The zero-arg connector ops invokes lazily (mirrors how the CLI passes
    ``transport.connect``). Tests monkeypatch this to inject a fake client."""
    return transport.connect(_PROFILE)


def _ledger(ledger_path: str | None = None) -> Ledger:
    """Construct the ledger the CLI's ``--ledger`` option would: an explicit
    per-tool path wins, else the server default, else the profile/state
    default (:func:`inkbridge.dispatch.default_ledger_path`)."""
    path = ledger_path or _LEDGER_PATH
    return Ledger(Path(path)) if path else Ledger()


# Typed domain error -> the agent-facing code string, in match order (subclasses
# first). Reproduces the mapping cli.py performs via its per-command handlers and
# the _cloud_errors/_mark_errors context managers.
_ERROR_CODES: list[tuple[type[BaseException], str]] = [
    (ops.UnknownDocError, "unknown_doc"),
    (ops.NoManifestError, "no_manifest"),
    (ops.NoResponseError, "no_response"),
    (ops.AlreadyTrackedError, "already_tracked"),
    (ops.WaitTimeout, "timeout"),
    (SparseMarkError, "sparse_mark"),
    (AuthError, "auth"),
    (FileExistsError, "already_exists"),
    (FileNotFoundError, "not_found"),
    (httpx.RequestError, "unreachable"),
]


@contextmanager
def _tool_errors():
    """Map the typed exceptions ops (and the transport/decode paths) raise to a
    ToolError carrying the CLI's ``code`` string, so an agent branches on a
    stable token instead of a bare traceback."""
    try:
        yield
    except ToolError:
        raise
    except BaseException as e:  # noqa: BLE001 — re-raised below, mapped or not
        for exc_type, code in _ERROR_CODES:
            if isinstance(e, exc_type):
                raise ToolError(f"[{code}] {e}") from e
        raise


@server.tool()
def compose(
    output_pdf: str,
    source_markdown: str | None = None,
    blocks: list[dict] | None = None,
    manifest_path: str | None = None,
    doc_id: str | None = None,
    device: str = "manta",
    density: str = "dense",
    scale: float | None = None,
) -> dict[str, Any]:
    """Render an authored document to a device-ready tickable PDF + input-cell
    manifest. Provide exactly one of ``source_markdown`` (Markdown text) or
    ``blocks`` (block-IR: a list of ``{"kind": ..., ...}`` dicts an agent emits
    directly). ``density`` is a named preset (normal/compact/dense); ``scale``
    overrides it with an exact factor. Returns the compose.v1 body: doc_id, the
    ``pdf``/``manifest`` paths (feed them to ``dispatch``), page count, and cell
    count."""
    from inkbridge.compose import DENSITIES
    from inkbridge.compose import compose as compose_markdown
    from inkbridge.compose import compose_from_ir

    if (source_markdown is None) == (blocks is None):
        raise ToolError(
            "[invalid_source] provide exactly one of source_markdown or blocks")
    if scale is None:
        try:
            scale = DENSITIES[density]
        except KeyError:
            raise ToolError(
                f"[invalid_source] unknown density {density!r}; "
                f"known: {', '.join(DENSITIES)}") from None

    out = Path(output_pdf)
    mpath = Path(manifest_path) if manifest_path else None
    try:
        if blocks is not None:
            result = compose_from_ir(blocks, out, mpath, doc_id,
                                     device=device, scale=scale)
        else:
            result = compose_markdown(source_markdown, out, mpath, doc_id,
                                      device=device, scale=scale)
    except (ValueError, KeyError) as e:
        raise ToolError(f"[invalid_source] {e}") from e

    return {
        "doc_id": result.doc_id,
        "pdf": str(result.pdf_path),
        "manifest": str(result.manifest_path),
        "pages": result.pages,
        "cells": len(result.cells),
        "device": device,
        "scale": scale,
    }


@server.tool()
def dispatch(
    file: str,
    manifest_path: str | None = None,
    remote_folder: str = "Document",
    replace: bool = True,
    ledger_path: str | None = None,
) -> dict[str, Any]:
    """Push a composed PDF to the tablet and record it in the ledger as awaiting
    a response. ``replace`` defaults true (idempotent): the remote name is
    deleted before the push, so re-dispatching a doc leaves exactly one remote
    copy instead of failing on the cloud's no-overwrite. Returns the dispatch.v1
    body."""
    ledger = _ledger(ledger_path)
    with _tool_errors():
        return ops.dispatch(
            _connect, ledger, Path(file),
            remote_folder=remote_folder,
            manifest_path=manifest_path, replace=replace)


@server.tool()
def status(acknowledge: bool = False, ledger_path: str | None = None) -> dict[str, Any]:
    """Poll the cloud for every tracked doc and return one row each
    (doc_id/remote/state/mark_md5/base_changed). ``acknowledge`` marks
    responded/changed docs as seen and persists the ledger. Returns the
    status.v1 body ({ledger, entries})."""
    ledger = _ledger(ledger_path)
    with _tool_errors():
        rows = ops.status(_connect, ledger, acknowledge=acknowledge)
    return {"ledger": str(ledger.path), "entries": rows}


@server.tool()
def wait_for_response(
    doc_id: str,
    timeout_s: float = 60.0,
    ledger_path: str | None = None,
) -> dict[str, Any]:
    """Bounded long-poll until ``doc_id``'s mark arrives — the synchronizing
    verb of the loop. ``timeout_s`` is clamped to %.0f s (loop status/short
    waits for longer). Returns the wait.v1 status row on arrival; errors with
    code ``timeout`` if none lands in the window.""" % WAIT_CAP_S
    ledger = _ledger(ledger_path)
    timeout = min(timeout_s, WAIT_CAP_S)
    with _tool_errors():
        return ops.wait(_connect, ledger, doc_id, timeout=timeout)


@server.tool()
def collect(doc_id: str, output_dir: str, ledger_path: str | None = None) -> dict[str, Any]:
    """Pull ``doc_id``'s ``.pdf.mark``, resolve the ink against its compose
    manifest, and write the ``<doc>.answers.json`` sidecar under ``output_dir``.
    Returns the collect.v1 body (resolved ``answers`` + ``answers_file``). Does
    not mutate the ledger."""
    ledger = _ledger(ledger_path)
    with _tool_errors():
        return ops.collect(_connect, ledger, doc_id, output_dir=Path(output_dir))


@server.tool(structured_output=False)
def composite_page(
    base_pdf: str,
    mark_path: str,
    page_number: int,
    output_png: str | None = None,
):
    """Render the annotated page — decoded ink overlaid on the base PDF page —
    and return it inline as a PNG so the calling model reads freehand
    annotations, diagrams, and math directly. ``page_number`` is 1-indexed. Also
    saves the PNG (``output_png`` or ``<base>.p<N>.composite.png``) and reports
    the path."""
    from inkbridge.composite import composite_page as _composite

    with _tool_errors():
        img = _composite(Path(base_pdf), Path(mark_path), page_number)

    out = Path(output_png) if output_png else Path(
        base_pdf).with_suffix(f".p{page_number}.composite.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, format="PNG")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return [Image(data=buf.getvalue(), format="png"),
            f"composite saved to {out}"]


@server.resource("inkbridge://ledger")
def ledger_resource() -> str:
    """The active ledger as JSON — outstanding docs and their remote/mark state,
    read-only, for a client that wants to inspect without a tool call."""
    ledger = _ledger()
    return json.dumps({"ledger": str(ledger.path), "entries": ledger.entries},
                      indent=2)


def main() -> None:
    """Console entry point (``inkbridge-mcp``): run the stdio server."""
    import argparse

    global _PROFILE, _LEDGER_PATH
    parser = argparse.ArgumentParser(
        prog="inkbridge-mcp",
        description="inkbridge MCP server (stdio): compose/dispatch/status/"
                    "wait/collect/composite the agent round-trip loop.")
    parser.add_argument(
        "--profile", default=None,
        help="Named transport profile (else $INKBRIDGE_PROFILE, else the "
             "single-account env/.env credentials).")
    parser.add_argument(
        "--ledger", default=None,
        help="Ledger path override (else $INKBRIDGE_LEDGER / the profile "
             "default). A tool's own ledger_path argument still wins.")
    args = parser.parse_args()
    _PROFILE = args.profile
    _LEDGER_PATH = args.ledger
    server.run()  # stdio transport (the default)


if __name__ == "__main__":
    main()
