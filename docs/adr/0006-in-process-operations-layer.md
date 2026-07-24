# ADR-0006: An in-process operations layer (`inkbridge.ops`) between the CLI and the primitives

Status: Accepted
Date: 2026-07-23

## Context

The good primitives already exist and are well-factored: `dispatch.py` (the
ledger + the Analysis-0011 join), `answers.py` (question resolution),
`readback.py` (the cell decode), and `transport/private_cloud.py` (the cloud
client). But the *orchestration* that composes them — push-then-record-a-ledger-
entry (`dispatch`), poll-and-join (`status`), pull-resolve-materialize-a-sidecar
(`collect`) — lives **inside Click command bodies** in `cli.py`. Nothing but the
CLI can invoke a whole operation; a caller who wants "dispatch this document"
gets a `click.Command`, not a function.

[Remediation item A1](../remediation-plan.md) calls this the single
highest-leverage refactor for the agent use case. The README promises a future
MCP server; as things stand that server would have to **shell out to the CLI and
parse `--json`**, or **re-implement the orchestration** against the primitives —
re-deriving the ledger upsert, the sidecar write, the exit-code mapping. Both
options duplicate the exact logic the CLI already contains and would drift from
it. The three orchestration verbs are the product's spine, and they are reachable
only through Click.

The forces:

- **An in-process caller needs the payloads, not the process.** The MCP server
  wants the `dispatch.v1` / `collect.v1` / status-row dicts as Python objects,
  not a subprocess exit code and a block of stdout to re-parse.
- **The CLI's behavior must not change.** `dispatch`, `status`, `collect` have
  committed exit codes (ADR-0002), `--json` payload shapes, and human output,
  all under test (`test_dispatch`, `test_collect`). The refactor has to be
  behavior-preserving to the byte.
- **Click concerns and domain concerns are currently entangled.** Exit codes,
  `echo`, `emit_result`, and the `_cloud_errors` mapping are interleaved with
  the ledger writes and the pull/resolve sequence. A reusable layer has to draw
  a clean line: domain logic below, presentation above.
- **Errors are the hard part of the seam.** Today the command bodies raise
  `CliError` (a Click exception carrying an exit code) directly from the middle
  of orchestration — e.g. collect's unknown-doc → exit 4, no-manifest → exit 6,
  no-response → exit 3. A layer that returns payloads can't also own exit codes,
  so the failure vocabulary has to move to something transport-neutral.

## Decision

We will add **`src/inkbridge/ops.py`**, an in-process operations layer that sits
between the CLI (and the future MCP server) and the primitives. It owns the
orchestration; the CLI becomes a thin adapter over it.

**Surface.** Three functions, one per orchestration verb, each **returning the
bare payload dict the CLI builds today**:

- `ops.dispatch(connect, ledger, file, *, remote_folder, manifest_path)` →
  the `dispatch.v1` body (`doc_id`, `remote`, `manifest`, `response_cells`,
  `trigger_cells`, `ledger`).
- `ops.status(connect, ledger, *, acknowledge)` → the list of status-row dicts
  (`doc_id`, `remote`, `state`, `mark_md5`, `base_changed`).
- `ops.collect(connect, ledger, doc_id, *, output_dir)` → the `collect.v1` body
  (the `answers.v1` payload plus `answers_file`).

**No Click, no `echo`/`emit_result`, no exit codes in `ops`.** The return value
is the payload; presentation (human `echo` vs. `emit_result`, the
`schema_version` envelope) stays entirely in the CLI.

**Dependencies are injected, not constructed.** The CLI keeps owning
credential/client construction (`PCClient.from_env`) and builds the `Ledger`;
`ops` receives that connector and the ledger as arguments. The transport is
injected as `connect` — a **zero-arg connector returning a connected client**
(the CLI passes the bare, un-invoked `PCClient.from_env`), which `ops` invokes
**lazily** via `connect()`, only once the operation actually needs the cloud
(so client construction happens inside `ops`, not before the call). Lazy is load-bearing, not incidental: a precondition failure
(unknown doc, no manifest) must not authenticate — the existing collect tests
assert exit 4 / exit 6 without the cloud ever being contacted — so `ops` can't
be handed an already-logged-in client eagerly. `ops` owns the **domain
writes** — the ledger `upsert`/`save`, and collect's `answers.json` sidecar
(written under the `output_dir` the caller passes in) — because those are part
of the operation's meaning, not its rendering. (Injecting the connector rather
than a concrete client is also what makes A2's transport seam land cleanly:
`ops` names neither the client type nor its constructor.)

**Typed domain exceptions are the failure vocabulary.** `ops` raises:

- `UnknownDocError` — no ledger entry for the doc_id (CLI → `NOT_FOUND`, exit 4).
- `NoManifestError` — the entry was dispatched without a manifest (CLI →
  `PRECONDITION`, exit 6).
