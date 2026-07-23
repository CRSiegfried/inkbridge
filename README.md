# inkbridge

A control plane for the [Supernote Manta](https://supernote.com/pages/manta) e-ink
tablet: push documents to the device, pull handwritten annotations back, and —
the one thing Supernote's own software still can't do — chain a PDF together
with a notes page into a single document.

The long-term goal is to treat the Manta as an I/O peripheral for AI agents:
an agent drafts or fetches a document, `inkbridge` pushes it to the device,
you annotate it by hand, and `inkbridge` pulls the annotated result back for
the agent to read (OCR/VLM transcription, diagrams, math, the works).

## Why this exists

The Supernote community has already built solid pieces of this — a `.note`
parser, unofficial Cloud API clients, even an MCP server for LLM access to
notes. Nobody has wired them into one coherent push/pull/merge control plane,
and nobody has solved PDF+notes merging. `inkbridge` is an orchestration layer,
not a from-scratch reimplementation: it wraps existing libraries for parsing
and transport (chiefly [`supernotelib`](https://github.com/jya-dev/supernote-tool))
and adds the missing merge/chain logic and an agent-facing interface on top.

```
            ┌─────────────┐
   agent /  │  inkbridge  │   push()  ──────────▶  Supernote Manta
   human  ─▶│     CLI     │   pull()  ◀──────────  (Cloud sync /
            │  (+ future  │   merge()               Browse & Access /
            │  MCP server)│                         USB)
            └─────────────┘
```

## Status

Working against a real device today: `compose`, `dispatch`, `status`,
`collect`, and `proof` form an end-to-end round-trip — render a Markdown
document to a tickable PDF, send it to the tablet, detect which boxes were
marked by hand, and read the answers back. `composite` reconstructs the
combined page — decoded `.pdf.mark` ink overlaid on the rendered base page —
into a single image host-side, the capture render handed to a VLM. `merge`
(PDF chaining) works standalone. `.note`-to-PDF conversion is still a stub;
the private-cloud transport is the supported path. A second backend implements
the `Transport` protocol (`transport/base.py`) and is validated by the
conformance suite — the official Supernote Cloud backend is future work.

Contributions and Manta owners willing to test the device-facing commands are
welcome.

## Install (dev)

```bash
pip install -e ".[dev]"
inkbridge --help
```

## Using it

The local-only commands need nothing but the package:

```bash
# Render Markdown to a tickable PDF (dense layout is the device-validated default)
inkbridge compose notes.md --output notes.pdf

# Chain a PDF together with a notes page
inkbridge merge base.pdf addition.pdf --output combined.pdf

# Overlay pulled-back ink onto the base page — one image for a VLM to read
inkbridge composite notes.pdf notes.pdf.mark -o capture.png
```

The device-facing commands (`push`, `pull`, `dispatch`, `status`, `collect`)
talk to a Supernote private-cloud deployment and read credentials from the
environment:

```bash
export INKBRIDGE_CLOUD_URL="https://your-private-cloud.example.com"
export INKBRIDGE_CLOUD_EMAIL="you@example.com"
export INKBRIDGE_CLOUD_PASSWORD="…"

inkbridge doctor                          # verify config, connectivity, and login
inkbridge compose notes.md -o notes.pdf   # emits notes.pdf + notes.manifest.json
inkbridge dispatch notes.pdf              # push, recording it in the ledger
inkbridge status                          # which dispatched docs have new marks
inkbridge collect <doc-id>                # pull the annotated result back
```

`inkbridge doctor` is the quickest way to confirm the credentials work: it
logs in and lists the root, exiting `0` when ready, `5` on a bad/expired
credential, `6` when unconfigured or the cloud is unreachable.

The three credentials may also live in a `./.env` file instead of the
environment. Run `inkbridge <command> --help` for the full flag set on any
command.

## License

MIT — see [`LICENSE`](LICENSE). Note that one adjacent tool in the ecosystem
(`sn2md`) is AGPL-3.0; `inkbridge` only ever shells out to it as an external
CLI, never imports it as a library, to keep this project's license clean.
