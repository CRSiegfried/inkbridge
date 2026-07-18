# Architecture

## Design principle

`inkbridge` is a thin orchestration layer over existing, permissively-licensed
Supernote libraries (see [`ecosystem.md`](ecosystem.md)). It should contain as
little device-protocol or `.note`-parsing code as possible — that work is
already done and maintained upstream. What it owns is:

1. A unified interface (`push` / `pull` / `merge`) over transports that
   currently only exist as separate, incompatible tools.
2. The PDF↔notes merge/chain logic, which doesn't exist anywhere yet.
3. An agent-facing surface (CLI now, MCP later) so an LLM agent can drive the
   whole loop without a human operating multiple CLIs by hand.

## Components

```
src/inkbridge/
  transport/        # push/pull to the device — wraps sncloud / supernote-cli
                     # / Browse & Access, picks a backend, normalizes errors
  convert/           # .note <-> PDF/PNG/text — wraps supernotelib
  merge.py           # PDF + notes chaining — the new capability
  cli.py             # `inkbridge push|pull|merge|...`
  mcp/               # agent-facing MCP server (phase 4) — evaluate building
                      # on allenporter/supernote's existing MCP server before
                      # writing a new one from scratch
```

## Transport backend selection

Three ways to get a file on/off the device exist, in order of preference:

1. **Supernote Cloud** (via `sncloud` or `supernote-cli`) — works over the
   internet, no physical proximity needed, but requires the device to have
   cloud sync enabled and the account credentials configured.
2. **Browse & Access** (device-hosted WiFi HTTP server) — works on the local
   network without cloud round-trips, but has no documented API; needs
   reverse engineering (packet capture against a real device) before
   `inkbridge` can drive it programmatically.
3. **USB mass-storage/MTP** — always available, no network needed, but
   requires physical connection and is the least "agentic" (no remote push).

`transport/` should expose one interface with pluggable backends, not force a
choice up front — a household running `inkbridge` unattended for an agent
loop will likely want Cloud; a one-off local job may prefer USB.

## The agent loop (target end state)

```
1. Agent produces or fetches a PDF.
2. inkbridge push <file> --to notebook       # lands on the Manta
3. Human writes on the device.
4. inkbridge pull <notebook> --since <ts>    # retrieves the updated .note
5. inkbridge convert --ocr                    # .note -> text/markdown
6. Agent reads the transcription and acts on it.
```

Steps 1-2 and 4-6 are the parts worth automating first; step 3 is
irreducibly manual (that's the point of a pen-and-paper device). The
PDF+notes merge feature slots in between steps 1 and 2, or as a standalone
command (`inkbridge merge base.pdf notes.note -o combined.pdf`) for the
simpler non-agentic use case the user asked for directly.

## Open design questions

- Should `merge` operate on the `.note` file directly (insert PDF pages as
  background layers under a notebook) or always go through a PDF
  intermediate (flatten notes to PDF, then merge PDFs)? The latter is
  simpler and reuses `supernotelib`'s existing PDF export; the former
  preserves editability on-device but requires understanding (and possibly
  writing to) the `.note` format, which no library currently does — all
  existing tools are read-only converters.
- Build our own MCP server, or contribute agent-facing commands upstream to
  `allenporter/supernote`'s existing MCP server instead of duplicating it?
  Needs a closer read of that project before deciding.
