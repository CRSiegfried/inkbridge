# ADR-0002: Agent-facing CLI output and exit-code contract

Status: Accepted
Date: 2026-07-20

## Context

The primary consumer of the `inkbridge` CLI is an autonomous AI agent that
drives the whole document lifecycle — compose, dispatch, watch, react,
retire — not a human at an interactive prompt.
Analysis 0017 (unpublished)
inventories the command families that surface needs to grow, and its
finding 10 is that a machine-legibility contract matters more than any single
new verb: the commands are only as composable as their output and exit codes
are predictable.

The current surface predates that framing. Commands print human-readable
prose to stdout (`click.echo(f"Wrote {result}")`), signal failure only
through Click's default nonzero exit, and mix a "nothing happened" outcome in
with success. An agent consuming that has to scrape prose, can't branch on
outcome without parsing text, and can't distinguish "no response yet" from
"succeeded" from "auth expired" by exit code alone. Every new command built
without a settled contract widens that inconsistency, and because the contract
constrains the shape of *every* command that follows, it has to be decided
before the loop-closing verbs (`answers`, `watch`, `close`) are built, not
retrofitted after.

This is one decision — the cross-cutting I/O contract — deliberately split out
from the individual command designs in Analysis 0017 so it can be settled
once and inherited.

## Decision

We will adopt a single output-and-exit contract that every `inkbridge`
command obeys, new commands from the outset and existing commands as they are
touched:

1. **`--json` on every command.** Each command emits a machine-readable JSON
   document to stdout under `--json`. Without the flag, output is
   human-readable text; the two are separate rendering paths over the same
   result, never interleaved. Nothing but the JSON document goes to stdout in
   `--json` mode (logs and progress go to stderr).

2. **Stable, versioned schemas.** Every `--json` payload carries a
   `schema_version` field. Schemas are additive within a version; a
   breaking change bumps the version. Each command's schema is documented in
   [`reference/cli.md`](../reference/cli.md) as the command is built.

3. **A defined exit-code taxonomy**, so an agent branches on outcome without
   parsing output:

   | Code | Meaning |
   |------|---------|
   | 0 | Success — the operation completed and did something |
   | 3 | Success, no change — nothing needed doing (idempotent no-op, no new ink) |
   | 4 | Not found — named doc/manifest/remote file does not exist |
   | 5 | Auth expired / not authenticated |
   | 6 | Precondition failed — the environment isn't ready (`doctor`-class) |
   | 1 | Unexpected error |
   | 2 | Usage error (reserved for Click's argument parsing) |

   "Success, no change" is distinct from plain success on purpose: a poll or
   a `redispatch` that finds nothing to do must be distinguishable from one
   that acted, or the agent can't tell whether to react.

4. **Errors as JSON on stderr.** Under `--json`, a failure emits a JSON
   object to *stderr* (`{"error": {...}, "schema_version": ...}`) alongside
   the exit code — never a bare traceback, never error text mixed into the
   stdout payload.

5. **Reads never mutate state.** No command changes ledger, remote, or local
   state as a side effect of reporting. State transitions are always an
   explicit, separately-invokable action (this is the principle behind the
   `collect` ack split in Analysis 0017 finding 3).

The contract is a hard rule enforced in review, not a per-command option.

## Consequences

**Easier:** an agent can drive any command uniformly — call with `--json`,
branch on the exit code, parse a versioned payload — without per-command
special-casing. New commands inherit legibility for free instead of
reinventing output shape. "No response yet" vs. "done" vs. "auth expired"
becomes a code comparison, not a text scrape. The read/mutation split means
an agent can always re-inspect a response without fear of advancing state.

**Harder:** every command now carries two rendering paths (human and JSON)
and must be conscious of which stream it writes to — more surface per command
than a single `click.echo`. Existing commands need retrofitting as they're
touched, so for a while the surface is mixed (contract-compliant new commands
alongside legacy prose ones); we accept that transitional inconsistency
rather than block feature work on a big-bang migration. The exit-code
taxonomy must be enumerated centrally and kept honest — a command that
invents its own codes silently breaks the contract.

**Giving up:** freedom to shape each command's output for its own
convenience. Output shape is now a shared, versioned interface with the cost
that comes with any interface — you can't change it casually.

**Deferred, not solved here:** the individual command designs (signatures,
per-command schemas) remain Analysis 0017's and `reference/cli.md`'s job;
this ADR fixes only the cross-cutting contract they all sit inside. The exact
`schema_version` scheme (per-command vs. global) is left to the first
command's implementation to pin down, then documented as the pattern.

## Alternatives considered

- **No contract — shape each command's output ad hoc** (status quo):
  rejected. It is exactly what makes the current surface hard for an agent to
  consume, and the cost compounds with every command added.
- **JSON as the only output, no human text mode:** rejected. A human still
  needs to run these commands during development and debugging; forcing them
  to read raw JSON for every `ls` or `status` is a needless downgrade when a
  second rendering path is cheap.
- **Success/failure only (0 / nonzero), signal everything else in the JSON
  body:** rejected. An agent scripting a poll loop or a `wait` wants to
  branch on outcome from the exit code alone (`wait --until responded`'s
  whole point is a timeout-vs-met distinction in the code); burying
  "no change" and "not found" inside the payload forces a parse on the hot
  path and defeats simple shell composition.
- **A machine-readable envelope on stdout for errors too** (errors in the
  stdout payload rather than stderr): rejected. Mixing error and result on
  one stream means a consumer can't trust that stdout under `--json` is
  always the result document; separating streams keeps "stdout = result,
  stderr = diagnostics" invariant.

## Related

- Analysis 0017 (unpublished) —
  finding 10 (the contract) and finding 3 (the read/mutation split) that this
  ADR promotes to a decision; the individual command families it governs.
- [`reference/cli.md`](../reference/cli.md) — where each command's flags and
  per-command JSON schema are documented as built.
