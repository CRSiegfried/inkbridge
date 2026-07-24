# CLI reference

Last updated: 2026-07-23. Complete command surface of `inkbridge` as of
compose 0.7.0 (the compose subsystem's own `COMPOSE_VERSION`, stamped into
each manifest as `compose_version` — distinct from the `inkbridge` package
version). Facts only — for the narrative of the dispatch loop see
the how-to on dispatching a form and collecting the response (not in the public docs);
for why the pieces exist see
the vision-alignment explainer (local archive, unpublished).

## Agent-facing contract (ADR-0002)

The primary consumer is an autonomous agent, so every command obeys the
cross-cutting output/exit contract from
[ADR-0002](../adr/0002-agent-facing-cli-contract.md). Adoption is now complete
(CT1): **all commands** — `answers`, `collect`, `compose`, `composite`,
`dispatch`, `doctor`, `ls`, `merge`, `proof`, `pull`, `push`, `readback`,
`reconcile`, `rm`, `status`, `wait` — support `--json`, emit a `schema_version`
envelope, and map failures to the exit taxonomy below. A parametrized contract
test (`tests/test_contract.py`) enforces that no command escapes it.

A compliant command guarantees:

- **`--json` emits one machine-readable document to stdout** and nothing
  else; human-readable text is a separate rendering path over the same
  result. Progress and diagnostics go to stderr.
- **Exit-code taxonomy** — branch on outcome without parsing text:

  | Code | Meaning |
  |---|---|
  | 0 | Success — completed and did something |
  | 3 | Success, no change — nothing needed doing |
  | 4 | Not found — named doc/manifest/remote file does not exist |
  | 5 | Auth expired / not authenticated |
  | 6 | Precondition failed — environment isn't ready (`doctor`-class) |
  | 1 | Unexpected error |
  | 2 | Usage error (Click argument parsing) |

- **Errors are JSON on stderr** under `--json`, never a bare traceback:
  `{"schema_version": "error.v1", "error": {"code", "message"[, "details"]}}`.
  Without `--json`, a one-line `error: <message>` on stderr. Both carry the
  same exit code.
- **Reads never mutate** ledger, remote, or local state.

### Schema-version scheme

Every `--json` payload carries a `schema_version`. The scheme (pinned by
`answers`, the first compliant command):

- **Result payloads: per-command version**, the string `"<command>.v<N>"`
  (e.g. `"answers.v1"`), owned by that command and bumped only when *that*
  command's result schema changes incompatibly. Additive fields do not bump
  it.
- **Error payloads: one shared `"error.v1"`** across all commands — the error
  envelope shape is identical everywhere, so it is versioned once.

## Configuration

All transport commands connect through `transport.connect()` (the backend
seam, ADR-0007), which today builds `PCClient.from_env()` — reading, from the
environment first and then `./.env`:

| Variable | Meaning |
|---|---|
| `INKBRIDGE_CLOUD_URL` | Base URL of the private cloud (e.g. `https://sn.example.com`) |
| `INKBRIDGE_CLOUD_EMAIL` | Account email |
| `INKBRIDGE_CLOUD_PASSWORD` | Account password |

**Named profiles** ([ADR-0010](../adr/0010-named-profile-config.md)): before
falling back to the single-account variables above, `transport.connect()`
resolves the profile named by `$INKBRIDGE_PROFILE` from
`~/.config/inkbridge/config.toml` (`$XDG_CONFIG_HOME`-aware; `$INKBRIDGE_CONFIG`
overrides the file path) — one `[device.<name>]` section per account carrying
`url`/`email`/`password` and an optional `ledger`. A named profile's ledger
defaults to a per-profile path under the state dir below, so credentials and
ledger move together. With no profile set, the env / `./.env` credentials
apply unchanged.

Separately, `INKBRIDGE_LEDGER` sets the dispatch-ledger path. It is read from
the environment only — not `./.env` — and every ledger command also takes
`--ledger PATH`. With neither set, the ledger defaults to a **stable per-user
state dir**, never the cwd (A5): `$XDG_STATE_HOME/inkbridge/ledger.json`, else
`~/.local/state/inkbridge/ledger.json` (POSIX) or `%LOCALAPPDATA%\inkbridge`
(Windows).

## Remote paths and folders

- A *remote path* is `Folder/name.ext` and splits on the **last** slash, so
  nested folders work: `Document/Projects/f.pdf` → folder
  `Document/Projects`, name `f.pdf`.
- Folder arguments (`--to`, `ls FOLDER`) accept the same nested form.
  Resolution walks the server's `directoryId` tree one listing per segment.
