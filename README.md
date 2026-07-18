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
and nobody has solved PDF+notes merging. See
[`docs/ecosystem.md`](docs/ecosystem.md) for the full survey of prior art and
what `inkbridge` builds on vs. what it adds.

## Architecture

`inkbridge` is an orchestration layer, not a from-scratch reimplementation.
It wraps existing libraries for parsing and transport, and adds the missing
merge/chain logic and an agent-facing interface on top. See
[`docs/architecture.md`](docs/architecture.md) for the full design and
[`docs/roadmap.md`](docs/roadmap.md) for build phases.

```
            ┌─────────────┐
   agent /  │  inkbridge  │   push()  ──────────▶  Supernote Manta
   human  ─▶│     CLI     │   pull()  ◀──────────  (Cloud sync /
            │  (+ future  │   merge()               Browse & Access /
            │  MCP server)│                         USB)
            └─────────────┘
```

## Status

Early scaffold — see [`docs/roadmap.md`](docs/roadmap.md). Not yet functional
against a real device. Contributions and Manta owners willing to test the
device-facing commands are welcome.

## Install (dev)

```bash
pip install -e ".[dev]"
inkbridge --help
```

## License

MIT — see [`LICENSE`](LICENSE). Note that one adjacent tool in the ecosystem
(`sn2md`) is AGPL-3.0; `inkbridge` only ever shells out to it as an external
CLI, never imports it as a library, to keep this project's license clean. See
[`docs/ecosystem.md`](docs/ecosystem.md#licensing-notes).
