# inkbridge

## Public vs. local

Everything tracked here must be publishable. Anything machine-specific
(credentials, deployment instances, captured device data) goes in
`deploy/local/` — gitignored, never committed.
Exception (ADR-0005): sanitized, no-credential, synthetic-content device
captures MAY be tracked under `tests/fixtures/` solely as test inputs.

## Documentation

Public documentation lives in `docs/` — the ADRs (`docs/adr/`), the CLI
reference (`docs/reference/cli.md`), the remediation plan, and selected
explainers/how-tos. See `docs/README.md` for the map and the citation
conventions. The analysis (research-notes) series and other working material
stay in the local-only archive `deploy/local/docs-archive/` (gitignored), which
also holds the full documentation framework `README.md`. Any new documentation
file, or a substantive edit to an existing one — in `docs/` or in the local
archive — must be reviewed by the `docs-maintainer` subagent before being
considered done.
