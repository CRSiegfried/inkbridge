# ADR-0004: No page-identity fiducial; positional page mapping under a dense-mark assumption

Status: Accepted
Date: 2026-07-21

## Context

Readback maps a pulled `.pdf.mark` back to its compose manifest one page at a
time, assuming mark-page *k* is compose-page *k*
(Analysis 0009 (unpublished) F7 — an
observed but unconfirmed ordering). To confirm that mapping per-document,
earlier design carried a **positional fiducial**: the command-strip
capture-trigger box was drawn in a center-out "slot" indexed by page number
(Analysis 0012 (unpublished) F4), the idea
being that a page's identity could be recovered from the box's position. That
fiducial was emitted into the manifest but read by nothing, and its position
drifting page-to-page looked like a bug to a reader who didn't know the intent.

Designing out how it would actually be *read*, it collapses — and so does the
obvious fallback of a structural page-count check. Two hardware facts drive
this ADR:

**1. The readback decodes the isolated ink layer.** The `.pdf.mark` contains
user strokes only; printed content is byte-level absent
(Analysis 0009 (unpublished) F3;
`composite.py` module docstring). A fiducial printed into the base PDF lives in
the base PDF, indexed by *compose* page; the thing that can be misordered is
the *mark/device* page; and the two never meet in the artifact we decode.
Compositing device-page *k*'s ink over base-page *j* just re-reads base-page
*j*'s own printed fiducial (= *j*) — circular. The rescue of pre-seeding *ink*
into the mark is refuted too: the device generates its own mark from scratch,
annotated-only and ink-pure, and a pre-seeded cloud `.pdf.mark` collides rather
than merges — the server renames the device's copy `..._CONFLICT_<ts>.pdf.mark`
(Analysis 0014 (unpublished)
F2/F4/F11). Only the pen puts ink in the layer we decode.

**2. The mark is sparse and page-index-free.** Only *annotated* pages
materialize, and the container stores no document-page index
(Analysis 0009 (unpublished) F7).
Confirmed live on 2026-07-21: `InformationTrustworthiness.pdf` is 10 pages, but
its `.pdf.mark` reports `get_total_pages() == 2` — the eight un-annotated pages
simply aren't there. This kills the tempting fallback of a **page-count guard**
(compare the mark's page count to the manifest's): the count equals the number
of *annotated* pages, not document pages, so a normal partially-filled form
would trip it. A guard raising on `manifest.pages != mark.pages` false-positives
on any document with an entirely blank page — verified: `check(expected=10,
actual=2)` raises for a perfectly ordinary read. A blank page and a deleted
page are indistinguishable by count.

Meanwhile the gap a guard was meant to insure against is narrow. The mark is
paired to its base PDF per-document, the device never modifies a pushed PDF
(Analysis 0014 (unpublished) F3), and
document/page-file identity is already handled by content `md5` / server
`File.id` joins, not fiducials
(Analysis 0014 (unpublished) F11).

## Decision

We will **not** carry a page-identity fiducial of any kind — printed or
ink-seeded — and we will **not** ship a page-count structural guard.

- **Page mapping stays positional**: mark-page *k* is compose-page *k*, which
  holds when the mark is **dense** (every manifest page was annotated). This is
  an explicit, recorded assumption, not a proven invariant.
- **The capture-trigger box is de-overloaded to a pure trigger** — one centered
  box per page, carrying no `slot` / `fiducial_unique` and no page identity.
- **No structural guard.** Page count cannot cleanly detect insertion/deletion
  given a sparse, index-free mark, so we do not add one rather than add a check
  that false-positives on ordinary partial fills.
- **A sparse mark fails safe, not silently.** `read_mark` decodes eagerly over
  every manifest page; when a page is absent from the (sparse) mark,
  `decode_page_gray`'s `IndexError` is caught and re-raised as a typed
  `SparseMarkError`, which the CLI (`collect` / `answers` / `readback`) surfaces
  as a PRECONDITION(6) contract error. This is a fail-safe refusal, not a
  corrector — it makes a violation of the dense-mark assumption loud and typed
  rather than misattributing later pages' ink. It is distinct from the rejected
  page-count guard: it fires only on a genuinely absent page, so a dense mark
  decodes unchanged and valid reads never false-positive.

## Consequences

- **Easier**: the capture box is a single centered element; the readback path
  drops an unshippable guard and its false-positive risk; `geometry.py` sheds
  the unused slot machinery (`trigger_slots`, `trigger_slot_x0`,
  `trigger_pitch`).
- **Given up / open**: we cannot *recover* page identity when device pages
  diverge from compose pages, nor *detect* divergence in advance. The dense-mark
  assumption is load-bearing; when it is violated (a sparse multi-page mark — a
  page left entirely blank), `read_mark` now refuses with a typed
  `SparseMarkError` at decode time rather than misattributing later pages' ink.
  That is a fail-safe, not a fix: the missing page can't be located, so the read
  stops loudly, but the mapping still can't be corrected without positional page
  identity we don't have. Today's compose forms are short and typically fully
  annotated, so this has not bitten in practice — but **"readback assumes a
  dense mark" is a real open problem** deserving its own analysis (candidate
  follow-up). The only avenue that could ever *correct* rather than refuse is
  `.note`-file page metadata (see Alternatives).
- **Supersedes** the page-identity role of the fiducial referenced in
  Analysis 0009 (unpublished) F7 and
  Analysis 0012 (unpublished) F4. Those
  analyses stand as historical findings; this ADR is the current word on page
  tracking.

## Alternatives considered

- **Printed positional/encoded stamp in the base PDF** (the original plan, in
  several encodings — center-out slot, binary tick-row, comb-style glyph).
  Rejected: unreadable from the isolated-ink readback regardless of encoding or
  placement (Context fact 1). A naive round-trip test would have *passed* by
  rasterizing the PDF, giving false confidence while the real `.note` path
  stayed blind.
- **Ink-seeded stamp in the `.pdf.mark`** (mock user ink so it survives
  readback). Rejected: the device generates its own mark and a pre-seeded one
  collides rather than merges
  (Analysis 0014 (unpublished) F11).
  Synthetic ink remains useful, but only *locally*, as the `proof` self-test
  (Analysis 0017 (unpublished) F8) —
  a test harness, never a page carrier.
- **Page-count structural guard** (raise when the mark's page count disagrees
  with the manifest's). Rejected: the mark is sparse and index-free (Context
  fact 2), so the count reflects annotated pages, not document pages — the guard
  false-positives on ordinary partial fills and cannot distinguish a blank page
  from a deleted one. A one-directional variant (raise only when annotated pages
  *exceed* document pages) avoids false positives but catches so few real
  insertions it was not worth the code.
- **`.note`-file page metadata** (map device→compose pages via stable per-page
  IDs in the container). Deferred, not rejected: higher effort and uncertain
  payoff while in-device page divergence is itself unconfirmed. It is the only
  avenue that could ever *correct* rather than merely detect, so it is where to
  look if the dense-mark assumption starts biting.
- **Do nothing beyond positional mapping.** Accepted for now: it is the honest
  state of what the artifact can tell us, with the dense-mark assumption
  recorded as an open problem rather than papered over by a guard that lies.
