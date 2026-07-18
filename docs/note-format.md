# The `.note` format: undocumented, not obfuscated

No official spec for `.note` exists. Ratta has never published one, and no
tool in the ecosystem (see [`ecosystem.md`](ecosystem.md)) ships one either
— every reader treats the reference parser
([`supernotelib`](https://github.com/jya-dev/supernote-tool)) as the spec.
This document records what inspecting that parser actually shows, why the
format is undocumented in the first place, and what that structure implies
for how `inkbridge` should read notebooks.

**Caveat**: everything below comes from reading the reference parser's
source (structure, class/constant names, and its public API), not from a
byte-level hex-dump audit of real `.note` files. Treat it as "what the
reverse-engineered parser implies," not an authoritative spec — verify
against real notebooks before depending on anything beyond what
`supernotelib`'s public API already exposes.

## Not encrypted, not obfuscated

The parser contains no cryptographic operations and no deobfuscation step.
It's a plain custom binary container:

- A hierarchical metadata system of ASCII key=value pairs (page count,
  layer names, title/keyword regions, links), organized into named sections
  (header, pages, layers, footer).
- Fixed-size pointers — `ADDRESS_SIZE = 4` and `LENGTH_FIELD_SIZE = 4` bytes
  — chaining those sections together, so a reader can locate any section by
  address rather than by scanning the whole file linearly.
- Independent implementations (`supernotelib`, `SupernoteSharp`,
  `supernote_pdf`) converge on the same structure, which is a reasonable
  signal the reverse-engineering is solid rather than riddled with
  guesswork.

## Why no official spec

Most likely ordinary small-hardware-company neglect, not deliberate
lock-in. A Hacker News thread on Supernote's openness
([discussion](https://news.ycombinator.com/item?id=37273131)) describes
Ratta as tolerant of tinkering and sideloading — not the posture of a
company trying to wall off its formats. Ratta is a small team shipping
firmware and device features; publishing a format spec has no obvious
business upside and nobody asked for one loudly enough until the community
reverse-engineered it anyway. (reMarkable's `.lines` format followed a
similar arc: undocumented, community-reverse-engineered, no hostility from
the vendor.)

## The read/write asymmetry

Every existing tool reads or converts `.note` files. None write them. No
open tool has demonstrated constructing a valid `.note` file from scratch —
plausibly because nobody has needed to (every known use case so far is "get
my notes out," not "put structured content in"), not necessarily because
it's uniquely hard. This is why `inkbridge`'s merge feature goes through a
PDF intermediate rather than writing `.note` directly — see
[`architecture.md`](architecture.md#open-design-questions).

## Implication: targeted reads for latency

The address/length-pointer structure isn't just an implementation detail —
it's an opportunity. `supernotelib`'s own converter API already exposes
per-page decoding (`convert(page_number)`, distinct from the "convert every
page" path), and metadata accessors (`get_keywords()`, `get_links()`,
`get_total_pages()`) are called independently of page rendering. That's
consistent with metadata being cheap to read separately from the actual
ink/stroke bitmap decode — which matters a lot for the agent loop.

Motivating case: an agent pushes a document with a checkbox ("approve?
`[ ]`") to the device and wants to poll cheaply for whether it's been
marked — without re-running full-notebook conversion or an OCR/VLM call on
every poll, and ideally without decoding pages that haven't changed at all.

Three tiers of targeting, cheapest first:

1. **Change detection before decode** — if a page-level hash or timestamp
   is reachable via the metadata/address table without decoding stroke
   data, a poll can skip untouched pages entirely. Not yet confirmed from
   source inspection alone; needs checking against real notebook files.
2. **Page-level targeting** — use `convert(page_number)` to decode only the
   page that matters instead of the whole notebook. Already available
   today via `supernotelib`'s existing API; no new format code needed.
3. **Region-level targeting** — after decoding one page, inspect only a
   known bounding box for ink presence ("is anything drawn inside this
   rectangle") instead of running full-page OCR/VLM transcription. Cheap,
   deterministic, no LLM call required for a yes/no mark-detection
   primitive.

## Where this lives in inkbridge

Proposed home: a new `convert/targeted.py` module alongside
`convert/notebook.py` — a "was region R on page N marked" primitive the
agent loop can poll cheaply, distinct from full transcription. This doesn't
block Phase 1 (full conversion should land first, since it's the
well-trodden path), but `convert/notebook.py`'s API should be designed with
per-page access as a first-class option from the start rather than
retrofitted later. Tracked in [`roadmap.md`](roadmap.md).