- `NoResponseError` — no `.mark` on the server yet (CLI → `NO_CHANGE`, exit 3).
- plus the **existing** `SparseMarkError` (from `readback`), and the stdlib
  `FileNotFoundError` / `FileExistsError` the push path already raises.

The CLI maps each to a `CliError` with the right `Exit` code. `_cloud_errors`
stays in the CLI (it maps transport-layer `AuthError`/`httpx.RequestError`,
which are the transport's to name, not `ops`'). The one relocation: the
`SparseMarkError → CliError` translation moves **out** of the shared `_read_mark`
helper and **into** the CLI's exception mapping, so `ops.collect` can call the
plain `read_mark` and let the typed error propagate — keeping `ops` free of
`CliError`.

**Scope: the three orchestration verbs only.** `dispatch`, `status`, `collect`
command bodies become thin adapters: construct deps → call `ops` → `emit_result`
or human `echo`. The pure-read and utility commands (`ls`, `push`, `pull`, `rm`,
`readback`, `answers`, `compose`, `composite`, `merge`, `proof`, `doctor`) are
out of scope for this ADR — they don't compose the primitives the way the three
verbs do. Behavior is preserved exactly: payloads, exit codes, and human output
are identical, and `test_dispatch` / `test_collect` stay green unchanged.

## Consequences

- **Easier:** the MCP server (and any in-process caller) calls
  `ops.{dispatch,status,collect}` directly, gets typed payloads and typed
  errors, and never shells out or re-implements orchestration. The A2 transport
  seam drops in where the injected connector already is. The domain logic gets
  its own test surface (`test_ops.py`) that doesn't go through Click.
- **Harder / given up:** one more layer to keep honest. The CLI↔ops boundary is
  now a contract of its own — the payload shapes and the typed-exception set are
  a second interface to not break, on top of the CLI's committed one. The
  exit-code taxonomy is now split across two files (the `Exit` values and
  `CliError` in the CLI, the typed exceptions in `ops`); the mapping between them
  has to stay complete, and a new failure mode means adding a typed exception
  *and* wiring its CLI mapping. There is a small amount of ceremony —
  constructing deps in the command body and handing them down — that a
  monolithic command body did not have.
- **Behavior-preservation is load-bearing and tested.** The refactor claims
  byte-identical CLI behavior; the existing `test_dispatch`/`test_collect` nodes
  are the regression gate on that claim, and `test_ops.py` adds a structural
  assertion that no orchestration remains inline in the three command bodies
  (they delegate).

## Alternatives considered

- **MCP server shells out to the CLI and parses `--json`.** Rejected: it makes a
  subprocess boundary and text parsing load-bearing for the primary agent use
  case, couples the server to stdout formatting, and pays process-spawn cost per
  operation. The `--json` contract exists for *external* consumers; an
  in-process caller should not have to round-trip through it.
- **MCP server re-implements orchestration against the primitives.** Rejected:
  it duplicates the ledger upsert, the sidecar write, and the join — the logic
  most likely to drift — in a second place, so a fix to dispatch's ordering (see
  A4) would have to land twice or silently diverge.
- **Return Click-free results but keep raising `CliError` from `ops`.**
  Rejected: it drags `click` and the exit-code taxonomy into the domain layer, so
  a non-CLI caller inherits Click exceptions it has no exit code for. Typed
  domain exceptions keep `ops` presentation-agnostic and let each front-end
  (CLI now, MCP later) choose how a failure surfaces.
- **Push `ops` all the way down to own `from_env()` and `Ledger` construction.**
  Rejected for this ADR: constructing the client is where credentials, profiles
  (G6), and the transport seam (A2) live; making `ops` build its own client
  would re-entangle it with exactly those concerns. Injection keeps `ops` a pure
  composer and leaves dependency construction to the front-end, which is also
  what lets the tests drive it against `fake_cloud` and a temp ledger.
- **Refactor all commands onto `ops` now.** Rejected as scope creep: only
  the three verbs *orchestrate* the primitives; the pure reads (`answers`,
  `readback`) and utilities (`merge`, `composite`) have nothing to compose. CT1
  (universal `--json`/envelope adoption) is the item that touches the rest, and
  it is tracked separately.

## Related

- [Remediation plan](../remediation-plan.md) — item A1 (this ADR is its design)
  and A2 (the transport seam that lands on the injected connector).
- [ADR-0002](0002-agent-facing-cli-contract.md) — the exit-code taxonomy and
  `--json` envelope the CLI keeps owning; `ops` returns the payloads it wraps.
- [ADR-0003](0003-materialized-answers-artifact.md) — the `answers.json` sidecar
  `ops.collect` writes as its domain output.
- [ADR-0004](0004-no-page-fiducial.md) — the sparse-mark refusal whose typed
  error `ops.collect` lets propagate to the CLI's mapping.
