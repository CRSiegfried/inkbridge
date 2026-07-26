# ADR-0012: Re-adopt the Diataxis+ framework with review-time enforcement, no checked-in subagent

Status: Accepted
Date: 2026-07-26
Supersedes: [ADR-0001](0001-diataxis-plus-documentation-framework.md)

## Context

[ADR-0001](0001-diataxis-plus-documentation-framework.md) adopted the Diataxis+
documentation framework and, in the same Decision, chose how to enforce it: "a
subagent (`docs-maintainer`, see `.claude/agents/docs-maintainer.md`) that
reviews new/substantively-edited docs for correct placement, and a one-line rule
in `CLAUDE.md` requiring that review."

Two things have since changed.

- **The enforcement mechanism was withdrawn.** `.claude/agents/docs-maintainer.md`
  and `CLAUDE.md` are no longer tracked in this repository. Shipping a subagent
  definition imposes one contributor's assistant tooling on everyone who clones
  the project, and checked-in agent definitions that instruct a model on a
  reader's behalf are something contributors may reasonably be wary of running.
  A public repository should stay neutral about how its contributors work.
  Those files are now gitignored; the mandatory-review rule went with them.

- **ADR-0001 bundled two decisions**, contrary to this directory's own "one
  decision per ADR" rule. The framework (what categories exist, what each one
  claims about a document's epistemic status) and the enforcement mechanism (who
  or what checks placement before a change lands) are independent choices — the
  first is a property of the documentation, the second a property of the
  workflow. Bundling them is precisely why withdrawing the mechanism could not be
  recorded as a dated update note: `adr/README.md` reserves those for
  decision-preserving cleanups and states that a change to the decision itself
  "is always a supersession." An update note was written first and was the wrong
  instrument.

The framework itself is not in question. It has been in use since 2026-07-18 and
the categories have held up; only the enforcement half is being revisited.

## Decision

We will **re-adopt the Diataxis+ framework unchanged** and **enforce it by
ordinary pull-request review** rather than by a checked-in subagent.

The categories, carried forward verbatim from ADR-0001:

- The four Diataxis categories — `tutorial/`, `how-to/`, `reference/`,
  `explanation/` — split by what the reader needs, not by subject matter.
- `adr/` — Architecture Decision Records (Nygard-style: Context, Decision,
  Consequences, Alternatives), sequential and immutable once accepted.
- `analysis/` — rough investigative write-ups with mandatory per-finding
  confidence levels and a pivot plan, feeding into ADRs once an investigation
  firms up into an actual decision.
- `moc/` — Maps of Concept: living, non-numbered index docs that link related
  material across all other categories by theme.

Enforcement is now: the placement standard is **written down for humans** under
"Contributing docs" in [`../README.md`](../README.md#contributing-docs), and
`CONTRIBUTING.md` points there. A reviewer applies it at PR time. No repository
file requires that any particular tool — agentic or otherwise — perform that
review. Contributors who want assistant help with it are free to configure that
locally; `.claude/` is gitignored precisely so they can.

## Consequences

**Easier:** the repository no longer ships assistant configuration, so cloning
it carries no tooling assumptions and nothing that instructs a model on the
reader's behalf. The placement rules are now legible to a human contributor
without reading an agent prompt — previously the fullest statement of the
standard lived inside `docs-maintainer.md`, which is a strange place for a
convention that applies to everyone. Separating framework from enforcement also
means the next change to *how* docs get reviewed no longer disturbs the record
of *what the categories are*.

**Harder:** enforcement is now genuinely weaker, and this ADR should not pretend
otherwise. A subagent checked every substantive doc edit; a human reviewer checks
what they happen to notice, on a single-maintainer project where most PRs are
self-reviewed. Expect category drift and stale cross-links to accumulate at a
rate ADR-0001 was designed to prevent. The written standard mitigates this only
insofar as someone reads it.

**Explicitly given up:** the "review before merging a doc change" gate as a
*requirement*. It is now a convention. No CI check replaces it — a link-integrity
or placement linter in the existing gate would be the natural way to recover part
of what was lost, and is deliberately not proposed here rather than being
promised and forgotten.

**Unchanged:** every category and every rule about them, including ADR
immutability and the analysis series' unpublished status. Documents already
placed under ADR-0001 need no migration; this ADR supersedes ADR-0001's record,
not its effects. ADR-0001's own "Deferred" item — the four pre-existing docs not
yet reclassified — carries forward unresolved, and is now owned by whoever next
touches them rather than by a named agent.

## Alternatives considered

- **Leave the dated update note on ADR-0001** (what was done first) — rejected:
  `adr/README.md:18-19` scopes update notes to anticipated, decision-preserving
  cleanups and says a change to the decision "is always a supersession."
  Withdrawing the enforcement mechanism named in the Decision is not
  decision-preserving. Keeping the note would have made the directory's most
  load-bearing rule advisory in the one case that tested it.
- **Supersede ADR-0001 with a record that only removes enforcement**, leaving
  the framework's canonical statement in a superseded document — rejected: a
  reader who follows `Superseded by` off ADR-0001 should land somewhere that
  states the framework in full. Splitting "the categories" and "how they are
  enforced" across a superseded and a live ADR reproduces the original bundling
  problem in a worse form.
- **Keep the subagent but stop requiring it** — rejected: the file would still
  ship, which is the actual objection. A repository-tracked agent definition
  reads as project-endorsed regardless of whether a rule cites it.
- **Replace it with a CI placement/link linter now** — rejected as scope: it is
  a real option and probably the right long-term answer, but writing one is a
  change to the gate, not a documentation decision, and bundling it here would
  repeat exactly the mistake this ADR exists to correct.
