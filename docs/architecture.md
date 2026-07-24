# Architecture

## Design principle

`inkbridge` is a thin orchestration layer over existing, permissively-licensed
Supernote libraries (see [`ecosystem.md`](ecosystem.md)). It should contain as
little device-protocol or `.note`-parsing code as possible — that work is
already done and maintained upstream. What it owns is:

1. A unified interface (`push` / `pull` / `merge`) over transports that
   currently only exist as separate, incompatible tools.
2. The PDF↔notes merge/chain logic, which doesn't exist anywhere yet.
3. An agent-facing surface (a CLI and an MCP server) so an LLM agent can
   drive the whole loop without a human operating multiple CLIs by hand.
4. Low-latency, targeted reads of a notebook — checking a specific
   page/region rather than paying for a full conversion every time. See
   `note-format.md` (local archive, unpublished).

## Components

```
src/inkbridge/
  transport/         # push/pull — the `Transport` protocol seam (base.py)
                     # with private-cloud and local-folder backends,
                     # transport-neutral errors
  convert/           # .note/.mark decode — wraps supernotelib
                     #   notebook.py  — full-document conversion (stub seam)
                     #   targeted.py  — cheap single-page/region reads
  compose/           # Markdown / block-IR -> tickable PDF + input manifest
  readback.py        # per-cell decode of a pulled .pdf.mark
  answers.py         # question-level resolution over the readback
  merge.py           # PDF + notes chaining — the new capability
  ops.py             # in-process operations layer the CLI and MCP share
  cli.py             # `inkbridge push|pull|dispatch|collect|...`
  mcp.py             # agent-facing stdio MCP server (`inkbridge-mcp`)
```

## Transport backend selection

Three ways to get a file on/off the device exist, in order of preference:

1. **Supernote Cloud** (via `sncloud` or `supernote-cli`) — works over the
   internet, no physical proximity needed, but requires the device to have
   cloud sync enabled and the account credentials configured.
2. **Browse & Access** (device-hosted WiFi HTTP server) — works on the local
   network without cloud round-trips. No *official* API, but it's already
   reverse-engineered: a working client
   ([`jbchouinard/supernote-sync`](https://github.com/jbchouinard/supernote-sync),
   see [`ecosystem.md`](ecosystem.md#cloud--transport)) drives it on port
   8089 with a directory listing carrying per-file mtime + size. The open
   work is validating/adopting that client against a real device, not
   reverse-engineering from scratch — see
   Analysis 0001 (unpublished) finding 5.
3. **USB mass-storage/MTP** — always available, no network needed, but
   requires physical connection and is the least "agentic" (no remote push).

`transport/` should expose one interface with pluggable backends, not force a
choice up front — a household running `inkbridge` unattended for an agent
loop will likely want Cloud; a one-off local job may prefer USB.

A fourth option is under active investigation: **self-hosted Private Cloud**
— Ratta ships an official beta that lets the device sync to a server you run
instead of Ratta's hosted cloud, speaking the same protocol (so the Cloud
change-detection design carries over) and hostable behind any
reverse proxy or tunnel. It's not yet a decided backend, but it materially
reshapes the Cloud-vs-local trade-off. See
Analysis 0007 (unpublished).

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

**Note (annotated PDFs).** The step-4 comment above assumes a `.note` comes
back, which holds when the human writes in a native notebook. But if what
was pushed in step 2 is a **PDF**, step 4 retrieves the original `.pdf`
plus a separate `.pdf.mark` sidecar (the handwriting) — the device stores
PDF annotations alongside the unmodified PDF rather than converting it to a
notebook. Reunifying them is a compositing step, not `note_to_pdf`. See
Analysis 0003 (unpublished) finding 5; the
mechanics of that compositing are an open, not-yet-started investigation
(see the research-state MoC linked under Open design questions).

## Targeted reads: cheap polling for the agent loop

Step 4-6 of the agent loop above (`pull` → `convert --ocr` → agent reads
transcription) is fine for "give me the full transcription of what changed,"
but it's the wrong tool for a narrower, very common case: the agent just
wants to know whether the user marked a specific checkbox on a specific
page — e.g. "approve? `[ ]`" on a form the agent pushed earlier. Running a
full notebook conversion plus an OCR/VLM call to answer a yes/no question is
needless latency and cost, and it doesn't scale to polling.

The `.note` format's own structure supports doing much better — see
`note-format.md` (local archive, unpublished)
for the detail. In short: `supernotelib` already exposes single-page decode
(`convert(page_number)`) separately from whole-notebook conversion, and
metadata (page count, keywords, links) appears cheap to read independent of
stroke/ink decoding. That supports a `convert/targeted.py` primitive —
"was region R on page N marked" — sitting alongside the full
`convert/notebook.py` pipeline, for the agent loop to poll cheaply instead
of re-running full transcription every time.

This is a Phase 1.5-ish concern: it doesn't block the initial read/write
path (Phase 1/2 in `roadmap.md` (local archive, unpublished)), but `convert/notebook.py`'s
API should leave room for per-page/region access as a first-class citizen
so it isn't a painful retrofit once the agent loop (Phase 4) needs it.

## Open design questions

- Should `merge` operate on the `.note` file directly (insert PDF pages as
  background layers under a notebook) or always go through a PDF
  intermediate (flatten notes to PDF, then merge PDFs)? The latter is
  simpler and reuses `supernotelib`'s existing PDF export; the former
  preserves editability on-device but requires understanding (and possibly
  writing to) the `.note` format, which no library currently does — all
  existing tools are read-only converters.
- ~~Build our own MCP server, or contribute agent-facing commands upstream to
  `allenporter/supernote`'s existing MCP server instead of duplicating it?~~
  Since decided: `inkbridge` ships its own tightly-scoped stdio MCP server as
  a thin front-end over the in-process operations layer — see
  [the MCP how-to](how-to/run-the-mcp-server.md).

The merge question is deliberately *not* decided yet — it isn't developed
enough to commit to an ADR. It, the still-open investigations behind it, and
the not-yet-started research threads (push/`.mark` reunification, going
around Ratta's cloud, security/trust, failure modes, polling economics) are
all tracked as a reviewable research program in
the research-state MoC (local archive, unpublished).
