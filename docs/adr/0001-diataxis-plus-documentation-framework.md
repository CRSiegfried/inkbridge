# ADR-0001: Diataxis+ documentation framework

Status: Superseded by [ADR-0012](0012-manual-framework-enforcement.md)
Date: 2026-07-18

> **Superseded 2026-07-26.** The Decision below bundled two choices: the
> Diataxis+ categories, and enforcing them with a checked-in `docs-maintainer`
> subagent. The subagent definition and `CLAUDE.md` are no longer tracked in
> this repository, which changes the Decision and therefore calls for
> supersession rather than an update note.
> **[ADR-0012](0012-manual-framework-enforcement.md) is now the canonical
> record**: it re-adopts the categories below verbatim and moves enforcement to
> ordinary pull-request review against the written standard in
> [`docs/README.md`](../README.md#contributing-docs). The framework is
> unchanged and no document needs re-placing. References to
> `.claude/agents/docs-maintainer.md` and `CLAUDE.md` below are historical and
> no longer resolve.

## Context

`inkbridge` had four flat docs (`architecture.md`, `ecosystem.md`,
`note-format.md`, `roadmap.md`) with no organizing structure — fine at four
files, not fine once tutorials, how-tos, decision records, and exploratory
investigations start accumulating. Three problems specifically:

1. No place to record *why* a hard-to-reverse decision was made (transport
   backend choice, PDF-intermediate vs. direct `.note` writing) separately
   from the explanation of how the system currently works — so decisions
   and their rationale rot together with whatever explanation doc happened
   to mention them.
2. No place for rough, in-progress investigations (e.g. "how do we reliably
   detect a notebook was annotated") that aren't yet confident enough to be
   a decision or stable enough to be reference material, but are too
   substantial to just be a comment in an issue.
3. As the doc count grows, no navigational layer — a reader has to already
   know the tree to find everything relevant to one theme (e.g. everything
   touching the `.note` format).

## Decision

Adopt [Diataxis](https://diataxis.fr) (tutorials / how-to / reference /
explanation) as the base structure, extended with three categories:

- `adr/` — Architecture Decision Records (Nygard-style: Context, Decision,
  Consequences, Alternatives), sequential and immutable once accepted.
- `analysis/` — rough investigative write-ups with mandatory per-finding
  confidence levels and a pivot plan, feeding into ADRs once an
  investigation firms up into an actual decision.
- `moc/` — Maps of Concept: living, non-numbered index docs that link
  related material across all other categories by theme.

Enforce it with a subagent (`docs-maintainer`, see
[`.claude/agents/docs-maintainer.md`](../../.claude/agents/docs-maintainer.md))
that reviews new/substantively-edited docs for correct placement, and a
one-line rule in `CLAUDE.md` requiring that review. Full category
definitions and rules live in the documentation-framework README (local archive) and each
category's own `README.md`.

## Consequences

**Easier:** a doc's category signals its epistemic status at a glance (a
`reference/` doc claims to be complete and current; an `analysis/` doc
explicitly doesn't); decisions and their rationale have one canonical home
that isn't overwritten by later explanation edits; new contributors (human
or agent) have a MoC entry point instead of needing to already know the
tree.

**Harder:** seven categories is more upfront structure than four flat
files needed, and enforcing "review before merging a doc change" adds
friction to what used to be a plain edit — the bet is that `docs-maintainer`
keeps that friction low enough to be worth the consistency.

**Deferred, not solved by this ADR:** the four pre-existing docs are not
reclassified into the new structure yet. `docs-maintainer` owns that
migration as a follow-up task, not as part of adopting the framework — see
the migration tracking in the local archive.

## Alternatives considered

- **Flat `docs/` with no categories** (status quo) — rejected: already
  breaking down at four files, would get worse, not better, as
  tutorials/how-to/reference/ADR/analysis content accumulates.
- **Diataxis only, no extensions** — rejected: Diataxis has no answer for
  "record a decision" or "capture an in-progress, not-yet-confident
  investigation" — both needs this project already has (e.g. the
  PDF-vs-`.note`-write question in `architecture.md`'s open design
  questions, and the change-detection investigation in
  Analysis 0001 (unpublished)).
  Forcing those into `explanation/` would blur "how it works" with "what we
  decided" and "what we're still unsure about."
- **A single `decisions/` folder covering both settled and open
  questions** — rejected: collapses two different epistemic states
  (settled vs. exploratory) into one category, which defeats the point of
  being able to tell at a glance whether something is safe to build on.
