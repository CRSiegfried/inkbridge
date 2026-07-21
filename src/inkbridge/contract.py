"""Agent-facing CLI contract (ADR-0002): the shared machine-legibility
scaffolding every command inherits instead of re-implementing.

Provides the four cross-cutting pieces the ADR mandates:

- ``emit_result`` — the ``--json`` rendering path: the *only* thing written to
  stdout in JSON mode, a versioned document; ``log`` keeps progress on stderr.
- ``Exit`` — the exit-code taxonomy (0 ok / 3 no-change / 4 not-found /
  5 auth / 6 precondition / 1 error / 2 usage), so an agent branches on
  outcome without parsing text.
- ``CliError`` — a failure that renders as one line (human) or a JSON object
  on *stderr* (``--json``), carrying its own exit code; never a bare traceback.

Schema-version scheme (the ADR left this open for the first command to pin
down; ``answers`` pins it):

- **Result payloads carry a per-command schema_version**, the string
  ``"<command>.v<N>"`` (e.g. ``"answers.v1"``). The version is *owned by that
  command* and bumped only when THAT command's result schema changes
  incompatibly; additive fields never bump it. A global version was rejected
  because it would force every command's consumers to re-check on any one
  command's change.
- **Error payloads share one cross-cutting schema**, :data:`ERROR_SCHEMA`
  (``"error.v1"``), because the error envelope shape is identical across every
  command — the one place a shared version is correct.

Each command documents its own ``schema_version`` and payload in
``reference/cli.md`` as it is built.
"""

from __future__ import annotations

import json
from enum import IntEnum

import click


class Exit(IntEnum):
    """ADR-0002 exit-code taxonomy. Values are the process exit codes; an
    agent branches on these without parsing output."""

    OK = 0            # completed and did something
    NO_CHANGE = 3     # succeeded, nothing needed doing (idempotent no-op)
    NOT_FOUND = 4     # named doc/manifest/remote file does not exist
    AUTH = 5          # auth expired / not authenticated
    PRECONDITION = 6  # environment isn't ready (doctor-class)
    ERROR = 1         # unexpected error
    USAGE = 2         # usage error (reserved for Click's argument parsing)


# Shared, cross-cutting error-envelope schema (see module docstring): every
# command's --json failure serializes to this one shape, versioned here.
ERROR_SCHEMA = "error.v1"


class CliError(click.ClickException):
    """A contract-compliant failure (ADR-0002 §Decision 3-4).

    Carries a stable machine ``code`` and one of the :class:`Exit` statuses,
    and renders to *stderr* — a one-line ``error: ...`` in human mode, or a
    ``{"schema_version": "error.v1", "error": {...}}`` object under ``--json``.
    Raise it from a command instead of ``click.ClickException`` so the exit
    code and the JSON error envelope both come out right.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str,
        exit_status: Exit = Exit.ERROR,
        as_json: bool = False,
        details: dict | None = None,
    ):
        super().__init__(message)
        self.exit_code = int(exit_status)  # click reads self.exit_code
        self.code = code
        self.as_json = as_json
        self.details = details or {}

    def show(self, file=None) -> None:  # noqa: ARG002 - click passes a file arg
        if self.as_json:
            error = {"code": self.code, "message": self.format_message()}
            if self.details:
                error["details"] = self.details
            click.echo(
                json.dumps({"schema_version": ERROR_SCHEMA, "error": error}, indent=2),
                err=True,
            )
        else:
            click.echo(f"error: {self.format_message()}", err=True)


def emit_result(payload: dict, schema_version: str) -> None:
    """Write a command's JSON result document to stdout — the ONLY thing on
    stdout under ``--json`` (ADR-0002 §Decision 1). ``schema_version`` is
    stamped in as the leading key."""
    click.echo(json.dumps({"schema_version": schema_version, **payload}, indent=2))


def log(message: str) -> None:
    """Emit a progress/diagnostic line to stderr, so stdout stays the pure
    result document under ``--json`` (ADR-0002 §Decision 1)."""
    click.echo(message, err=True)
