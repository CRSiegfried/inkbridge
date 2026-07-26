# inkbridge documentation

Public documentation for `inkbridge`. This is a curated, sanitized subset of a
larger internal documentation set; the research-notes series and other working
material stay in a local-only archive and are intentionally not published (see
[Citation conventions](#citation-conventions) below).

## Map of the tree

- [`adr/`](adr/) — Architecture Decision Records: one immutable-once-accepted
  record per significant, hard-to-reverse decision (the CLI contract, the
  transport seam, the fixture-tracking carve-out, and so on). Start with
  [`adr/README.md`](adr/README.md) for the index and conventions; new records
  follow [`adr/template.md`](adr/template.md).
- [`reference/cli.md`](reference/cli.md) — the complete `inkbridge` command
  surface: every command, its flags, its `--json` schema, and the shared
  exit-code taxonomy. Information-only; look things up here.
- [`how-to/run-the-mcp-server.md`](how-to/run-the-mcp-server.md) — task recipe
  for exposing the compose→dispatch→collect loop to an MCP-capable agent.
- [`architecture.md`](architecture.md) — how the pieces fit together and why
  `inkbridge` is a thin orchestration layer over existing Supernote libraries.
- [`ecosystem.md`](ecosystem.md) — survey of the prior-art libraries
  `inkbridge` builds on, with their licenses.
- [`remediation-plan.md`](remediation-plan.md) — the deployment-readiness
  tracker whose lettered rows (A/C/CT/D/G/DOC) the codebase cites; see below.

## Citation conventions

Source comments, docstrings, and these docs use three kinds of shorthand to
point at the reasoning behind a decision:

- **`ADR-NNNN`** (e.g. `ADR-0002`) → the matching record under
  [`adr/`](adr/), i.e. `adr/NNNN-<slug>.md`. These are published here and
  resolve within this tree.
- **Letter-prefixed IDs** — `A1`–`A5`, `C1`–`C3`, `CT1`/`CT2`, `D1`–`D6`,
  `G1`–`G6`, `DOC1` — → the correspondingly-lettered row in
  [`remediation-plan.md`](remediation-plan.md), the code-review remediation
  tracker. Each row states the issue, its severity, and the runnable check
  that closes it. These resolve within this tree.
- **Bare four-digit numbers**, often paired with a finding tag (e.g.
  `0009 F4`, `Analysis 0012`) → the internal *analysis* series: rough,
  exploratory research notes that investigate an open question without
  committing to a decision. **This series is unpublished** — it lives in a
  local-only archive and is deliberately not part of the public repository, so
  these citations intentionally do not resolve here. An analysis often *feeds*
  an ADR once its investigation firms up into a decision; when that has
  happened, the corresponding published ADR carries the settled result. Treat a
  four-digit analysis citation as provenance for "why," not as a link you can
  follow in the public tree.

## Contributing docs

New documentation follows [Diataxis](https://diataxis.fr/), extended with the
two categories Diataxis has no answer for (decision records and their
provenance) — see [ADR-0012](adr/0012-manual-framework-enforcement.md) for the
framework and why it is enforced at review time rather than by tooling. Pick
the category by what the reader needs, not by subject matter:

- **`how-to/`** — a task recipe for someone who already knows what they want
  to accomplish. Goal-oriented, assumes context.
- **`reference/`** — a complete, lookup-oriented description of a surface
  (flags, schemas, exit codes). Claims to be exhaustive and current.
- **explainers** (currently top-level, e.g. [`architecture.md`](architecture.md),
  [`ecosystem.md`](ecosystem.md)) — understanding-oriented background: how
  the pieces fit and why.
- **[`adr/`](adr/)** — one record per significant, hard-to-reverse decision.
  Sequential and **immutable once accepted**: don't rewrite an accepted ADR's
  Context or Decision, supersede it with a new one. The sole exception is a
  dated update note for an anticipated, decision-preserving cleanup. Full
  rules and the index: [`adr/README.md`](adr/README.md); new records use
  [`adr/template.md`](adr/template.md).

A doc's category is a claim about its epistemic status, so putting a piece in
the wrong one misleads the reader — prefer moving a doc over letting a
category drift. Keep relative links working when you move one, and add the
entry to the map above.

Note that the analysis series described under
[Citation conventions](#citation-conventions) is unpublished; if your change
depends on one, carry the settled result into an ADR rather than linking to
something readers of this repository cannot open.
