# ADR-0005: Sanitized device captures may be tracked as test fixtures (a carve-out to public/local)

Status: Accepted
Date: 2026-07-22

## Context

[`CLAUDE.md`](../../CLAUDE.md) draws one bright line: "Everything tracked
here must be publishable. Anything machine-specific (credentials, deployment
instances, captured device data) goes in `deploy/local/` — gitignored, never
committed." Lumping *captured device data* in with credentials and deployment
instances is deliberate — pulled `.pdf.mark` sidecars, dispatch ledgers, and
`responses/` can carry real personal content and operator-specific state, and
the `.gitignore` enforces it by path (`captures/`, `deploy/local/`,
`inkbridge-ledger.json`, `responses/`).

That blanket wording now collides with a real need.
[Remediation item C2](../remediation-plan.md) exists because the riskiest code
in the repo — `convert/targeted.py:decode_page_gray`, the `supernotelib`
boundary, the 1-/0-indexed page conversion — has **zero** test coverage, and no
CI can catch a regression in it. The only input that exercises that path
faithfully is a **real** `.pdf.mark`: the format is an opaque, undocumented
Supernote container (`markSN_FILE_VER_…`), and a hand-built or synthesized mark
would test our fiction of the format, not the format. The device-free `proof`
self-test already covers *synthetic ink over known geometry*
(Analysis 0017 (unpublished) F8) —
C2 is specifically the gap `proof` cannot reach: the real device-format decode.

A concrete, non-sensitive fixture is already in hand. The `sampler_form`
capture — a **synthetic, self-authored grocery-list test form** (milk / eggs /
coffee; an HEB/Kroger/Costco store-run choice) built purely to calibrate
readback (Analysis 0016 (unpublished)) — was
promoted from `deploy/local/captures/` into `tests/fixtures/`. Its
`.gitignore` mechanism does **not** block it there (the ignore rules are
path-scoped to `captures/`/`deploy/local/`), and `read_mark` over its manifest
decodes it cleanly (2 pages, 8/18 cells `ANSWERED`, nonzero coverages verified
2026-07-22), with an expected `sampler_form.readback.json` alongside to assert
against. Same fixture also unblocks [C1](../remediation-plan.md)'s sparse-mark
test (a page-2-only manifest against the real mark).

So the mechanism permits it, but the *rule prose forbids it* — a `.pdf.mark` is
literally "captured device data." Committing one is **hard to reverse** (git
history) and **precedent-setting** (it defines what may cross the public line).
That is exactly the publishing-boundary call the ADR category exists for; doing
it silently would leave a future contributor staring at a tracked `.mark` that
reads as an unexplained violation of a written rule.

## Decision

We will permit a **narrow, checklisted class** of captured device data to be
tracked, as an explicit carve-out to the CLAUDE.md public/local rule; all other
captured data stays local-only exactly as before.

A capture MAY be tracked (only under `tests/fixtures/`, solely as a test input)
when **all** of the following hold:

1. **Synthetic content.** It was produced from self-authored test material with
   no real personal, third-party, or business data — a fixture form, not a real
   note.
2. **No secrets or operator state.** No credentials, tokens, account ids,
   emails, server hostnames, or deployment specifics in the bytes *or* in any
   sidecar/metadata shipped with it.
3. **Fixture-only purpose.** It exists to exercise code, is referenced by a
   test, and lives under `tests/fixtures/`.

The `sampler_form` set — `tests/fixtures/sampler_form.{pdf, pdf.mark,
manifest.json, readback.json}` — is admitted as the first fixture under this
carve-out.

Operational riders:

- **CLAUDE.md carries the cross-reference.** On acceptance, its public/local
  section is amended so the rule and the tracked file no longer contradict. The
  amended passage reads verbatim (new sentence appended to the existing rule):

  > Anything machine-specific (credentials, deployment instances, captured
  > device data) goes in `deploy/local/` — gitignored, never committed.
  > Exception (ADR-0005): sanitized, no-credential, synthetic-content device
  > captures MAY be tracked under `tests/fixtures/` solely as test inputs.

  Applied only when this ADR moves to `Accepted` (CLAUDE.md is public and
  tracked); until then the tracked fixture stays uncommitted.
