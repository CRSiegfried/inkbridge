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

Any new documentation file, or a substantive edit to an existing one, must be
reviewed by the `docs-maintainer` subagent before it is considered done — see
the rule in [`CLAUDE.md`](../CLAUDE.md) and the agent definition in
[`.claude/agents/docs-maintainer.md`](../.claude/agents/docs-maintainer.md).
