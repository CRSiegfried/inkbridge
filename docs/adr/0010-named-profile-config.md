# ADR-0010: Named-profile config (`config.toml`) with a per-profile ledger

Status: Accepted
Date: 2026-07-23

> **Update 2026-07-24:** The `tomli` backport mentioned in the Decision and
> Consequences below has been removed. The project floor moved to Python 3.11,
> where `tomllib` is in the standard library, so `inkbridge.config` now imports
> `tomllib` unconditionally — this is the anticipated cleanup the Consequences
> section flagged ("dropped once 3.10 is"), not a new decision. The
> named-profile design is unchanged.

## Context

[Remediation item G6](../remediation-plan.md) targets the single-account
assumption. `PCClient.from_env` reads one fixed `INKBRIDGE_CLOUD_{URL,EMAIL,
PASSWORD}` triple, and the ledger has no notion of device or user, so one agent
driving several tablets (or several humans on one machine) has no seam — every
dispatch lands in the same credential world and the same ledger. [ADR-0007](0007-transport-protocol-seam.md)
deferred config-driven selection to here and built `transport.connect()` as the
single place a backend is chosen, precisely so this could drop in without
touching the commands.

## Decision

We will add **named-profile configuration** in a TOML file, each profile
carrying its own credentials **and its own ledger**, selected by name.

**`~/.config/inkbridge/config.toml`** (honoring `XDG_CONFIG_HOME`, overridable
with `$INKBRIDGE_CONFIG`) with one section per device/account:

    [device.tablet-a]
    url = "https://sn.example.com"
    email = "a@example.com"
    password = "…"
    ledger = "…"          # optional; defaults per-profile (below)

**`inkbridge.config`** parses it (`tomllib` on 3.11+, `tomli` on 3.10) into
`Profile(name, url, email, password, ledger)`. A profile's ledger defaults to a
**per-profile path** under the state dir (`<state>/profiles/<name>/ledger.json`)
when not set, so two profiles never share a ledger by accident.

**Selection is by name, from two sources.** `transport.connect(profile=None)`
resolves a profile — the explicit argument, else the `$INKBRIDGE_PROFILE`
environment default — and builds a client from that profile's credentials; with
no profile it falls back to `PCClient.from_env` (the unnamed, single-account
default, unchanged). `dispatch.default_ledger_path` likewise resolves the active
profile's ledger when `$INKBRIDGE_PROFILE` is set (still overridable by the
explicit `$INKBRIDGE_LEDGER` / `--ledger`), so credentials and ledger move
together under one name. `from_env` thus becomes **one profile source among
several**, not the only one.

The command surface is unchanged: selection rides on `connect`'s seam and the
ledger default, both already the single chokepoints, so no per-command `--profile`
flag is added — setting `$INKBRIDGE_PROFILE` (or calling `connect(profile=…)`
programmatically) switches the whole world.

## Consequences

- **Easier:** one operator drives several tablets/accounts by name — each with
  isolated credentials and an isolated ledger — with no code change per account.
  The transport seam and the ledger default absorb it, so the commands stay put.
- **Harder / given up:** a new config file and format is now part of the contract
  (a second place, besides env vars, that credentials live — and a plaintext
  password on disk, the same exposure `.env` already had, now blessed). A `tomli`
  dependency is added for Python 3.10 (dropped once 3.10 is). Two selection
  inputs (`$INKBRIDGE_PROFILE` and the `connect` argument) plus the `$INKBRIDGE_
  LEDGER` override interact, so the precedence has to stay documented and tested.
- **No CLI flag yet:** selection is env/programmatic only; a per-invocation
  `--profile` flag is a later addition if the env default proves too coarse.

## Alternatives considered

- **Env-selected active profile only** (`$INKBRIDGE_PROFILE` picking among
  `INKBRIDGE_<NAME>_CLOUD_*` triples), no TOML file. Rejected at the design
  checkpoint: it avoids a new file format but scatters N accounts across a
  combinatorial env-var namespace and has nowhere clean to record a per-profile
  ledger — the plan's `~/.config/.../config.toml` is the better home. (The
  `$INKBRIDGE_PROFILE` *selector* is kept; only the per-profile-env-triple
  storage is rejected.)
- **A per-command `--profile` flag** threaded through every cloud command.
  Rejected as scope creep for now: `connect` and the ledger default are already
  the two chokepoints, so an env/programmatic selector switches everything with
  no per-command surface; the flag can be layered on later.
- **Keep single-account; document running N checkouts/env files.** Rejected: it
  pushes the multi-device story onto the operator's shell hygiene and gives the
  ledger no per-account identity, which is exactly the seam G6 asks for.

## Related

- [Remediation plan](../remediation-plan.md) — item G6 (this ADR is its design),
  and A5 (the per-user state dir the per-profile ledger nests under).
- [ADR-0007](0007-transport-protocol-seam.md) — the `connect` seam this selects
  through; config-driven selection was explicitly deferred to here.
