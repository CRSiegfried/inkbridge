# Roadmap

Rough build phases. Each phase should be validated against a real Manta
before moving on — none of this is worth building against assumptions about
device behavior.

## Phase 0 — Scaffold (done)

Repo structure, ecosystem survey, architecture doc, packaging.

## Phase 1 — Read path

- Wire up `supernotelib` for `.note` → PDF/PNG/text conversion.
- Wire up `sncloud` (or `supernote-cli`) to list and download notebooks from
  Supernote Cloud.
- `inkbridge pull <notebook> -o out.pdf` working end-to-end against a real
  device/account.

## Phase 2 — Write path

- Push a PDF to the device as a new notebook via Cloud upload.
- `inkbridge push <file.pdf> --to <folder>` working end-to-end.
- Evaluate whether Browse & Access (local WiFi, no cloud round-trip) is worth
  reverse-engineering as a second transport backend.

## Phase 3 — PDF↔notes merge/chain

- The originally-missing feature: append a notes page (or a whole notebook)
  to an existing PDF, or vice versa.
- Start with the PDF-intermediate approach (flatten notes → PDF, merge PDFs
  with `pypdf`) since it needs no new format-writing code.
- `inkbridge merge base.pdf notes.note -o combined.pdf`.

## Phase 4 — Agent-facing surface

- Decide: own MCP server, or extend `allenporter/supernote`'s existing one.
- Close the full loop described in
  [`architecture.md`](architecture.md#the-agent-loop-target-end-state):
  agent pushes → human annotates → agent pulls and reads back.
- OCR/VLM transcription of annotations (likely via `sn2md` as a subprocess —
  see [licensing notes](ecosystem.md#licensing-notes)).

## Non-goals (for now)

- Reimplementing `.note` parsing from scratch — use `supernotelib`.
- A GUI — this is a CLI/agent tool first.
- Supporting non-Manta Supernote devices — revisit if the transport/format
  layers turn out to be shared across models anyway.
