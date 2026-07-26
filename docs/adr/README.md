# Architecture Decision Records

One record per significant, hard-to-reverse decision — format choice,
transport backend selection, licensing boundary, build-vs-extend calls.
Answers "what did we decide, and why," so nobody re-litigates a closed
question from scratch six months later without knowing what was already
considered and rejected.

## Rules

- **Sequential, immutable once accepted.** `NNNN-slug.md`, numbers never
  reused. Don't edit an accepted ADR's Context/Decision after the fact —
  reality moved on, write a new ADR and set the old one's Status to
  `Superseded by ADR-NNNN`. The one exception: an anticipated,
  decision-preserving cleanup the ADR itself flagged (e.g. dropping a stopgap
  once the interpreter floor moves) may be recorded as a dated
  `> **Update YYYY-MM-DD:**` note placed *above* the Context section. It must
  not alter the Context/Decision/Consequences body, and it never covers a
  change to the decision itself — that is always a supersession.
- **One decision per ADR.** If you're describing two decisions, write two
  ADRs, even if they were made in the same conversation.
- **Status is load-bearing.** `Proposed` (up for discussion) →
  `Accepted` (in effect) → `Superseded by ADR-NNNN` / `Rejected`. A reader
  should be able to tell at a glance whether a decision still holds.
- Use [`template.md`](template.md).

## When to write one vs. an Analysis

If you're still investigating and don't yet know the answer, write an
`analysis/` (local archive, unpublished) instead. Promote it to an ADR once there's an
actual decision to record — the ADR should cite the analysis it came from
rather than re-deriving the reasoning.

## Index

- [0001 — Diataxis+ documentation framework](0001-diataxis-plus-documentation-framework.md) — Superseded by ADR-0012
- [0002 — Agent-facing CLI output and exit-code contract](0002-agent-facing-cli-contract.md) — Accepted
- [0003 — Response state as a materialized answers artifact, monitoring delegated](0003-materialized-answers-artifact.md) — Accepted
- [0004 — No page-identity fiducial; positional page mapping under a dense-mark assumption](0004-no-page-fiducial.md) — Accepted
- [0005 — Sanitized device captures may be tracked as test fixtures (carve-out to public/local)](0005-tracked-test-fixture-captures.md) — Accepted
- [0006 — In-process operations layer (`inkbridge.ops`) between the CLI and the primitives](0006-in-process-operations-layer.md) — Accepted
- [0007 — `Transport` protocol seam; neutral errors by subclassing; config selection deferred](0007-transport-protocol-seam.md) — Accepted
- [0008 — Per-cell decision bands in the manifest; area-inverse scaling from one calibration](0008-per-cell-decision-bands.md) — Accepted
- [0009 — A cell-type registry and a block-IR compose entry point](0009-cell-type-registry-and-block-ir.md) — Accepted
- [0010 — Named-profile config (`config.toml`) with a per-profile ledger](0010-named-profile-config.md) — Accepted
- [0011 — Semantic transcription is out of scope; the boundary ends at the composite handoff](0011-transcription-out-of-scope.md) — Accepted
- [0012 — Re-adopt the Diataxis+ framework with review-time enforcement, no checked-in subagent](0012-manual-framework-enforcement.md) — Accepted
