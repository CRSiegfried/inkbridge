# Deployment-readiness remediation plan

A living planning/remediation tracker — the `roadmap.md` family (local
archive, unpublished): cross-cutting, edited in place. Each row is one issue surfaced by the Fable
code review (2026-07-22), paired with a **validation check** — a concrete,
runnable acceptance criterion that passes only once the issue is actually
resolved. This is a proof harness, not a narrative: if the check passes, the
issue is closed; if it doesn't, it isn't.

Provenance: Fable read all of `src/inkbridge/` and the test suite and
critiqued the repo against its stated purpose (an agent-facing I/O control
plane for the Supernote Manta). This doc is the actionable, checkable form of
that review — the code analogue of
Analysis 0008 (unpublished),
which captured Fable's review of the *research program*.

## How to use this doc

- Every check is written so it can be run today. Most currently **fail** —
  that is expected; the failing check *is* the open ticket, and making it
  pass *is* the definition of done.
- Checks are one of three kinds:
  - **`test`** — a named pytest node that must exist and pass. The node id is
    the contract; write the test to match it.
  - **`grep`** — a structural assertion over the source (an anti-pattern that
    must reach count 0, or a symbol that must exist).
  - **`cli`** — an observable behavior when the built CLI is driven.
- Severity: **S0** ship-blocker (an agent can be handed a confidently wrong
  answer, or the product's stated future is blocked) · **S1** high (blocks
  robust unattended/agent operation) · **S2** medium (generalization or
  hygiene debt).
- Status starts `open` for every row. Flip to `done` only when the paired
  check passes in CI; flip to `wontfix` only with a linked ADR explaining why.

## Summary

