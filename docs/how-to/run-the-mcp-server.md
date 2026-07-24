# How to run the MCP server and drive the loop from an agent

Last updated: 2026-07-23. Expose the full round-trip — compose → dispatch →
status/wait → collect → composite — to an MCP client (Claude Desktop, Claude
Code, or any MCP-capable agent) as seven tools, so an agent drives the device
loop directly instead of shelling out to the CLI.

The server is a thin stdio front-end over the in-process operations layer
([ADR-0006](../adr/0006-in-process-operations-layer.md)) and the transport seam
([ADR-0007](../adr/0007-transport-protocol-seam.md)): every tool returns the
same versioned `*.v1` payload the CLI emits under `--json`, and credentials
resolve exactly as the CLI's do — nothing device-specific lives in the tool
arguments. It runs as a subprocess of the agent and exchanges filesystem paths,
so agent and server must share a filesystem.

Prerequisites: private-cloud credentials in the environment, `./.env`, or a
named profile (see the [CLI reference](../reference/cli.md#configuration)), and
the device pointed at that server and syncing. This guide assumes you already
know the loop from the CLI side — read
the CLI how-to on dispatching a form and collecting the handwritten response (not in the public docs)
first; the tools mirror those verbs one-to-one.

## 1. Install with the `mcp` extra

The MCP SDK is an optional dependency, so the base install stays lean:

```bash
pip install -e '.[mcp]'      # or: uv pip install -e '.[mcp]'
```

This adds the `inkbridge-mcp` console script (entry point
`inkbridge.mcp:main`). Confirm it's on your PATH with `--help` (prints usage
and exits); run it with no arguments and it speaks the MCP protocol on stdio,
sitting until a client connects (Ctrl-C to exit):

```bash
inkbridge-mcp --help
```

## 2. Register it with your client

Point the client at the `inkbridge-mcp` command. A generic MCP client config
(`.mcp.json`, Claude Desktop's `claude_desktop_config.json`, etc.) looks like:

```json
{
  "mcpServers": {
    "inkbridge": {
      "command": "inkbridge-mcp",
      "args": ["--profile", "manta"]
    }
  }
}
```

`--profile` selects a named profile from `~/.config/inkbridge/config.toml`
([ADR-0010](../adr/0010-named-profile-config.md)); omit it to use
`$INKBRIDGE_PROFILE`, or the single-account env / `.env` credentials when no
profile is set. A `--ledger` flag overrides the ledger path
(else `$INKBRIDGE_LEDGER` or the profile's per-profile default). **Credentials
are never tool arguments** — keep them in the profile, the environment, or
`.env`.

Your actual client config carries machine-specific paths and profile names, so
it belongs in `deploy/local/`, never in the tracked tree — this snippet is the
publishable template.

## 3. The seven tools

| Tool | What it does | Key arguments |
| --- | --- | --- |
| `compose` | Render an authored doc to a tickable PDF + manifest. | exactly one of `source_markdown` (Markdown) **or** `blocks` (block-IR — [ADR-0009](../adr/0009-cell-type-registry-and-block-ir.md)); `output_pdf`; `density` (default `dense`) or exact `scale` |
| `dispatch` | Push the PDF and track it as awaiting a response. | `file`, `manifest_path`; `replace` **defaults true** |
| `reconcile` | Adopt an orphaned remote doc (on the cloud, not in the ledger) back into tracking, without re-uploading. | `folder`, `name`, `manifest_path` |
| `status` | Poll every tracked doc for landed ink. | `acknowledge` (default false) |
| `wait_for_response` | Bounded long-poll until one doc's mark lands. | `doc_id`, `timeout_s` (clamped to 120 s) |
| `collect` | Pull the `.mark`, resolve answers, write the sidecar. | `doc_id`, `output_dir` (required) |
| `composite_page` | Overlay ink on the base page, returned **inline as a PNG**. | `base_pdf`, `mark_path`, `page_number` (1-indexed) |

Two differences from the CLI worth knowing:

- **`dispatch` is idempotent by default** (`replace=true`): re-dispatching a
  doc under the same name deletes the remote copy first rather than failing on
  the cloud's no-overwrite, so an autonomous caller can retry safely. Pass
  `replace=false` to get the CLI's strict behavior. This is the one deliberate
  default change from the CLI, where `--replace` is opt-in.
- **`composite_page` returns the annotated page as an image content block**, so
  a vision-capable model reads the freehand ink, diagrams, and math directly —
  no separate upload step. It also saves the PNG (`output_png` or
  `<base>.p<N>.composite.png`) and reports the path.

The typical agent loop: `compose` (feed the returned `pdf`/`manifest` paths to
`dispatch`) → `wait_for_response` (or poll `status`) → `collect` → read the
resolved answers, and `composite_page` for any capture field or ambiguous mark
that needs *meaning* rather than presence.

`reconcile` is the off-path recovery verb: if the ledger and the cloud drift
apart — a `dispatch` that pushed but died before saving, a doc pushed out of
band, or a rebuilt ledger — it re-attaches tracking to a doc already on the
device *without* re-uploading, so any ink already on it survives (re-dispatching
with `replace=true` would delete the remote copy first). An agent recovering a
dropped doc uses it instead of escalating to the CLI.

A read-only resource, `inkbridge://ledger`, exposes the ledger JSON so a client
can inspect outstanding docs without a tool call.

## 4. Results and errors

Each JSON tool returns its `*.v1` body both as text and as MCP structured
content, so a client gets a parsed object without re-parsing text — the same
contract the [CLI reference](../reference/cli.md) documents per command.

Typed failures surface as tool errors whose message is prefixed with the CLI's
machine `code` — `[unknown_doc]`, `[no_manifest]`, `[no_response]`,
`[already_tracked]`, `[timeout]`, `[auth]`, `[not_found]`, `[already_exists]`,
`[unreachable]`, `[sparse_mark]`, `[ledger_corrupt]`, `[invalid_source]` — so
an agent branches on
the same tokens
the CLI maps to exit codes ([ADR-0002](../adr/0002-agent-facing-cli-contract.md)).
For example, `collect` on a doc with no ink yet errors `[no_response]` (loop and
retry), and on an unknown doc `[unknown_doc]`.

## Troubleshooting

- **Client shows no tools / server exits immediately** — the base install
  lacks the SDK: `inkbridge-mcp` prints a one-line "the 'mcp' package is not
  installed; run: pip install 'inkbridge[mcp]'" message on stderr and exits
  `2` (never a raw `ModuleNotFoundError` traceback). Reinstall with `.[mcp]`
  (step 1).
- **`[auth]` on the first cloud tool** — credentials rejected. Check the
  profile/env the server resolves; the transport logs in lazily, so this only
  appears once a tool actually reaches the cloud.
- **`[unreachable]`** — the cloud is down or unresolvable (DNS, connect,
  timeout); the same PRECONDITION-class signal the CLI gives.
- **`wait_for_response` returns `[timeout]` fast** — `timeout_s` is capped at
  120 s so a client's own tool timeout doesn't fire first; loop `status` or call
  it again for longer waits.
- **`composite_page` errors on the page number** — it is 1-indexed and the base
  PDF must be the compose-rendered sheet (same device canvas) the mark was
  captured against.
- Cloud-side listing quirks (`folder not found`, `E0322`, `E0321`, device sync
  lag) behave exactly as in
  the dispatch-and-collect how-to (not in the public docs).
