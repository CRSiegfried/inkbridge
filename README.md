# inkbridge

A control plane for the [Supernote Manta](https://supernote.com/pages/manta) e-ink
tablet: push documents to the device, pull handwritten annotations back, and
chain PDFs together into a single document.

The long-term goal is to treat the Manta as an I/O peripheral for AI agents:
an agent drafts or fetches a document, `inkbridge` pushes it to the device,
you annotate it by hand, and `inkbridge` pulls the annotated result back and
composites it into a VLM-ready image for the agent to read. Transcription
itself — OCR/VLM turning ink into text — is the calling agent's job, not
`inkbridge`'s (see [ADR-0011](docs/adr/0011-transcription-out-of-scope.md)):
`inkbridge` hands off a clean artifact and stops there.

## Why this exists

The Supernote community has already built solid pieces of this — a `.note`
parser, unofficial Cloud API clients, even an MCP server for LLM access to
notes. Nobody has wired them into one coherent push/pull/merge control plane.
`inkbridge` is an orchestration layer,
not a from-scratch reimplementation: it wraps existing libraries for parsing
and transport (chiefly [`supernotelib`](https://github.com/jya-dev/supernote-tool))
and adds the missing merge/chain logic and an agent-facing interface on top.

```
            ┌─────────────┐
   agent /  │  inkbridge  │   push()  ──────────▶  Supernote Manta
   human  ─▶│  CLI + MCP  │   pull()  ◀──────────  (Cloud sync /
            │    server   │   merge()               Browse & Access /
            │             │                         USB)
            └─────────────┘
```

## Status

Working against a real device today: `compose`, `dispatch`, `status`,
`collect`, and `proof` form an end-to-end round-trip — render a Markdown
document to a tickable PDF, send it to the tablet, detect which boxes were
marked by hand, and read the answers back. `composite` reconstructs the
combined page — decoded `.pdf.mark` ink overlaid on the rendered base page —
into a single image host-side, the capture render handed to a VLM. `merge`
(PDF chaining) works standalone. The private-cloud transport is the supported
path. The `Transport` protocol
(`transport/base.py`) plus its conformance suite are the seam a second backend
implements against — the official Supernote Cloud backend is future work.

Contributions and Manta owners willing to test the device-facing commands are
welcome — open a GitHub issue to discuss a change, or send a pull request
directly.

## Install

Not on PyPI yet — install straight from the repo. For a CLI tool, `pipx`
(or `uv tool`) keeps it in its own isolated environment:

```bash
pipx install git+https://github.com/CRSiegfried/inkbridge
inkbridge --help
```

Working on inkbridge itself? Clone and install editable with the dev extras:

```bash
pip install -e ".[dev]"
```

## Using it

The local-only commands need nothing but the package:

```bash
# Render Markdown to a tickable PDF (dense layout is the device-validated default)
inkbridge compose notes.md --output notes.pdf

# Chain two PDFs into a single document
inkbridge merge base.pdf addition.pdf --output combined.pdf

# Overlay pulled-back ink onto the base page — one image for a VLM to read
inkbridge composite notes.pdf notes.pdf.mark -o capture.png
```

See `examples/` for sampler Markdown documents (`sampler_form.md`,
`sampler_typography.md`) exercising every input primitive the compose
renderer supports. Render them with `inkbridge compose` to inspect the
generated PDF and manifest output.

The device-facing commands (`push`, `pull`, `dispatch`, `status`, `collect`,
`ls`, `rm`, `wait`, `reconcile`) talk to a Supernote private-cloud deployment
and read credentials from the environment:

```bash
export INKBRIDGE_CLOUD_URL="https://your-private-cloud.example.com"
export INKBRIDGE_CLOUD_EMAIL="you@example.com"
export INKBRIDGE_CLOUD_PASSWORD="…"

inkbridge doctor                          # verify config, connectivity, and login
inkbridge compose notes.md -o notes.pdf   # emits notes.pdf + notes.manifest.json
inkbridge dispatch notes.pdf              # push, recording it in the ledger
inkbridge status                          # which dispatched docs have new marks
inkbridge collect <doc-id>                # pull the annotated result back,
                                           # writing a <doc>.answers.json sidecar

# Re-read the pulled response at any time, without touching ledger or remote:
inkbridge readback notes.manifest.json notes.pdf.mark   # per-cell blank/ANSWERED/AMBIGUOUS
inkbridge answers  notes.manifest.json notes.pdf.mark   # resolved, question-by-question
```

That five-step chain — `compose` → `dispatch` → (you ink the device) →
`collect` → `readback`/`answers` — is the full round trip: render a
question, hand it to the device, and get a structured answer back out.
`readback` reports the raw per-cell decode; `answers` resolves the same
read into semantic, question-level results (a winning choice, a checkbox
boolean, or `needs_review` for a cell to inspect with `composite`).

`inkbridge doctor` is the quickest way to confirm the credentials work: it
logs in and lists the root, exiting `0` when ready, `5` on a bad/expired
credential, `6` when unconfigured or the cloud is unreachable.

The three credentials may also live in a `./.env` file instead of the
environment. Run `inkbridge <command> --help` for the full flag set on any
command.

A few utility verbs round out the private-cloud side: `inkbridge ls
[folder]` lists a folder's contents (the root if omitted); `inkbridge wait
<doc-id>` blocks until a dispatched document's response arrives, as an
alternative to polling `status`; `inkbridge reconcile <remote-path>` adopts
an orphaned remote file — one pushed out of band, or left behind by a
dispatch that crashed after the push — back into the ledger so `status` and
`collect` can track it again; and `inkbridge rm <remote-path>...`
**permanently deletes** files from the private cloud (no undo), refusing to
run without confirmation — pass `-y`/`--yes` to confirm non-interactively
(required under `--json` or a non-TTY stdin).

`docs/reference/cli.md` is the complete command reference, including every
flag, the `--json` output contract for each command, and the exit-code
taxonomy agents can branch on.

An MCP server (`inkbridge-mcp`, installed with the optional `mcp` extra)
exposes the same compose → dispatch → wait → collect loop as tools for an
MCP-capable agent — see `docs/how-to/run-the-mcp-server.md`.

## License

MIT — see [`LICENSE`](LICENSE).
The package also bundles the Bitstream Vera Mono font used by `compose`,
under its own permissive license — see
[`src/inkbridge/compose/fonts/VERA-COPYRIGHT.TXT`](src/inkbridge/compose/fonts/VERA-COPYRIGHT.TXT).