| ID | Issue | Sev | Check kind | Status |
|----|-------|-----|-----------|--------|
| C1 | Sparse `.mark` page misattribution | S0 | test | **done** |
| C2 | Decode path: real `.mark` decode now covered | S0 | test | **done** |
| C3 | `ls` truncates at 100 items (no pagination) | S0 | test | **done** |
| A1 | No in-process operations layer (MCP blocked) | S0 | grep+test | **done** |
| A2 | No transport seam; `cloud.py` diverges from `PCClient` | S1 | grep+test | **done** |
| A3 | Non-atomic, unlocked state writes | S1 | test | **done** |
| A4 | `dispatch` not idempotent; no `--replace`/reconcile | S1 | test | **done** |
| A5 | Ledger default is cwd-relative | S1 | test | **done** |
| CT1 | Agent contract half-adopted (6/12 commands off it) | S1 | test | **done** |
| CT2 | `rm` confirmation prompt hangs agents | S1 | cli | **done** |
| D1 | No `wait`/`watch` primitive (the workflow's missing verb) | S1 | test | **done** |
| D2 | `.note` merge path always crashes (`NotImplementedError`) | S1 | test | **done** |
| D3 | No second backend (USB/local-folder) | S2 | test | **done** |
| D4 | No CI / lint+test+proof gate | S1 | grep | **done** |
| D5 | Observability covers only the POST path | S2 | cli | **done** |
| D6 | Packaging hygiene (`py.typed`, public API surface) | S2 | grep | **done** |
| G1 | Decision thresholds global but geometry-dependent | S1 | test | **done** |
| G2 | Device geometry constants leak past `DeviceProfile` | S2 | grep+test | **done** |
| G3 | Closed forms vocabulary; compose is Markdown-only | S2 | test | **done** |
| G4 | Choice grouping by label-parse; dup id on page straddle | S1 | test | **done** |
| G5 | Readback bound to `.pdf.mark` (no `MarkDecoder` seam) | S2 | test | **done** |
| G6 | Single-account, no named-profile config | S2 | test | **done** |
| DOC1 | Docstrings cite gitignored docs unreachable by public | S2 | grep | **done** |

---

## C — Correctness (ship-blocking)

### C1 · Sparse `.mark` page misattribution
**Resolved 2026-07-22** (commit `a484fbe`) via the *detect-and-refuse* branch
of the acceptance below: `read_mark` now raises a typed `SparseMarkError` when
a manifest page is absent from the sparse mark, instead of a bare `IndexError`,
so a sparse multi-page mark fails loudly rather than risking silent
misattribution. This only types the already-failing path — a dense mark decodes
unchanged — so it does **not** reintroduce the structural page-count guard
[ADR-0004](adr/0004-no-page-fiducial.md) declined. The deeper fix that would
*correct* rather than *refuse* (positional page identity) remains deferred per
ADR-0004; `test_sparse_mark_page_identity_refuses_typed` is the gate.

`readback.py:142` `read_mark` — the `.pdf.mark` is sparse (only annotated
pages materialize, no embedded page index), but decode is positional and
assumes a dense mark. Ink on page 2 of a 3-page doc decodes as page 1 and
attributes answers to the wrong questions with full confidence. See
[ADR-0004](adr/0004-no-page-fiducial.md).

**Resolution target:** either (a) a positive page-identity mechanism, or at
minimum (b) detect the mismatch (`mark page count < manifest page count`) and
refuse with a typed error rather than misattribute.

**Validation check** (`test`):
```bash
pytest tests/test_readback.py -k "sparse_mark_page_identity" -q
```
PASS when a test loads a multi-page manifest whose sole inked page is **not**
page 1 and asserts `read_mark` either maps the ink to the correct page id or
raises the typed sparse-mark error — and asserts it never returns an answer
keyed to a page the human did not ink. The sparse case can be **derived from
the C2 fixture** (the `tests/fixtures/sampler_form` 2-page capture): feed a
manifest that references only page 2's cells against the real mark — no fresh
device capture needed.

### C2 · Decode path has no coverage → real `.mark` decode now covered
**Resolved 2026-07-22** (commit `a484fbe`): `test_real_mark_decode_*` decode the
tracked `sampler_form` capture via `read_mark` and assert per-cell coverage +
three-way decision against `sampler_form.readback.json` — the regression gate on
`decode_page_gray`, the supernotelib boundary, and the 1-/0-indexed mapping. The
fixture is tracked under [ADR-0005](adr/0005-tracked-test-fixture-captures.md).

Original issue — the riskiest code (`convert/targeted.py:decode_page_gray`, the
supernotelib boundary, the 1-/0-indexed conversion) *had* zero test coverage. The
*fixture* half was resolved first: a real 2-page device capture (the sanitized
`sampler_form` grocery-list form) was promoted from `deploy/local/captures/`
into **`tests/fixtures/`** — `sampler_form.pdf.mark` (base `sampler_form.pdf`,
`sampler_form.manifest.json`, and the expected `sampler_form.readback.json`
alongside it) — and is now git-tracked under the
[ADR-0005](adr/0005-tracked-test-fixture-captures.md) carve-out (Accepted
2026-07-22; CLAUDE.md amended). `read_mark` over the manifest decodes it
cleanly (2 pages, 8/18 cells `ANSWERED`, nonzero coverages verified
2026-07-22), so `git ls-files 'tests/**/*.mark'` now passes.

The test then landed (see the Resolved note above): `real_mark_decode` decodes
the tracked fixture via `read_mark` and asserts per-cell coverage/decision
against `sampler_form.readback.json`. It asserts on the per-cell values, **not**
the expected JSON's `mark_file` field, which records the original
`deploy/local/captures/` source path and won't match the tracked location.

**Validation check** (`test`):
```bash
test -n "$(git ls-files 'tests/**/*.mark')" && \
  pytest tests/test_readback.py -k "real_mark_decode" -q
```
PASS when the fixture `.mark` is tracked under `tests/` and a test decodes it
via `read_mark` and asserts per-cell coverage/decision within tolerance of
`sampler_form.readback.json`. (The local-only fallback — read
`deploy/local/captures/` and `skip` when absent — was the rejected alternative
under [ADR-0005](adr/0005-tracked-test-fixture-captures.md); the git-tracking
gate above is now the path.)

### C3 · `ls` truncates at 100 items
**Resolved 2026-07-22** (commit `c4d9864`): `ls` now loops `pageNo` to
exhaustion (fetching until a page comes back short of `pageSize`), so a folder
of >100 items lists in full and the `find`/`check_entries`/push-verify joins
that sit on it no longer report present files as missing. `fake_cloud` now
paginates its listing response; `test_ls_paginates_beyond_100` seeds 150 files
and asserts both the full listing and that a page-2 doc reads as `waiting`, not
`missing`.

Original issue — `transport/private_cloud.py` `ls` hardcoded `"pageNo": 1,
"pageSize": 100` and never paginated (the query is now the `pageNo` loop at
`:178`). `find`, push's post-upload verify, `resolve_dir`, and `check_entries`
all sit on `ls`, so a folder with >100 items made `status` report docs
`missing`, made `pull` claim files were absent, and made a *successful* push
fail its own verification.

**Resolution target:** `ls` follows pagination until the folder is exhausted.

**Validation check** (`test`):
```bash
pytest tests/test_private_cloud.py -k "ls_paginates_beyond_100" -q
```
PASS when `tests/fake_cloud.py` serves a folder of >100 entries across
multiple pages and `PCClient.ls` returns every entry (assert the count) and
`check_entries` finds a doc that lives on page 2+.

---

## A — Architecture

### A1 · No in-process operations layer (MCP blocked)
**Resolved 2026-07-23** (commit `8388ac6`, design [ADR-0006](adr/0006-in-process-operations-layer.md)):
`src/inkbridge/ops.py` now holds the orchestration for the three agent-facing
verbs. `ops.dispatch/status/collect` compose the primitives and RETURN the bare
contract payloads (`dispatch.v1` / `collect.v1` / status-row dicts) with no
Click, `echo`, `emit_result`, or exit codes — so the future MCP server calls
`ops` directly instead of shelling out to `--json`. The transport is injected as
a lazy zero-arg connector (the CLI passes `PCClient.from_env`) and the ledger is
injected; `ops` owns the domain writes (ledger `upsert`/`save`, collect's
`answers.json` sidecar) and raises typed domain errors
(`UnknownDocError`/`NoManifestError`/`NoResponseError`, plus the existing
`SparseMarkError`/`FileNotFoundError`/`FileExistsError`), which the CLI maps to
`CliError` + the exit taxonomy. The `dispatch`/`status`/`collect` command bodies
are now thin adapters; behavior is preserved (payloads, exit codes, human output
identical — `test_dispatch`/`test_collect` green). `tests/test_ops.py` drives
`ops.*` against `fake_cloud` + a temp ledger and asserts the payloads, the
domain writes, the typed errors, and (structurally) that the command bodies
delegate. Check run 2026-07-23: `python -c "from inkbridge import ops; …"`
imports clean and `pytest tests/test_ops.py -q` → **9 passed**.

Orchestration lives inside Click command bodies: `cli.py:collect`,
`cli.py:dispatch`, `cli.py:status`. Nothing composes the good primitives
(`dispatch.py`, `answers.py`, `readback.py`) except the CLI, so the README's
"future MCP server" would have to shell out and parse `--json` or
re-implement. This is the single highest-leverage refactor for the agent use
case.

**Resolution target:** an `inkbridge.ops` module whose functions take a
transport + ledger and return `contract` payload dicts; CLI command bodies
become thin renderers over it; the MCP server calls `ops` directly.

**Validation check** (`grep`+`test`):
```bash
python -c "from inkbridge import ops; ops.collect; ops.dispatch; ops.status" && \
  pytest tests/test_ops.py -q
```
PASS when `ops.{collect,dispatch,status}` are importable and callable without
Click, `tests/test_ops.py` drives them against `fake_cloud` and asserts they
return the same payload the CLI emits, and no orchestration branch remains
inline in the three command bodies (the command calls `ops.*` and renders).

### A2 · No transport seam; `cloud.py` diverges from `PCClient`
**Resolved 2026-07-23** (commit `5ef6a16`, design [ADR-0007](adr/0007-transport-protocol-seam.md)):
`transport/base.py` now holds a `Transport` protocol (`ls`/`resolve_dir`/`push`/
`pull`/`delete`) and transport-neutral `AuthError`/`MissingBytesError`; the
private-cloud exceptions **subclass** those bases (additive, message-identical —
`MissingBytesError` stays a `FileNotFoundError`). `transport.connect()` is the
zero-arg connector `ops`/CLI consume (resolving `PCClient.from_env` at call time
so monkeypatches and lazy config both hold); `cli.py` names no concrete backend
(`_cloud_errors` catches the neutral `AuthError`), and the divergent, unused
`transport/cloud.py` stub is deleted. `tests/test_transport_contract.py` runs a
semantic conformance suite parametrized over a backend fixture (one entry today;
D3's `LocalFolder` plugs in). Config-driven selection across named profiles is
deferred to G6 (a single selectable value needs no registry); the residual
`httpx.RequestError`/`doctor.client.api` leaks are recorded as G6/D3 debt in
ADR-0007. Check run 2026-07-23:
`! grep -rnE "private_cloud\.(AuthError|PCClient)|import PCClient" src/inkbridge/cli.py`
→ **clean** and `pytest tests/test_transport_contract.py -q` → **9 passed**
(full gate: 149 passed, ruff clean, proof exit 0).

`cli.py` imports `PCClient` concretely at seven call sites and `_cloud_errors`
keys on `private_cloud.AuthError`. The official-cloud stub
(`transport/cloud.py`) exposes free functions `push`/`pull`/`list_remote`
with an incompatible shape versus `PCClient`'s info-dict-returning methods, so
it cannot be wired in without touching every command.

**Resolution target:** a `Transport` protocol (login/ls/resolve/push/pull/
delete + transport-neutral `AuthError`/`MissingBytesError`), selected from
config; `_cloud_errors` maps neutral exception types.

**Validation check** (`grep`+`test`):
```bash
# no command may name a concrete backend class or its exceptions
! grep -rnE "private_cloud\.(AuthError|PCClient)|import PCClient" src/inkbridge/cli.py && \
  pytest tests/test_transport_contract.py -q
```
PASS when `cli.py` references only the `Transport` protocol / a factory (grep
count 0 for the concrete symbols) and `tests/test_transport_contract.py`
runs the same conformance suite against every registered backend.

### A3 · Non-atomic, unlocked state writes
**Resolved 2026-07-23** (commit `5758e49`): new `inkbridge/atomicio.py` provides
`atomic_write_text` (same-dir temp + `fsync` + `os.replace`; temp cleaned on
failure) and `file_lock` (exclusive advisory lock on a sidecar `.lock`,
`fcntl`/`msvcrt`, best-effort no-op elsewhere). `Ledger.save` and
`InkHashStore.update` now hold the lock across the read-modify-write and write
atomically; `update` additionally re-reads and merges under the lock so
different-page updates from two processes don't clobber. Check run 2026-07-23:
`pytest tests/test_dispatch.py tests/test_readback.py -k "atomic_write_survives_crash" -q`
→ **2 passed** (full gate: 153 passed, ruff clean, proof exit 0).

`dispatch.py:58` `Ledger.save` and `readback.py:191` `InkHashStore.update`
both do bare `write_text` — a crash mid-write corrupts the file, and two
processes (two agents, the stated goal) read-modify-write clobber each other.

**Resolution target:** write-temp-then-`os.replace`, plus an advisory lock
around read-modify-write.

**Validation check** (`test`):
```bash
pytest tests/test_dispatch.py tests/test_readback.py -k "atomic_write_survives_crash" -q
```
PASS when a test monkeypatches the writer to raise *after* the temp file is
written but *before* the rename, and asserts the original ledger/hash-store is
still intact and parseable.

### A4 · `dispatch` not idempotent; no `--replace`/reconcile
**Resolved 2026-07-23** (commit `02a22f8`): `dispatch --replace` (via
`ops.dispatch(replace=True)`) does delete-then-push so re-dispatching an
already-present doc succeeds with one remote copy + one ledger entry; a new
`reconcile REMOTE_PATH` command (`ops.reconcile`) adopts an orphaned remote file
(on the cloud, absent from the ledger) into the ledger from its listing row,
refusing a non-orphan (`already_tracked`→3) or a missing remote (`not_found`→4).
`fake_cloud` now models the real E0322 same-name refusal, which is what makes
the non-idempotency real (and un-skips the transport conformance duplicate-push
assertion); `reconcile` is on the CT1 contract matrix. Check run 2026-07-23:
`pytest tests/test_dispatch.py -k "replace_is_idempotent or reconcile_adopts_orphan" -q`
→ **2 passed** (full gate: 180 passed, ruff clean, proof exit 0).

`dispatch` pushes then saves the ledger (`cli.py:250`→`262`); a crash between
them orphans a remote file, and the retry dies with `FileExistsError`
(`private_cloud.py:221`, E0322) because the private cloud has no overwrite.
No `--replace` (delete-then-push) and no reconcile-orphan path exist. "Retry
after failure" — the most basic agent behavior — is currently hostile.

**Resolution target:** `dispatch --replace` (delete-then-push) and a
`reconcile` command that re-adopts an orphaned remote file into the ledger.

**Validation check** (`test`):
```bash
pytest tests/test_dispatch.py -k "replace_is_idempotent or reconcile_adopts_orphan" -q
```
PASS when dispatching an already-present doc with `--replace` succeeds and
leaves exactly one remote copy + one ledger entry, and `reconcile` turns a
pre-seeded orphan (remote file, no ledger entry) into a tracked entry.

### A5 · Ledger default is cwd-relative
**Resolved 2026-07-23** (commit `5f413e5`): `default_ledger_path` now resolves
to a stable per-user state dir when no `$INKBRIDGE_LEDGER` override is set —
`$XDG_STATE_HOME/inkbridge/ledger.json`, else `~/.local/state/inkbridge` (POSIX)
or `%LOCALAPPDATA%\inkbridge` (Windows), no new dependency. The explicit
override still wins verbatim. Check run 2026-07-23:
`pytest tests/test_dispatch.py -k "ledger_default_is_cwd_independent" -q` →
**1 passed** (full gate: 151 passed, ruff clean, proof exit 0).

`dispatch.py:42` defaults the ledger path relative to the current directory,
so the same command run from two directories silently sees two different
worlds.

**Resolution target:** default to a stable state dir (XDG / platform state
dir) with an env/flag override.

**Validation check** (`test`):
```bash
pytest tests/test_dispatch.py -k "ledger_default_is_cwd_independent" -q
```
PASS when a test resolves the default ledger path from two different working
directories and asserts they are the same path (and outside the cwd unless
explicitly overridden).

---

## CT — Agent-facing contract ([ADR-0002](adr/0002-agent-facing-cli-contract.md))

### CT1 · Contract half-adopted
**Resolved 2026-07-23** (commit `f33d959`): `ls`/`push`/`pull`/`composite`/`merge`
gained `--json` (were bare `ClickException`/untyped exit 1), `status` now wraps
its rows in a `status.v1` `{ledger, entries}` envelope (empty ledger included),
and `readback` emits via `emit_result` as `readback.v1` — so all 14 commands
support `--json`, carry a `schema_version`, and map failures to the exit
taxonomy. `tests/test_contract.py` drives `--json` across every command against
the sampler fixtures + `fake_cloud` (a real `.mark` blob seeded so `pull`/
`collect` decode genuine bytes) and a surface-completeness guard fails if a new
command escapes. `reference/cli.md` brought current (also folding in the A5/A2/
CT2/G4 surface changes). Check run 2026-07-23:
`pytest tests/test_contract.py -k "every_command_json_has_schema_version" -q` →
**14 passed** (full gate: 175 passed, ruff clean, proof exit 0).

`status --json` emits a bare list with no envelope; `readback --json`
hand-rolls its dict (`cli.py:377`) instead of `contract.emit_result`; and
`ls`, `push`, `pull`, `rm`, `merge`, `composite` have no `--json` at all and
raise bare `ClickException` (untyped exit 1). Six of twelve commands are off
the contract that is supposed to be the product's spine.

**Resolution target:** every command supports `--json`, emits through
`emit_result` with a `schema_version` envelope, and maps failures to the
typed exit taxonomy.

**Validation check** (`test`):
```bash
pytest tests/test_contract.py -k "every_command_json_has_schema_version" -q
```
PASS when a parametrized test invokes `--json` on **all** commands against
fixtures/`fake_cloud` and asserts each stdout is a JSON object carrying a
`schema_version`, stderr-only errors, and a documented exit code.

### CT2 · `rm` confirmation prompt hangs agents
**Resolved 2026-07-23** (commit `7a915fc`): `rm` dropped `@click.confirmation_option`
for explicit `-y/--yes` + `--json` flags. With no `-y`, an interactive human
(TTY, human mode) is still prompted, but under `--json` or a non-TTY stdin it
fails fast with a typed `confirmation_required` exit (6) — no stdin block, no
`EOFError`. `-y` deletes non-interactively; failures map to the taxonomy
(`not_found`→4) and `--json` emits an `rm.v1` `{deleted:[…]}` envelope. Check run
2026-07-23: `printf '' | inkbridge rm '/Document/nope.pdf' --json` → exit 6 with
a typed JSON error on stderr, promptly, no prompt (`tests/test_rm.py`, 5 passed;
full gate: 160 passed, ruff clean, proof exit 0).

`cli.py:191` decorates `rm` with `@click.confirmation_option(prompt=…)`; an
agent that forgets `-y` blocks on stdin forever.

**Resolution target:** under `--json` (or non-TTY stdin) `rm` never prompts —
it either honors `-y`/`--yes` or fails with a typed "confirmation required"
exit.

**Validation check** (`cli`):
```bash
printf '' | inkbridge rm '/Document/nope.pdf' --json; echo "exit=$?"
```
PASS when the process exits promptly with a typed JSON error on stderr (no
prompt, no hang, no `EOFError` traceback) and `--yes` performs the delete
non-interactively.

---

## D — Deployment features

### D1 · No `wait`/`watch` primitive
**Resolved 2026-07-23** (commit `030a559`): `inkbridge wait DOC_ID --timeout N`
(`ops.wait`) blocks until the doc's `.pdf.mark` arrives — a bounded long-poll
over the status join with exponential backoff (2 s doubling to 30 s) — exiting
`0` with a `wait.v1` status row on arrival (state responded/changed), `3` (typed
`timeout`) on timeout, `4` for an unknown doc. `sleep`/`monotonic` are injected
so the loop is tested deterministically; `wait` is on the CT1 contract matrix.
Check run 2026-07-23:
`pytest tests/test_wait.py -k "returns_0_on_mark and returns_3_on_timeout" -q` →
**1 passed** (a single node covering both halves, since the check ANDs the two
substrings; full gate: 185 passed, ruff clean, proof exit 0).

The agent loop is dispatch → *wait for the human* → collect, but the only
tool is manually polling `status`. The synchronizing verb of the whole
workflow is missing.

**Resolution target:** `inkbridge wait <doc-id> --timeout N` — bounded
long-poll with backoff, exit 0 when marks arrive, exit 3 on timeout.

**Validation check** (`test`):
```bash
pytest tests/test_wait.py -k "returns_0_on_mark and returns_3_on_timeout" -q
```
PASS when, against `fake_cloud`, `wait` exits 0 once a mark is delivered and
exits 3 (timeout, typed) when none arrives within the window.

### D2 · `.note` merge path always crashes
**Resolved 2026-07-23** (commit `6b3b02c`): merge took the *typed-rejection*
branch of the target — `merge_pdfs` now rejects a `.note` input up front with a
typed `UnsupportedInputError` (a `ValueError` subclass) instead of routing
through the `NotImplementedError` stub; the CLI maps it to a typed
`unsupported_input` contract error (exit 1) on stderr, never an uncaught
traceback. `convert/notebook.py` remains the seam for the future supernotelib
`.note`→PDF conversion (the implement branch). Check run 2026-07-23:
`pytest tests/test_merge.py -k "note_input_is_handled_or_typed_error" -q` →
**1 passed** (asserts the CLI never surfaces `NotImplementedError`; full gate:
186 passed, ruff clean, proof exit 0).

`convert/notebook.py:8` `note_to_pdf` and `:13` `note_to_text` both raise
`NotImplementedError`, yet `merge`'s advertised `.note` support routes
through them, so `merge x.note y.pdf` is a documented feature that always
tracebacks.

**Resolution target:** implement via supernotelib, **or** make `merge` reject
`.note` inputs with a typed error (never an uncaught `NotImplementedError`).

**Validation check** (`test`):
```bash
pytest tests/test_merge.py -k "note_input_is_handled_or_typed_error" -q
```
PASS when `merge` on a `.note` input either produces a valid combined PDF or
exits with a typed "unsupported input" error — asserted to never surface
`NotImplementedError`.

### D3 · No second backend (USB / local-folder)
**Resolved 2026-07-23** (commit `256aeb3`): `transport/local_folder.py` adds
`LocalFolder`, a directory-tree backend implementing the `Transport` protocol
with no network — the first second consumer of the ADR-0007 seam. Semantics
mirror the private cloud where load-bearing (missing folder→`FileNotFoundError`,
same-name push→`FileExistsError`, atomic delete refusal, same listing-row shape)
and it emits the D5 per-verb timing lines. It joins the conformance suite's
`BACKENDS`, so the full semantic contract runs against it, and a dedicated test
blocks httpx to prove a push/pull/ls/delete cycle works with zero network. Check
run 2026-07-23: `pytest tests/test_transport_contract.py -k "local_folder" -q` →
**10 passed** (full gate: 206 passed, ruff clean, proof exit 0).

Everything rides on one dev's private cloud. A watched local folder needs no
network and fully de-risks the transport assumption; it is also the cheapest
proof that A2's seam is real.

**Resolution target:** a `LocalFolder` transport implementing the `Transport`
protocol.

**Validation check** (`test`):
```bash
pytest tests/test_transport_contract.py -k "local_folder" -q
```
PASS when the A2 conformance suite passes against `LocalFolder` with no
network access (assert no httpx calls).

### D4 · No CI / gate
**Resolved 2026-07-23** (commit `0c8c00f`): `.github/workflows/ci.yml` runs the
three-part gate — `ruff check src tests`, `pytest -q`, and `inkbridge proof
tests/fixtures/sampler_form.manifest.json` — on every push and PR (Python 3.10
and 3.12). Check run 2026-07-23:
`git ls-files '.github/workflows/*.yml' | xargs grep -lE 'ruff' | xargs grep -lE 'pytest' | xargs grep -l 'inkbridge proof'`
→ resolves to `ci.yml` (all three steps present).

No CI config is tracked; nothing runs `pytest`, `ruff`, or `inkbridge proof`
on push. `proof` is a device-free end-to-end self-test — free coverage left
on the table.

**Resolution target:** a tracked CI workflow running lint + tests + a
`proof` on a fixture manifest.

**Validation check** (`grep`):
```bash
git ls-files '.github/workflows/*.yml' | xargs grep -lE 'ruff' | xargs grep -lE 'pytest' | xargs grep -l 'inkbridge proof'
```
PASS when a tracked workflow file runs all three steps.

### D5 · Observability covers only the POST path
**Infrastructure landed** (commit `2f8f434`): `obs.py` provides the opt-in
logging surface — `-v/--verbose` (INFO), `-vv` (DEBUG), and
`--log-file`/`INKBRIDGE_LOG`, wired at `cli.py:15,25,27` — silent by default so
stdout stays contract-pure. `contract.py:86-88` (`CliError`) already logs its
exit reason to that opt-in log, and `transport/private_cloud.py:120` logs each
POST with timing (DEBUG) while `:161` logs login (INFO). The scaffolding is done;
what remains is coverage, not building.

**Resolved 2026-07-23** (commit `c0f82fd`): `_call`'s per-request timing line
moved from DEBUG to INFO (surfaced at `-v`, stdout stays contract-pure), and the
two raw byte transfers that bypass `_call` now emit their own timed INFO lines —
`PUT /oss/upload (multipart) → … (N bytes, Nms)` and `GET blob → … (N bytes,
Nms)` — so ls (list/query), upload, and download each carry a timed request line
at `-v`. Default invocation stays byte-silent. Check run 2026-07-23:
`inkbridge -v dispatch … --json` / `… collect … --json` (driven over the mock
transport) → stdout parses as contract JSON and stderr matches
`\b(GET|POST|PUT)\b.*ms` for the ls/upload/download requests
(`tests/test_logging.py` adds the coverage; full gate: 196 passed, ruff clean,
proof exit 0).

**Original issue — per-verb coverage:** only the shared POST path was
instrumented, so the individual verbs `ls`/`resolve`/`find`/`push`/`pull`/
`delete` emitted no line of their own; the multipart upload/download and any GET
reads emitted nothing; and request-level lines surfaced only at `-vv` (DEBUG),
so a plain `-v` showed no per-request activity. (The divergent
`transport/cloud.py` stub this row once cited was deleted by A2, commit
`5ef6a16`; the fix covers `private_cloud` and any future `Transport` backend —
`local_folder` already emits the same per-verb lines, D3.)

**Resolution target:** every transport verb (`ls`/`resolve`/`find`/`push`/`pull`/
`delete`, on every backend implementing the `Transport` protocol) emits one
request+timing line, surfaced at `-v` (INFO) while stdout stays contract-pure.

**Validation check** (`cli`):
```bash
inkbridge -v <cmd that uploads and downloads> --json >/tmp/out 2>/tmp/err; \
  python -c "import json;json.load(open('/tmp/out'))" && \
  grep -qiE '\b(GET|POST|PUT)\b.*ms' /tmp/err
```
PASS when stdout stays valid contract JSON and, under `-v` (not only `-vv`),
stderr carries a timed request line for each of `ls`, upload, and download.

### D6 · Packaging hygiene
**Resolved 2026-07-23** (commit `82f9bb4`): added `src/inkbridge/py.typed`
(wired into setuptools `package-data`) so the package ships typed, and
`__init__.py` now advertises `__all__ = [__version__, ops, transport, Transport,
connect]` — the ops layer and transport seam as the embedder entry points,
resolved lazily via PEP 562 so `import inkbridge` stays cheap. Check run
2026-07-23:
`test -f src/inkbridge/py.typed && python -c "import inkbridge; assert inkbridge.__all__ and inkbridge.__version__"`
→ pass (`tests/test_packaging.py` enforces it; full gate: 190 passed, ruff
clean, proof exit 0).

`__init__.py` defines `__version__` but exports no public API surface, and
there is no `py.typed` marker (the package ships untyped to consumers).

**Resolution target:** add `py.typed`, and export the intended public surface
(at minimum the `ops` functions and `Transport`) from `inkbridge/__init__`.

**Validation check** (`grep`):
```bash
test -f src/inkbridge/py.typed && \
  python -c "import inkbridge; assert inkbridge.__all__ and inkbridge.__version__"
```
PASS when `py.typed` is present and the package advertises an `__all__`.

---

## G — Over-specific; needs a generalization seam

### G1 · Decision thresholds global but geometry-dependent
**Resolved 2026-07-23** (commit `02f28f0`, design [ADR-0008](adr/0008-per-cell-decision-bands.md)):
compose now stamps per-cell `bands` (`{ambiguous_floor, answered_line}`) into
every manifest cell, area-inverse scaled from the calibration tick box at scale
1.0 (`band = base × A_ref/A_cell`), so the *absolute* ink threshold is held
constant across cell sizes and densities. `read_pages` decides from each cell's
manifest bands and consults no decision-relevant global when they are present;
the globals remain only as the base compose scales from and the fallback for
pre-G1 manifests (the tracked `sampler_form` fixture and `proof` are unchanged).
Uniform across all cell types (approved design checkpoint). Check run 2026-07-23:
`pytest tests/test_readback.py -k "thresholds_from_manifest_two_cell_sizes" -q`
→ **1 passed** (two 100×-different-sized cells with the same real mark both
decode ANSWERED via manifest bands, where a single global mis-decides the large
one); verified end-to-end that a fresh dense compose carries correctly-scaled
bands and passes `proof` (full gate: 187 passed, ruff clean, proof exit 0).

`readback.py:39` `AMBIGUOUS_FLOOR` / `:40` `ANSWERED_LINE` were calibrated on
one cell size; the docstring concedes they don't transfer. But `compose`
emits several cell sizes and `--density` rescales them all, changing the
ink-fraction denominator per cell — so a single global pair mis-decides
whenever cell size drifts.

**Resolution target:** `compose` writes per-cell decision bands into the
manifest (it knows each box's geometry); `readback` reads thresholds from the
manifest, using no decision-relevant module global.

**Validation check** (`test`):
```bash
pytest tests/test_readback.py -k "thresholds_from_manifest_two_cell_sizes" -q
```
PASS when a test composes two cells of markedly different sizes at the same
ink coverage and both decode to the correct answer using only manifest-borne
thresholds.

### G2 · Device geometry constants leak past `DeviceProfile`
**Resolved 2026-07-23** (commit `a76791b`): `SCALE`→`DeviceProfile.pt_per_px` and
`ROW`→a `row_h` property derived from a physical `row_mm` target × the profile's
new `ppi` field (still 80 px on the ~300 PPI Manta/Nomad — no layout drift). The
concrete `MANTA`/`NOMAD` instances moved to a new `compose/profiles.py` so the
geometry engine carries no device literals, and `composite.py`'s canvas default
now derives from the `MANTA` profile, not a `1920/2560` literal. Check run
2026-07-23:
`! grep -rnE '\b(1920|2560)\b' src/inkbridge/composite.py src/inkbridge/compose/geometry.py`
→ clean, and `pytest tests/test_geometry.py -k "alt_profile_roundtrips" -q` →
**1 passed** (a synthetic near-square 250-PPI profile composes and rasterizes
back to its own canvas with glyphs in-bbox; full gate: 192 passed, ruff clean,
proof exit 0).

`geometry.py:25` `SCALE` and `:27` `ROW` are module constants outside
`DeviceProfile`; `composite.py:29` hardcodes `1920×2560` at module scope; and
`render_base_page` assumes the 3:4 aspect. A non-Manta panel at a different
PPI breaks the "shared physical constants" premise.

**Resolution target:** PPI, canvas dims, and the pt→px scale live in
`DeviceProfile`; `ROW` derives from a physical millimeter target.

**Validation check** (`grep`+`test`):
```bash
! grep -rnE '\b(1920|2560)\b' src/inkbridge/composite.py src/inkbridge/compose/geometry.py && \
  pytest tests/test_geometry.py -k "alt_profile_roundtrips" -q
```
PASS when no bare canvas literal remains at module scope and a synthetic
non-Manta profile (different PPI/aspect) round-trips compose→geometry.

### G3 · Closed forms vocabulary; compose is Markdown-only
**Resolved 2026-07-23** (commit `6ebddea`, design [ADR-0009](adr/0009-cell-type-registry-and-block-ir.md)):
`compose/celltypes.py` adds a registry (`register(name, render, resolve)` +
`CustomBlock`); `render.render()` gains one seam branch dispatching a
`CustomBlock` to its registered render fn, and `answers._resolve_single`
consults the registry for a registered type's resolver — so a new cell type is
one `register()` call plus an IR block, flowing compose→readback→answers with no
further core edit (`readback` was already type-agnostic). `compose_from_ir(blocks,
…)` is the structured entry point: IR dicts become the same block objects the
Markdown parser produces (`parser.block_from_ir`) and run through one shared
`_compose_blocks` tail, so IR and Markdown can't drift. Check run 2026-07-23:
`pytest tests/test_compose.py -k "compose_from_block_ir and cell_type_registry" -q`
→ **1 passed** (a doc built from IR with no Markdown, a novel `stamp` type driven
compose→readback→answers; full gate: 207 passed, ruff clean, proof exit 0).

Four directives in a bespoke `{kind: …}` micro-syntax (`compose/parser.py`),
cell types dispatched by string; no multi-select / rating / per-line free
text. `compose()` accepts Markdown text only — but an agent would rather emit
the block IR / JSON than author Markdown.

**Resolution target:** a cell-type registry (render fn + resolve fn per type)
and a `compose`-from-block-IR entry point.

**Validation check** (`test`):
```bash
pytest tests/test_compose.py -k "compose_from_block_ir and cell_type_registry" -q
```
PASS when a test builds a document from an IR dict (no Markdown) and renders
it, and a newly registered cell type flows through compose→readback→answers
without edits to the core.

### G4 · Choice grouping by label-parse; duplicate id on page straddle
**Resolved 2026-07-23** (commit `4d42da3`): compose now mints one explicit,
de-duplicated `group` id per choice question and stamps it onto every option
cell; `CellReading` gained a `group` field (threaded through `read_pages`), and
`resolve_answers` groups on that page-independent id — a straddling choice is
one group, and two same-label questions never collide. The label is still parsed
for the option *value*, never for grouping/identity; a manifest predating the
field falls back to the old `(page, question)` key. Check run 2026-07-23:
`pytest tests/test_answers.py -k "choice_straddling_page_break_is_one_group" -q`
→ **1 passed**, plus an end-to-end check that compose emits a shared group id
across a choice's options (full gate: 155 passed, ruff clean, proof exit 0).

`answers.py:resolve_answers` reconstructs choice groups by splitting the cell
label on `": "` and keying on `(page, question)`; worse, `render.py:_choice`
paginates option chunks independently, so a choice whose options straddle a
page break becomes two groups with the **same** id `choice.<slug>` — a
split-vote, duplicate-id result no consumer expects.

**Resolution target:** the manifest carries an explicit per-question `group`
id; grouping keys on it, never on parsed labels.

**Validation check** (`test`):
```bash
pytest tests/test_answers.py -k "choice_straddling_page_break_is_one_group" -q
```
PASS when a choice whose options span a page break resolves to exactly one
answer group with a single unique id, and two questions sharing a label do
not collide.

### G5 · Readback bound to `.pdf.mark`
**Resolved 2026-07-23** (commit `2d75af3`): a `MarkDecoder` protocol
(`page_gray(page) → gray ndarray`, `IndexError` when absent) with the default
`SupernoteMarkDecoder` wrapping `decode_page_gray`; `read_mark` now accepts an
injected `decoder=` (existing callers unchanged — with none it builds the
default from `mark_path`). Because `decode_page_gray` imports supernotelib
lazily, an injected decoder feeds the decision/answers stack with supernotelib
entirely off that path. Check run 2026-07-23:
`pytest tests/test_readback.py -k "answers_from_injected_decoder" -q` → **1
passed** (a PNG-backed fake decoder feeds `read_mark`→`resolve_answers`
end-to-end with `import supernotelib` blocked; full gate: 193 passed, ruff
clean, proof exit 0).

`convert/targeted.py:decode_page_gray` is the only supernotelib touchpoint in
the read path — nearly a seam already, but the decision/answers stack depends
on it concretely.

**Resolution target:** a `MarkDecoder` protocol returning `{page: gray}`; the
decision stack accepts any decoder (so a scanned printout or another brand's
export works).

**Validation check** (`test`):
```bash
pytest tests/test_readback.py -k "answers_from_injected_decoder" -q
```
PASS when a fake `MarkDecoder` built from a plain PNG feeds the answers
pipeline end-to-end with no supernotelib import on that path.

### G6 · Single-account, no named-profile config
**Resolved 2026-07-23** (commit `874e357`, design [ADR-0010](adr/0010-named-profile-config.md)):
`inkbridge/config.py` reads `~/.config/inkbridge/config.toml` (XDG-aware,
`$INKBRIDGE_CONFIG` override) with one `[device.<name>]` section per account →
`Profile(url, email, password, ledger)`, each profile's ledger defaulting to a
per-profile path under the state dir. `transport.connect(profile=None)` resolves
the profile (explicit arg, else `$INKBRIDGE_PROFILE`) and builds a client from
its credentials, falling back to `PCClient.from_env` when unnamed;
`default_ledger_path` follows the active profile so credentials and ledger move
together. `tomli` added as the 3.10 `tomllib` backfill. Check run 2026-07-23:
`pytest tests/test_config.py -k "named_profiles_select_device_and_ledger" -q` →
**1 passed** (two profiles select distinct credentials + per-profile ledgers;
full gate: 211 passed, ruff clean, proof exit 0).

`private_cloud.py:106` `from_env` reads one fixed credential triple; the
ledger has no notion of device/user. One agent driving several tablets (or
several humans) has no seam.

**Resolution target:** named-profile config
(`~/.config/inkbridge/config.toml` with `[device.x]` sections) plus a
per-profile ledger; `from_env` becomes one profile source among several.

**Validation check** (`test`):
```bash
pytest tests/test_config.py -k "named_profiles_select_device_and_ledger" -q
```
PASS when a test with two configured profiles selects the right credentials
and the right per-profile ledger by name.

---

## DOC — Documentation

### DOC1 · Docstrings cite gitignored docs
**Resolved 2026-07-23** (commit `9e06dc1`): all 64 `Analysis NNNN`/`ADR-NNNN`
prefixed citations across 19 shipped source files were rephrased to their
plain-language meaning (the doc-id token dropped), so a public reader is no
longer pointed at gitignored documents. Comments/docstrings only, plus one
`SparseMarkError` message; no code or asserted strings changed. Bare
non-prefixed shorthand (`0012 F6`, `§Decision 3-4`) is left as-is (it cites no
resolvable doc id and does not match the gate). Check run 2026-07-23:
`! grep -rnE 'Analysis[- ]?[0-9]{4}|ADR[- ]?[0-9]{4}' src/inkbridge` → **0
matches** (full gate: 190 passed, ruff clean, proof exit 0).

Source docstrings reference "Analysis 0009/0012", "ADR-0002/0003/0004", etc.,
but per [`CLAUDE.md`](../CLAUDE.md) all docs live in gitignored
`deploy/local/docs-archive/`. A public reader gets citations to documents
that don't exist for them.

**Resolution target:** either publish the referenced ADRs/analyses into the
public tree, or relocate the pointers out of shipped source.

**Validation check** (`grep`):
```bash
# public source must not cite local-only doc ids
! grep -rnE 'Analysis[- ]?[0-9]{4}|ADR[- ]?[0-9]{4}' src/inkbridge
```
PASS when no shipped source file cites a doc id that isn't resolvable from the
public repo (count 0), or the cited docs have been published.

---

## Running the whole harness

Once the tests exist, the full gate is:

```bash
ruff check src tests && \
pytest -q && \
inkbridge proof   # device-free end-to-end self-test
```

Structural (`grep`) checks are cheap enough to encode as their own pytest
nodes (e.g. `tests/test_structure.py`) so the entire table is enforced by one
`pytest` run in CI — see check **D4**.

## Related

- Analysis 0008 (unpublished) —
  Fable's review of the research *program* (this doc is the code analogue).
- [ADR-0002](adr/0002-agent-facing-cli-contract.md) — the contract CT1/CT2
  measure against.
- [ADR-0004](adr/0004-no-page-fiducial.md) — the open page-identity
  decision behind C1.
- [reference/cli.md](reference/cli.md) — the current command surface the contract
  checks extend.
- `roadmap.md` (local archive, unpublished) — where the S0/S1 items should be sequenced.
