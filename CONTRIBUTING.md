# Contributing to inkbridge

Thanks for your interest. inkbridge is a control plane for the Supernote
Manta: it pushes documents to the device, pulls handwritten annotations back,
and bridges PDFs with notes pages. This guide covers setup, the checks your
change must pass, and the conventions the project holds itself to.

## Scope

inkbridge deliberately builds on existing libraries (e.g. `supernotelib`)
rather than reimplementing `.note` parsing. Before proposing a large addition,
skim `docs/ecosystem.md` (the prior-art survey) and `docs/adr/` (the decisions
behind the design) — the thing you need may already have a home or a decision.

## Public vs. local — read this first

Everything committed here must be publishable. Anything machine-specific —
credentials, deployment instances, captured device data — belongs in
`deploy/local/` (gitignored) and must never appear in a commit. The one
exception (ADR-0005): sanitized, no-credential, synthetic-content device
captures may live under `tests/fixtures/`, solely as test inputs.

## Development setup

Requires Python 3.11 or newer.

```sh
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev,mcp]'
```

## The gate — run it before you push

CI runs the same three checks on Python 3.11 and 3.13. Run them locally first:

```sh
ruff check src tests                                        # lint
pytest -q                                                   # tests
inkbridge proof tests/fixtures/sampler_form.manifest.json   # device-free self-test
```

All three must pass, and `proof` must exit 0. Ruff is pinned (the `dev` extra
in `pyproject.toml`) so local and CI never drift — use the pinned version, not
a system-wide ruff.

## Pull requests

- Branch off `master` and open a pull request; direct pushes to `master` are
  gated.
- The gate above must be green before a PR can merge.
- Keep each PR focused, and explain the *why* in the description.

## Commit messages

Use a short type prefix and an imperative summary; put non-obvious reasoning in
the body. Prefixes already in use here include `build`, `ci`, `docs`, `lint`,
and `mcp`; use `fix` for a bug fix. For example:

```
build: raise Python floor to 3.11, drop the tomli backport
```

## Documentation changes

Public docs live in `docs/` — Diataxis how-tos/reference/explainers plus
`docs/adr/` for decisions; see `docs/README.md` for the map. Any new doc file
or substantive edit must be reviewed by the `docs-maintainer` before it is
considered done (the rule in `CLAUDE.md`). Don't rewrite an accepted ADR's
Context or Decision after the fact — supersede it with a new ADR, or, for an
anticipated decision-preserving cleanup, add a dated update note above the
Context section.

## License

By contributing, you agree that your contributions are licensed under the
project's MIT License (see [`LICENSE`](LICENSE)).
