# ADR-0007: A `Transport` protocol seam; neutral errors by subclassing; config selection deferred

Status: Accepted
Date: 2026-07-23

## Context

[Remediation item A2](../remediation-plan.md) targets the transport seam.
`cli.py` names `PCClient` concretely at ~16 call sites across eight commands and
`_cloud_errors` keys on `private_cloud.AuthError`; the official-cloud stub
`transport/cloud.py` exposes free functions (`push`/`pull`/`list_remote`) whose
shape is incompatible with `PCClient`'s info-dict-returning methods, so it can
never be wired in without touching every command. The plan's target: "a
`Transport` protocol (login/ls/resolve/push/pull/delete + transport-neutral
`AuthError`/`MissingBytesError`), selected from config; `_cloud_errors` maps
neutral exception types."

A1 ([ADR-0006](0006-in-process-operations-layer.md)) just landed and constrains
the shape: `ops.*` consume a **zero-arg connector** (`connect`) returning a
connected client, invoked lazily so a precondition failure never authenticates.
A2's factory has to *be* that connector.

Two forces the plan's one-line target understates, surfaced by an external
design review:

- **The real incompatibility was never method names — it was payload shapes and
  exception semantics.** `push`→`{md5,size,folder,name}`, `pull`→`{listing_md5,
  bytes_md5,match,size,dest}`, `ls`→rows the CLI renders on `fileName`/
  `isFolder=="Y"`/`size`/`md5`, and `resolve_dir` returns a private-cloud `int`
  directory id that `ls` consumes. A bare `Protocol` of method names captures
  none of that; `cloud.py` diverged precisely in the parts a name-only protocol
  wouldn't have caught.
- **Behavior preservation is load-bearing and fragile here.** `MissingBytesError`
  is caught as a `FileNotFoundError` by both `ops.collect` and `cli.pull` (the
  phantom-row → NO_CHANGE path); four test modules construct
  `private_cloud.AuthError` with its 3-arg `(endpoint, code, msg)` signature and
  monkeypatch `PCClient.from_env`. Any exception re-homing or factory wiring that
  disturbs those breaks green tests.

## Decision

We will introduce the seam as a **pure-behavioral protocol plus a zero-arg
connector**, make the neutral exceptions **bases (by subclassing)** of the
private-cloud ones, and **defer config-driven backend selection to G6**.

**`transport/base.py`** holds:

