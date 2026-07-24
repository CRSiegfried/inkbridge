# ADR-0009: A cell-type registry and a block-IR compose entry point

Status: Accepted
Date: 2026-07-23

## Context

[Remediation item G3](../remediation-plan.md) targets compose's closed
vocabulary. The four input directives (`choice`/`ack`/`comb`/`capture`) are a
bespoke `{kind: …}` micro-syntax parsed in `compose/parser.py`; `render.render`
dispatches them with a hardcoded `isinstance` chain, and `answers` resolves them
by string (a `_BOOLEAN_TYPES` set plus a presence fallback). Adding a cell type
means editing all three. And `compose()` accepts **Markdown text only** — but an
agent (the primary consumer) would rather emit a structured block IR / JSON than
author Markdown and hope the parser round-trips its intent.

`readback` is already type-agnostic: it measures per-cell ink coverage and
decides blank/ambiguous/answered with no per-type code, so a new type needs no
readback change. The coupling that blocks extension is on the two ends — render
(draw the cell, stamp the manifest) and answers (resolve the reading to a value).

## Decision

We will add a **cell-type registry** that both ends consult for non-built-in
types, plus a **block-IR compose entry point**.

**`compose/celltypes.py`** holds `register(name, *, render, resolve)` and a
`REGISTRY` mapping a type name to a `CellType(render, resolve)`:

- `render(renderer, block)` draws the cell and stamps its manifest cell(s) via
  the renderer's primitives (e.g. `renderer._checkbox`).
- `resolve(cell_reading) -> Answer` turns one decoded cell into its answer.

A `CustomBlock(type, label, ir)` carries a registered type through the block
list.

**One-time seams, then zero core edits per type.** `render.render` gains a
single branch — an unrecognized/`CustomBlock` block dispatches to
`REGISTRY[type].render` — and `answers.resolve_answers` consults
`REGISTRY[type].resolve` for a cell whose type is registered, else the existing
built-in logic. Those two seam edits are made **once**; thereafter a new type is
one `register(...)` call plus an IR block, flowing compose→readback→answers with
no edit to render, answers, or readback. The five built-in types stay as they are
(hardcoded dispatch) — the registry is the extension path, not a rewrite of what
works.

**`compose_from_ir(blocks, output_pdf, …)`** is the agent-facing entry point: a
list of IR dicts (`{"kind": "choice", "label": …, "options": […]}`,
`{"kind": "checkbox", "label": …}`, a registered custom `{"kind": "<name>", …}`,
…) is converted to the same block objects the Markdown parser produces and run
through the identical `Renderer` + band-stamping, so IR and Markdown compose
share one rendering path and cannot drift. `compose()` (Markdown) stays; it is
now one front door of two.

## Consequences

- **Easier:** an agent composes from structured IR without authoring Markdown; a
  new cell type (multi-select, rating, per-line free text) is added out-of-core
  by registering a render+resolve pair. The IR and Markdown paths converge on one
  renderer.
- **Harder / given up:** two dispatch sites now have a registry branch to keep
  honest, and the registry is global mutable state (a registration leaks across a
  process) — acceptable for a CLI, a smell for a long-lived embedder, which
  should register once at import. The built-in types are deliberately *not*
  migrated onto the registry, so there are two dispatch styles (hardcoded core +
  registry extension) rather than one uniform table — a pragmatic trade to keep
  the change contained and the known-good path untouched.
- **IR is a second input contract.** `compose_from_ir`'s dict shape is now a
  surface consumers depend on, alongside the Markdown syntax.

## Alternatives considered

- **IR entry point + an answers-side resolver registry only** (render dispatch
  left as-is). Rejected at the design checkpoint: a new type could resolve but
  not *render* without a core edit, so it wouldn't flow compose→answers
  end-to-end — half the seam.
- **Migrate all built-in types onto the registry** for one uniform dispatch
  table. Rejected as scope creep: it rewrites the known-good render/answers paths
  for no functional gain over adding the extension seam; the built-ins can be
  folded in later if a second reason appears.
- **Replace the `{kind: …}` micro-syntax with a general markup** (or drop
  Markdown for IR entirely). Rejected: Markdown authoring stays useful for
  humans, and the IR entry point gives agents the structured path without a
  flag-day migration of the existing syntax.

## Related

- [Remediation plan](../remediation-plan.md) — item G3 (this ADR is its design),
  and G4 (the explicit choice `group` id the IR path also carries).
- [ADR-0008](0008-per-cell-decision-bands.md) — the per-cell bands the IR path
  stamps through the same `_stamp_decision_bands` step.