- There is **no folder creation**: a missing segment is an error naming it;
  create folders on the device or in the web UI.
- Uploads never overwrite: a same-name push fails with the server's E0322
  mapped to a clear "already exists" error. Push under a new name or `rm`
  the remote copy first.

## Transport commands

### `inkbridge push FILE [--to FOLDER] [--json]`

Upload FILE into FOLDER (default `Document`, the folder that syncs to the
device). Verifies the upload response body *and* re-reads the listing to
compare md5 (the server records listing rows without verifying bytes).
`--json` → `push.v1` `{"source", "folder", "name", "size", "md5"}`. Exit `4`
(`not_found`) when the folder is missing, `1` (`already_exists`) on a same-name
push (no overwrite), `5` auth, `6` unreachable.

### `inkbridge pull REMOTE_PATH -o OUTPUT [--json]`

Download `Folder/name` to OUTPUT, md5-verified against the listing row.
Distinguishes "not on server" from a *phantom row* (listed but bytes
missing server-side, E0321 — benign; reconciliation purges it). `--json` →
`pull.v1` `{"remote", "output", "size", "listing_md5", "bytes_md5", "match"}`.
Exit `4` (`not_found`) when absent, `5` auth, `6` unreachable.

### `inkbridge ls [FOLDER] [--json]`

List the root (folders only, no argument) or any folder. Human output per row:
size (or `<dir>`), md5, name; folders sort first. `--json` → `ls.v1`
`{"folder", "entries": [{"name", "is_folder", "size", "md5"}]}` (same sort).
Exit `4` (`not_found`) when the folder is missing, `5` auth, `6` unreachable.

### `inkbridge rm REMOTE_PATH... [--yes] [--json]`

Delete files from the private cloud (and, on sync, the device). All names in a
folder must exist or nothing in that folder is deleted. Confirmation **never
blocks an agent** (CT2): a human at a TTY (human mode) is prompted, but under
`--json` or a non-TTY stdin a missing `--yes` is a typed
`confirmation_required` exit (`6`), not a hung prompt. `--yes` deletes
non-interactively; `--json` → `rm.v1` `{"deleted": ["Folder/name", …]}`. Exit
`4` (`not_found`) when a name is absent, `5` auth, `6` unreachable/confirmation.

## Compose and readback commands

### Manifest cell categories: page inputs vs. page actions

Manifest cells are one of two kinds, which decides how a read is interpreted:

- **Page inputs** — `checkbox`, `ack`, `choice`, `comb`, `capture`. Carry an
  answer the human gives; `answers` resolves each to a value.
- **Page actions** — `capture_trigger`. A page-level trigger, not a question;
  `answers` excludes it and `dispatch` files it as `trigger_cells` rather than
  `response_cells`. The category is open to further actions.

Both kinds are stamped by the same renderer and read by the same
type-agnostic coverage decoder (`readback`); they diverge only at the semantic
layer. For why the split exists, see
the vision-alignment explainer (local archive, unpublished).

### `inkbridge compose SOURCE.md [-o OUT.pdf] [--manifest M.json] [--device manta|nomad] [--density normal|compact|dense] [--scale FLOAT] [--json]`

Render markdown to a device-canvas PDF plus the input-area manifest
(cell ids/labels/bboxes, trigger slots, doc_id). Default device `manta`
(calibrated); `nomad` renders 1404×1872 with an assumed chrome envelope and
stamps `device.chrome_calibrated: false` into the manifest. Default outputs:
`SOURCE.pdf` and `OUT.manifest.json` beside it.

`--density` picks a layout-scale preset that shrinks fonts, rows, and
tickable boxes uniformly to fit more per page: `normal` (scale 1.0, the
calibrated baseline), `compact` (0.85), `dense` (0.72). The command
**defaults to `dense`**, the device-validated choice
(Analysis 0018 (unpublished)). `--scale
FLOAT` overrides the preset with an exact factor (`<1` packs tighter) for
previewing arbitrary densities. The scale is compose-only — bboxes are
normalized — and is recorded in the manifest under `layout.scale` for
provenance. The library `compose()` default stays at 1.0; only the CLI defaults
to dense.

Each manifest cell also carries a `bands` object
(`{ambiguous_floor, answered_line}`) — the per-cell readback decision
thresholds compose derives from the cell's geometry (G1,
[ADR-0008](../adr/0008-per-cell-decision-bands.md)), area-inverse scaled so the
decode is correct across cell sizes and densities. `readback`/`answers`/
`collect` decide from these per-cell bands, not a global threshold; a manifest
without `bands` falls back to the module calibration constants.