- **Provenance sidecar caveat.** `sampler_form.readback.json`'s `mark_file`
  field records its original `deploy/local/captures/` source path. That path is
  non-sensitive, but the `real_mark_decode` test MUST assert on per-cell
  coverage/decision, **not** on that field verbatim (it won't match the tracked
  location).
- **Opacity is acknowledged, not waived.** A `.mark` is opaque binary a reviewer
  can't eyeball for leaks, so admission rests on **known provenance** (criteria
  1–2 above), established when the capture is created, not on post-hoc
  inspection. If provenance is uncertain, it stays local.

## Consequences

- **Easier:** C2 and C1 — the two S0 correctness holes on the highest-risk
  decode path — become closable with real CI coverage, no hardware in the loop.
  Regressions in the `supernotelib` boundary and the 1-/0-indexed conversion
  become catchable by `pytest`.
- **Harder / given up:** the bright-line "no captured device data is ever
  public" invariant is gone, replaced by a three-point judgment call. Every
  future candidate fixture now carries a **sanitization burden** — someone must
  vet provenance before tracking — and the residual risk is that a later
  capture is admitted carelessly and leaks something, made worse by the format's
  opacity (no easy textual review). The carve-out is deliberately narrow and
  checklisted to hold that risk down, but it is a real, standing cost that the
  old blanket rule did not have.
- **Scope discipline:** this ADR does **not** loosen anything for ledgers,
  `responses/`, real notes, or deployment state — those remain local-only,
  never committed. Only synthetic, secret-free, fixture-purpose captures move.
- **Reversibility:** narrow but not free to undo — once a fixture is in history,
  un-committing it means a history rewrite. Admit deliberately.

## Alternatives considered

- **Keep captures strictly local; C2/C1 use a local-only fixture and skip in
  public CI** (read `deploy/local/captures/`, `skip` when absent). Rejected as
  the primary path, kept as the documented fallback if this ADR is *not*
  accepted: it honors the existing rule untouched but leaves the riskiest code
  with **no** coverage on the public repo — which is the entire reason C2
  exists. A fixture that only runs on one operator's machine is barely a
  regression gate at all.
- **Synthesize a `.pdf.mark` programmatically** so it isn't "captured" and the
  rule never applies. Rejected: the container format is opaque and
  reverse-engineered; a hand-built mark would validate our model of the format
  rather than the real `supernotelib` decode. Synthetic ink already has its
  place as the `proof` self-test at the geometry layer
  (Analysis 0017 (unpublished) F8) —
  C2 is the complementary guarantee that only a real device artifact can give.
- **Git-LFS or an external fixture host.** Rejected: over-engineered for a ~43 KB
  file, and it adds a network fetch to CI plus a *second* place the public/local
  boundary has to be enforced — more surface, not less.
- **Track it with no recorded decision** (just `git add` the sanitized file).
  Rejected: this is the hard-to-reverse, precedent-setting boundary call the ADR
  category exists to capture; an unexplained tracked `.mark` directly
  contradicts the CLAUDE.md prose and invites a future contributor to either
  "fix" the violation or cite it as license for tracking real captures.

## Related

- [Remediation plan](../remediation-plan.md) — items C1 and C2, which this ADR
  unblocks.
- [ADR-0004](0004-no-page-fiducial.md) — page identity; uses the same
  `sampler_form` two-page capture reasoning.
- Analysis 0009 (unpublished) — the
  isolated-ink decode C2 gives coverage to.
- Analysis 0016 (unpublished) — where the
  `sampler_form` fixture came from.
- [`CLAUDE.md`](../../CLAUDE.md) — the public/local rule this carves out.
