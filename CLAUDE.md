# inkbridge

## Public vs. local

Everything tracked here must be publishable. Anything machine-specific
(credentials, deployment instances, captured device data) goes in
`deploy/local/` — gitignored, never committed.

## Documentation

All docs live in `deploy/local/docs-archive/` (local-only; the public repo
has none for now). Any new documentation file, or a substantive edit to an
existing one, must be reviewed by the `docs-maintainer` subagent before
being considered done. See `deploy/local/docs-archive/README.md` for the
framework it enforces.
