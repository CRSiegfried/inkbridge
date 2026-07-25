# ADR-0011: Semantic transcription is out of scope; the boundary ends at the composite handoff

Status: Accepted
Date: 2026-07-24

## Context

The documented target end state had inkbridge owning free-form semantic
transcription. `architecture.md`'s "agent loop (target end state)" listed a
step 5 — `inkbridge convert --ocr   # .note -> text/markdown` — as an inkbridge
command, and its "Targeted reads" section framed a "full notebook conversion
plus an OCR/VLM call" as inkbridge's own expensive path. `ecosystem.md`'s survey
went further and *recommended building it*, twice: "inkbridge is better served
by its own **provider-agnostic VLM call** on a `composite` crop, borrowing
supernote-cli's prompt as prior art." The README tagline's parenthetical
("OCR/VLM transcription, diagrams, math, the works") reads the same way.

None of that transcription was ever built — the trajectory was documented, not
implemented. Two facts make the trajectory the wrong one:

- **The design already splits two different "read the annotations" operations,
  and only one is an LLM surface.** Deterministic *targeted reads* — `proof` /
  `readback` / `answers`, "was region R on page N marked," per-cell decode over
  the byte-stable round trip ([ADR-0008](0008-per-cell-decision-bands.md) bands,
  [ADR-0003](0003-materialized-answers-artifact.md) answers artifact) — read the
  annotations with pure image processing, no model. Free-form *semantic
  transcription* (handwriting/math/diagram → text) is a separate, model-bound
  operation. `composite` already terminates at a VLM-ready crop ("the capture
  render sent to a VLM"); the model call lives one step past it and was never
  written.

- **inkbridge's consumer is itself a vision-capable model.** The agent-facing
  surface is reached over MCP by an agent that already has vision; the maintainer's
  own workflow hands the composite to that assistant to read. inkbridge making the
  VLM call would duplicate the caller's own capability — and would import a whole
  subsystem to do it: multi-provider config, API-key handling, response caching,
  token accounting — exactly what a comparable community tool (PySN-digest) carries,
  with per-model LLM config files and a hash-keyed response cache. It would also
  inject nondeterminism into a codebase whose contracts are
  shape-based and mock-tested end to end
  ([ADR-0007](0007-transport-protocol-seam.md)).

## Decision

We will scope **semantic transcription — any OCR/VLM/LLM inference that turns ink
into text/markdown — out of inkbridge entirely.** inkbridge's responsibility ends
at the **composite handoff**: it produces a VLM-ready artifact (the `composite`
crop, plus the structured mark/answer sidecars) and hands off; the model call
belongs to the caller (an MCP agent, the maintainer's assistant, Apple Vision,
any OCR backend).

Concretely:

- **The planned `convert --ocr` command is removed** from `architecture.md`'s
  agent-loop target end state. The loop's read step becomes caller-supplied
  transcription over the pulled/composited artifact — not an inkbridge command.
- **`ecosystem.md`'s "own provider-agnostic VLM call" recommendation is
  reversed.** supernote-cli's transcription prompt is prior art for *the caller*,
  not a thing inkbridge imports.
- **The README tagline is corrected** to state that transcription is the caller's
  job.

**In scope, unchanged:** deterministic targeted reads — `proof` / `readback` /
`answers`, per-cell blank/ANSWERED/AMBIGUOUS decode, "was region R on page N
marked." These read the annotations without a model and remain core. Rendering a
`.note`/`.pdf.mark` page to an image (`composite`, page render) is likewise in
scope — it is deterministic and is precisely the handoff artifact.

**Out of scope:** any inkbridge-owned OCR/VLM/LLM inference, provider selection,
API-key handling, or transcription caching.

**The seam is `composite`** (`composite.py`): it emits the VLM-ready crop;
downstream transcription consumes it. This ADR is the single source of truth for
the reversal — `architecture.md` and `ecosystem.md` are living docs and are
edited to match, but ADRs are immutable, so future drift points back here.

## Consequences

- **Easier:** the dependency and security surface stays small — no LLM SDKs, no
  key management, no prompt-injection exposure, no provider-churn maintenance. The
  shape-based conformance discipline ([ADR-0007](0007-transport-protocol-seam.md))
  holds — nothing in the tree has to mock a nondeterministic model. The `composite`
  output becomes a clean, backend-agnostic contract any transcriber (the caller's
  agent, Apple Vision, a cloud OCR) can consume. The lean-control-plane identity
  is preserved.
- **Harder / given up:** there is no batteries-included "push doc → get text back"
  story — a newcomer must wire their own transcription. inkbridge advertises a
  smaller surface than the ecosystem survey imagined, and we forgo owning
  transcription quality and its caching (the kind of response-cache + multi-provider
  maturity a dedicated tool like PySN-digest has built is deliberately left on the
  table).
- **The composite artifact is now load-bearing as the handoff contract.** Its
  shape and stability become a first-class obligation rather than an afterthought,
  because external transcribers depend on it. A future change to the composite
  output shape is a contract change, not an internal detail.

## Alternatives considered

- **Own a provider-agnostic VLM call** (`ecosystem.md`'s prior recommendation).
  Rejected: it duplicates the MCP caller's own vision capability, imports a
  churning multi-provider subsystem plus key management and caching, and injects
  nondeterminism into a codebase whose contracts are shape-based and mock-tested.
  License-OK (Apache-2.0 prior art is available to import) is not the same as
  worth-it.
- **Ship an optional, quarantined reference transcriber behind an extra** — core
  stays LLM-free, but a "just works" demo path exists. Rejected: even optional and
  isolated, it makes inkbridge an LLM surface to maintain (keys, provider drift,
  cache), and the maintainer's own workflow already supplies transcription via
  their assistant, so the adoption gap it would close is not one this project needs
  to own. Left as a possible future *companion package*, not an inkbridge concern.
- **Keep `convert --ocr` in the loop diagram but label it caller-supplied.**
  Rejected: leaving a named inkbridge command in the target end state keeps
  advertising the surface. Removing it is the honest signal.

## Related

- [`architecture.md`](../architecture.md) — the agent-loop target end state, whose
  step 5 (`convert --ocr`) this ADR removes, and the "Targeted reads" section,
  whose deterministic-vs-transcription contrast this ADR sharpens.
- [`ecosystem.md`](../ecosystem.md) — the survey whose "own provider-agnostic VLM
  call" recommendation this ADR reverses.
- [ADR-0003](0003-materialized-answers-artifact.md) — the materialized answers
  artifact; the deterministic semantic read that stays in scope.
- [ADR-0007](0007-transport-protocol-seam.md) — the shape-based conformance
  discipline this decision protects from nondeterminism.
- [ADR-0008](0008-per-cell-decision-bands.md) — per-cell decision bands, the
  deterministic targeted-read mechanism.