Contract-compliant (see
[Agent-facing contract](#agent-facing-contract-adr-0002)); `schema_version`
`compose.v1`. Under `--json` the result document is
`{"schema_version": "compose.v1", "doc_id", "pdf", "manifest", "pages",
"cells", "device", "scale"}` — the generated `doc_id` as a structured field
(also written into the manifest), the two output paths, the page/cell counts,
and the resolved device/scale. Exit: `0` on success; `1` (`invalid_source`)
when the markdown cannot be rendered (e.g. a non-positive `--scale`).

### `inkbridge readback MANIFEST MARK_FILE [--hash-store H.json] [--update-hashes/--no-update-hashes] [--json]`

Decode a pulled `.pdf.mark` against its manifest: per-cell
blank / ANSWERED / AMBIGUOUS decisions plus per-page ink hashes.
`--hash-store` adds changed/unchanged per page for re-dispatch idempotency;
`--update-hashes` (the default) records the current page hashes into the
store, `--no-update-hashes` polls without recording. `--json` → `readback.v1`
`{"doc_id", "mark_file", "pages": [{"page", "ink_hash", "cells": [...]}]}`
(each page carries `changed` when `--hash-store` is set).

Exit: `0` on success; `1` (`invalid_manifest`) when the manifest is not valid
JSON; `6` (`sparse_mark`) when a manifest page is absent from the mark (a
sparse mark that cannot be read positionally); `2` (Click) when MANIFEST or
MARK_FILE does not exist.

### `inkbridge answers MANIFEST MARK_FILE [--json]`

Semantic, question-level results: groups the per-cell readings `readback`
produces back into the *question* each cell belongs to and resolves each,
so an agent reads "what did the human answer" instead of raw cell coverage.
Sits on top of the readback decoder (same decode as `readback`; no second
decoder). A pure read — never touches ledger, remote, or local state, so a
response can be re-inspected freely. Contract-compliant (see
[Agent-facing contract](#agent-facing-contract-adr-0002)); `schema_version`
`answers.v1`. This is the on-the-fly form; the identical `answers.v1` payload
is what `collect` persists as a `<doc_id>.answers.json` sidecar (ADR-0003).

Under `--json` the result document is
`{"schema_version": "answers.v1", "doc_id", "mark_file", "answers": [...]}`;
each element of `answers` is the per-question object described below.

Per-question resolution by cell type:

| Type | `status` / `value` |
|---|---|
| `choice` | Single-select. One option ANSWERED → `answered`, `value` = option string. Two+ ANSWERED → `conflict`, `value` = the option list. Only AMBIGUOUS → `needs_review`. None → `unanswered`. |
| `checkbox`, `ack` | `answered` with boolean `value`: ANSWERED → `true` (given), BLANK → `false` (not given). |
| `comb`, `capture` | Presence only: ANSWERED → `answered` with `value: null`; BLANK → `unanswered`. The precise comb per-box fill is **not** extracted yet (deferred decoder refinement). |
| any lone AMBIGUOUS | `needs_review`, `value: null`. |
| `capture_trigger` | Excluded — a [page action](#manifest-cell-categories-page-inputs-vs-page-actions), not a question. |

Each answer carries `id`, `type`, `label`, `page`, `status`, `value`, and —
on every outcome except a `checkbox`/`ack` boolean or an `unanswered`
question — a `cells` list of the cell ids to `composite` and look at (so a
resolved `choice` and a `conflict` carry it too, not only `needs_review` and
presence-`answered`). Choice options are grouped by the manifest's explicit
per-question `group` id (G4) — page-independent, so a choice whose options
straddle a page break resolves to one group, and two distinct questions sharing
a label never merge. The cell label `"<question>: <option>"` is still parsed for
the option *value*, never for grouping/identity; a manifest predating the
`group` field falls back to the old `(page, question-label)` key.

Exit: `0` on success (including all-blank), `4` when the manifest or mark file
is absent, `1` (`invalid_manifest`) on a malformed manifest, `6`
(`sparse_mark`) when a manifest page is absent from the mark.

### `inkbridge composite BASE_PDF MARK_FILE -o OUT.png [-p PAGE] [--cell ID --manifest M.json] [--json]`

Overlay decoded mark ink on the rendered base page (the VLM capture
render). `-p` defaults to 1. `--cell` crops to one manifest cell (requires
`--manifest`). Canvas size follows the mark decode, so it is
device-agnostic. `--json` → `composite.v1` `{"output", "width", "height"}`;
exit `4` (`not_found`) when `--cell` names no such cell.

### `inkbridge merge BASE ADDITION -o OUT.pdf [--position append|prepend] [--json]`

Merge two PDF documents into one. `--json` → `merge.v1` `{"output"}`; exit `1`
(`invalid_input`) on a bad `--position`. `.note` inputs are **not** supported
yet: rather than traceback, merge rejects a `.note` input with a typed
`unsupported_input` error (exit `1`) — never an uncaught `NotImplementedError`
(D2). Wiring supernotelib's `.note`→PDF conversion is tracked follow-up;
`convert/notebook.py` remains the seam for it.

## Dispatch-ledger commands

The ledger records what was pushed, from which manifest, and that a
response is expected. It is instance data: gitignored, one JSON file.

### `inkbridge dispatch FILE [--to FOLDER] [--manifest M.json] [--replace] [--ledger L] [--json]`

`push` + record. The manifest defaults to FILE's sibling
`.manifest.json` when present; without one the doc is tracked for arrival
only (`collect` refuses it — exit `6`, nothing to resolve the ink
against). Re-dispatching the same remote folder/name supersedes the old ledger
entry — but the private cloud has no overwrite, so a plain re-dispatch of a
file already on the cloud fails `1` (`already_exists`). **`--replace`** deletes
the existing remote copy first, then pushes (idempotent re-dispatch, A4),
leaving exactly one remote copy and one ledger entry.

Contract-compliant (see
[Agent-facing contract](#agent-facing-contract-adr-0002)); `schema_version`
`dispatch.v1`. Under `--json` the result document is
`{"schema_version": "dispatch.v1", "doc_id", "remote": {"folder", "name"},
"manifest", "response_cells", "trigger_cells", "ledger"}` — the recorded
`doc_id` as a structured field, the remote location, the manifest path (or
`null`), the response/trigger cell counts, and the ledger path. Exit: `0` on
success; `4` (`not_found`) when the remote folder does not exist; `1`
(`already_exists`) on a same-name push (uploads never overwrite — `rm` the
remote copy or push under a new name); `5` auth; `6` when the cloud is
unreachable. (The shared cloud-error mapping — see
[Exit behavior](#exit-behavior) — supplies `5`/`6`.)

### `inkbridge reconcile REMOTE_PATH [--manifest M.json] [--ledger L] [--json]`

Adopt an *orphaned* remote file — one present on the cloud (`REMOTE_PATH` =
`Folder/name`) with no ledger entry, e.g. a `dispatch` that pushed then crashed
before saving the ledger, or a file pushed out of band — into the ledger, so
`status`/`collect` can track it again. It reads the file's listing row and
builds the entry from it (the same md5/size a completed push would record);
`--manifest` lets `collect` later resolve its ink (without one the doc is
tracked for arrival only). `--json` → `reconcile.v1` `{"doc_id", "remote":
{"folder", "name"}, "manifest", "base_md5", "ledger"}`. Exit: `0` on adoption;
`3` (`already_tracked`) when the file is already in the ledger (not an orphan);
`4` (`not_found`) when no such remote file exists; `5` auth; `6` unreachable.

### `inkbridge status [--update] [--json] [--ledger L]`

One listing per distinct folder, then per entry the sidecar join:

| State | Meaning |
|---|---|
| `waiting` | Base file listed, no `.mark` sibling yet — no ink ever |
| `RESPONDED` | `.mark` exists and was never acknowledged |
| `CHANGED` | `.mark` md5 differs from the acknowledged one — new ink |
| `seen` | `.mark` md5 equals the acknowledged one — nothing new |
| `missing` | Base row (or its whole folder) is gone from the server |

`--update` acknowledges every RESPONDED/CHANGED entry's current mark md5,
so later runs report `seen` until new ink lands. A base-md5 drift is
flagged separately (`base_changed` / "join untrustworthy"): annotation
never rewrites the base, so drift means rename/replace/export.

`--json` → `status.v1` `{"ledger", "entries": [{"doc_id", "remote", "state",
"mark_md5", "base_changed"}]}` (an envelope, not a bare list; an empty ledger
returns `entries: []`, not a human line). Exit `5` auth, `6` unreachable.

### `inkbridge wait DOC_ID [--timeout SECONDS] [--ledger L] [--json]`

Block until DOC_ID's `.pdf.mark` response arrives — the synchronizing verb of
the dispatch → (human inks) → collect loop (D1), replacing a manual `status`
poll. Bounded long-poll with exponential backoff (2 s, doubling to 30 s);
`--timeout` defaults to 300 s. Exit `0` with a `wait.v1` status row (the same
`{doc_id, remote, state, mark_md5, base_changed}` fields) once a mark lands
(state `responded`/`changed`); `3` (`timeout`) when none arrives in the window;
`4` for an unknown doc_id; `5` auth; `6` unreachable.

### `inkbridge collect DOC_ID [-o DIR] [--json] [--ledger L]`

Pull DOC_ID's `.pdf.mark` into DIR (default `responses/`) and **materialize
its answers** ([ADR-0003](../adr/0003-materialized-answers-artifact.md)):
resolve the ink against the entry's manifest (same resolver as `answers`) and
write a `<doc_id>.answers.json` sidecar beside the mark — the `answers.v1`
document plus a `mark_md5` field recording the ink state it reflects. Reading
response state afterward is just parsing that file.

`collect` does **not** acknowledge or advance the ledger — it is a
materialize, not a state transition. To detect staleness, a consumer diffs the
sidecar's `mark_md5` against the current mark md5 that `status` reports.
Blocking until a response first arrives is `wait`'s job (D1); reacting to
*later* changes is still left to the agent loop or an external file-watcher.

Contract-compliant (see
[Agent-facing contract](#agent-facing-contract-adr-0002)). Under `--json`,
stdout is a `collect.v1` envelope: the `answers.v1` payload fields (`doc_id`,
`mark_file`, `mark_md5`, `answers`) plus `answers_file` naming the sidecar.
Exit: `0` when a response was pulled and resolved; `3` (no change) when there
is no response yet; `4` when DOC_ID is not in the ledger; `6` when the doc was
dispatched without a manifest (`no_manifest`) or the pulled mark is sparse
(`sparse_mark`).

## Diagnostics

Two self-tests, deliberately disjoint in what they exercise: `doctor` is the
cloud/auth/connectivity probe (needs configuration, contacts the cloud, no
device); `proof` is the manifest/readback decode check (needs a manifest,
contacts nothing). Neither needs a device or a human.

### `inkbridge doctor [--json]`

Readiness probe for the integration before you dispatch: it logs in with the
configured `INKBRIDGE_CLOUD_*` credentials and lists the root — read-only, the
one round-trip it makes. Answers "are we configured, reachable, and
authenticated?" without touching a document, a ledger, or a device.

Contract-compliant (see
[Agent-facing contract](#agent-facing-contract-adr-0002)); `schema_version`
`doctor.v1`. Under `--json` the result document is
`{"schema_version": "doctor.v1", "ok": true, "url", "checks": [...]}`, each
check `{"name", "ok", "detail"}` (`authentication`, then `connectivity`).

Exit: `0` ready; `5` auth (credentials rejected or expired); `6` precondition
— missing `INKBRIDGE_CLOUD_*` configuration (`config_missing`) or the cloud
unreachable (`unreachable`, e.g. DNS/connect/timeout). Because doctor is the
purpose-built producer of the auth/connectivity signal, it is the command an
agent runs to diagnose setup, rather than inferring it from a document command.

### `inkbridge proof MANIFEST [--json]`

Device-free decode self-test: stamp synthetic ink into every manifest cell,
read it back, and assert every cell reads ANSWERED — catching manifest/readback
drift with no device and no human. It contacts no cloud, so it exercises
neither credentials nor connectivity (that is `doctor`'s job).

Contract-compliant; `schema_version` `proof.v1`. Under `--json` the result is
`{"schema_version": "proof.v1", "doc_id", "pages", "cells", "ok", "failures": [...]}`,
each failure the cell id/page/type/coverage/decision that did not read
ANSWERED. Exit: `0` when every cell passes; `1` when any cell fails; `4` for a
missing manifest.

## Exit behavior

- **Cross-cutting cloud failures.** Every command that contacts the private
  cloud (`push`, `pull`, `ls`, `rm`, `dispatch`, `reconcile`, `status`, `wait`,
  `collect`, `doctor`) maps a rejected/expired credential to `5` (auth) and an
  unreachable cloud to `6` (precondition), rather than letting either escape
  as an uncaught traceback. Under `--json` the error envelope carries
  `code: "auth"` / `code: "unreachable"`. A traceback from these paths is a
  bug.
- **Corrupt ledger.** Every command that reads the ledger (`dispatch`,
  `reconcile`, `status`, `wait`, `collect`) maps a truncated or hand-edited
  ledger file to a typed precondition error — exit `6`, code
  `ledger_corrupt` — never an uncaught `JSONDecodeError` traceback.
- **Every command** now honors the full exit-code taxonomy above — e.g. `3`
  no-change, `4` not-found, `5` auth, `6` precondition, `1` other errors, `2`
  for a Click usage/argument error — with JSON errors on stderr under `--json`
  (CT1). There are no remaining plain-text-only commands.
