# ADR-0008: Per-cell decision bands in the manifest; area-inverse scaling from one calibration

Status: Accepted
Date: 2026-07-23

## Context

[Remediation item G1](../remediation-plan.md) targets the readback decision
thresholds. `readback.decide` classifies a cell three ways (blank / ambiguous /
answered) from its **ink-coverage fraction** — ink pixels ÷ cell-area pixels —
against two module-global bands (`AMBIGUOUS_FLOOR = 0.001`,
`ANSWERED_LINE = 0.004`), calibrated once (Analysis 0009) on a single tick-box
size. Their own docstring concedes the numbers are geometry-dependent and do not
transfer.

They don't transfer because the fraction's **denominator is the cell area, and
that varies**: `compose` emits several cell sizes (a 90 px tick box vs. a large
capture area), and `--density` rescales every box (the CLI default is
`dense`, scale 0.72 — tick cells at 0.52× the area). A deliberate pen mark is
roughly **constant absolute ink** (a stroke is a stroke), so the *fraction* it
produces is inversely proportional to cell area. One global fraction pair
therefore mis-decides whenever cell size drifts from the calibration size — the
smaller the cell, the higher the fraction the same mark yields, so a global
under-thresholds stray ink in small cells and could over-threshold a real mark
in large ones.

`compose` already knows every cell's geometry (it computes the bboxes). The read
side does not — it only sees normalized bboxes and a decoded page.

## Decision

We will move the decision thresholds **out of `readback` module globals and into
the manifest, per cell**, computed by `compose` from each cell's geometry.

**Model — area-inverse scaling from one calibration.** The calibration bands
stay anchored to one reference geometry: the tick box at scale 1.0
(`A_ref = (glyph_box + 2·glyph_pad)²` px, the size Analysis 0009 calibrated on).
For a cell of bbox-pixel-area `A_cell`, `compose` writes

    bands = { ambiguous_floor: BASE_FLOOR × (A_ref / A_cell),
              answered_line:   BASE_LINE  × (A_ref / A_cell) }

into that cell's manifest entry. The `A_ref / A_cell` factor holds the
*absolute* ink threshold constant across sizes: a standard tick cell at scale
1.0 gets factor 1.0 (bands == base, so current behavior is preserved for the
calibrated case); a dense (smaller) cell gets a proportionally **higher**
fraction threshold, matching the higher fraction the same mark produces there.
**Uniform across all cell types** (chosen over a tick-only variant): a stroke is
one absolute-ink threshold everywhere, and large presence cells (comb/capture)
correctly inherit a low fraction threshold — presence needs little ink — with no
per-type branch or second threshold family in the manifest.

**Read side — manifest bands are authoritative; no decision-relevant global is
consulted when they are present.** `read_pages` reads each cell's `bands` and
passes them to `decide`; the module constants remain only as (a) the calibration
basis `compose` scales from and (b) the fallback for a manifest that predates the
field. `compose` stamps `bands` on every cell, so current output never takes the
fallback.

`compose` imports the base bands from `readback` as the single calibration
source (a one-way `compose → readback` dependency — `readback` does not import
`compose`, so no cycle), rather than duplicating the calibrated numbers.

## Consequences

- **Easier:** decode is correct across densities and cell sizes — the whole
  reason the bands existed as "provisional." A new cell size (a new density, a
  new directive with a differently-sized box) decodes correctly with no
  recalibration, because `compose` derives its band from geometry. The manifest
  becomes self-describing: a reader needs only the manifest to decode, not a
  matching `readback` build's globals.
- **Harder / given up:** the manifest gains a `bands` field per cell that
  consumers may come to depend on — a schema commitment. The absolute-ink model
  is itself a calibration assumption (a stroke ≈ constant ink); it is a better
  model than "constant fraction," but it is still a model, and the *base*
  numbers remain the provisional Analysis-0009 values — G1 fixes the *scaling*,
  not the base calibration, which still wants an on-device sweep. `compose` now
  depends on `readback` for the base constants.
- **Behavior preservation:** a standard tick cell at scale 1.0 is unchanged
  (factor 1.0); manifests without `bands` (the tracked `sampler_form` fixture,
  any pre-G1 manifest) decode exactly as before via the fallback, so
  `test_real_mark_decode` and `proof` stay green (a fully-inked `proof` cell
  reads ≈1.0 coverage, far above any band).

## Alternatives considered

- **Keep global bands, recalibrate the numbers.** Rejected: any single global
  pair is wrong for *some* cell size the moment `compose` emits more than one, or
  `--density` rescales — recalibrating just moves which size is right. The bug is
  the fixed denominator, not the specific constants.
- **Tick-boxes area-scaled, presence cells on a fixed floor.** Rejected (the
  offered alternative at the design checkpoint): more conservative about
  extrapolating the calibration to writing areas, but it adds a per-type branch
  and two threshold families in the manifest for no clear gain — a low fraction
  threshold on a large presence cell is exactly what "presence needs little ink"
  wants, which the uniform rule already gives.
- **Readback infers per-cell thresholds from bbox at decode time** (no manifest
  field). Rejected: it re-derives geometry the write side already has, needs the
  canvas dims and the reference size baked into `readback`, and keeps the
  decision logic coupled to a `readback`-side constant — the opposite of making
  the manifest self-describing. Writing the band once, where the geometry is
  known, is the cleaner seam.
- **Store an absolute ink-pixel threshold instead of a fraction.** Rejected for
  now: it would change `decide`'s input contract (fraction → absolute count) and
  every caller/test that speaks coverage fractions; scaling the existing fraction
  bands per cell achieves the same constant-absolute-ink effect without touching
  the coverage contract.

## Related

- [Remediation plan](../remediation-plan.md) — item G1 (this ADR is its design),
  and G2 (device geometry constants), which shares the "geometry belongs in one
  place" thrust.
- Analysis 0009 (unpublished) — the
  original band calibration these scale from.
- [ADR-0004](0004-no-page-fiducial.md) — the readback decode path this decides
  over.