- `Transport` — a `runtime_checkable` `Protocol` declaring only the
  **post-connection** surface the CLI/ops actually call: `ls`, `resolve_dir`,
  `push`, `pull`, `delete`. It deliberately **omits `login` and `from_env`**
  (deviating from the plan's literal list): construction and credentials are the
  connector's job, not an instance-surface concern, and login shape is
  backend-specific (a local folder has none). `resolve_dir` returns an **opaque
  `DirHandle`** that `ls` consumes — the private cloud's handle happens to be
  `int`; the protocol does not commit to that.
- Neutral `AuthError(Exception)` and `MissingBytesError(FileNotFoundError)` with
  plain-message constructors.

**`private_cloud` exceptions become subclasses of the neutral ones**, not moves,
aliases, or wrappers: `class AuthError(PrivateCloudError, base.AuthError)` and
`MissingBytesError(base.MissingBytesError)`. This keeps every existing
`except private_cloud.AuthError`, the 3-arg construction in tests, the exact
message text, and the `MissingBytesError`-is-a-`FileNotFoundError` relation
intact, while letting `_cloud_errors` catch the **neutral** `base.AuthError`.

**`transport.connect`** is the zero-arg connector — the CLI passes it straight
onto A1's `connect` seam and calls it directly in the five non-ops commands. It
resolves `PCClient.from_env` **at call time** (never captured at import) so the
test monkeypatches stay live and credentials read lazily; a `KeyError` from
missing config propagates unchanged (`doctor`'s `config_missing` path). Today it
returns the private cloud unconditionally; a config-driven registry drops in
here at G6 — we do **not** build selection machinery for a single selectable
value.

**`cli.py` names no concrete backend.** All `PCClient` imports/uses become
`transport.connect` / `transport.connect()`; `_cloud_errors` imports
`base.AuthError`. Grep count for the concrete symbols → 0.

**`transport/cloud.py` is deleted** (with the README stub sentence updated). It
is referenced nowhere in `src`/`tests`; reshaping it into a protocol skeleton of
`NotImplementedError`s would be dead code that can't join the conformance suite,
and leaving it preserves the exact divergence A2 exists to kill. The `Transport`
protocol + the conformance suite become the spec a real official-cloud backend
implements against; git history keeps the old notes.

**`tests/test_transport_contract.py`** asserts the **semantic** contract
(push/pull round-trip and result-dict shapes, the error taxonomy, the neutral
exception hierarchy, atomic `delete` refusal, `ls` row shape, `resolve_dir`∘`ls`
composition), parametrized over a backend fixture — one entry today
(private cloud over `fake_cloud`), the harness D3's `LocalFolder` plugs into.
Dialect-specific behaviors (signature-stripping, E0321 phantoms, pagination)
stay in `test_private_cloud.py`.

**Documented residual leaks (accepted as G6/D3 debt, not fixed here):**

- `_cloud_errors` still catches `httpx.RequestError` for the "unreachable"
  PRECONDITION class — transport-specific, not covered by the neutral set. A
  neutral `UnreachableError` is deferred (wrapping every `PCClient` call site is
  high blast radius for a currently-dead branch).
- `doctor` reads `client.api` (duck-typed, not on the protocol).
- The neutral `ls`/`resolve_dir` contract promotes wire-dialect fields
  (`isFolder=="Y"`, `int` handles) that `LocalFolder` will inherit.

## Consequences

- **Easier:** the CLI is backend-agnostic; an in-process caller or a second
  backend (D3) targets `Transport` + an executable contract spec instead of
  folklore. The connector slots onto A1 with zero impedance (both are zero-arg).
  Exception neutrality is achieved with **no** behavior change — subclassing is
  purely additive.
- **Harder / given up:** the neutral surface is honest but incomplete — the
  "unreachable" taxonomy branch and `doctor`'s `.api` still reach past the seam,
  so "A2 done" is *not* "seam fully neutral." The contract suite duplicates a
  little of `test_private_cloud.py`'s round-trip coverage (deliberately — the
  contract copy is the backend-agnostic one D3 reuses). Promoting dialect fields
  into the neutral contract is standing debt.
- **Behavior-preservation is the gate:** every existing test stays green,
  including the four modules that monkeypatch `from_env` (the call-time
  resolution is what keeps them live) and the ones constructing 3-arg
  `AuthError`.

## Alternatives considered

- **Config-driven selection now (plan's literal target).** Rejected for this
  item: selection machinery with exactly one selectable value is untestable
  speculation and imports an unclassified "unknown backend" failure mode into a
  behavior-preserving commit. Deferred to G6 (named profiles), where a second
  thing to select actually exists. `connect()` is structured so the registry is
  a ~5-line drop-in.
- **Fold D3 `LocalFolder` in now** so the suite proves two backends. Rejected:
  LocalFolder immediately stresses the two contract debts (int handles, raw
  `isFolder` rows), forcing interface redesign mid-A2 and blowing the
  scoped-commit constraint. Correct order: neutralize the seam (A2), then let D3
  be its first consumer, with the contract suite already standing as its
  acceptance harness.
- **Re-home the exceptions by moving or aliasing** rather than subclassing.
  Rejected: *moving* changes constructor signatures/message text (doctor/logging
  tests break); *aliasing* (`transport.AuthError = private_cloud.AuthError`)
  makes the "neutral" name secretly the httpx-flavored type carrying
  `endpoint`/`error_code` a local backend can't supply, defeating the point.
  Subclassing is additive and byte-identical.
- **Put `login`/`from_env` on the protocol** (the plan's literal list).
  Rejected: classmethods/construction on a `Protocol` are awkward and unchecked,
  and A1 already made "connected client" the contract — login is a construction
  concern the connector owns, and its shape is backend-specific.
- **A name-only `Protocol`, contract suite asserting `isinstance`.** Rejected as
  near-worthless: `runtime_checkable` verifies method *names*, not the payload
  shapes and error semantics that are the actual contract `cloud.py` violated.

## Related

- [Remediation plan](../remediation-plan.md) — item A2 (this ADR is its design),
  D3 (`LocalFolder`, the seam's first second consumer), G6 (named-profile config,
  where config-driven selection and the residual `.api`/unreachable leaks land).
- [ADR-0006](0006-in-process-operations-layer.md) — the `ops` layer whose
  zero-arg `connect` seam this factory plugs into.
- [ADR-0002](0002-agent-facing-cli-contract.md) — the exit taxonomy
  `_cloud_errors` feeds from the neutral exceptions.
