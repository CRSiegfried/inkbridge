"""Optional, contract-safe logging for inkbridge.

inkbridge is driven as a subprocess by peers (chiefly the assistant's
``SupernoteAdapter``) over the ADR-0002 ``--json`` contract, which owns **stdout
byte-for-byte**. So logging here NEVER writes to stdout, and is **silent by
default** — the byte-for-byte stdout (and the JSON error envelope on stderr) are
unchanged unless a caller opts in.

Opt-in surfaces (wired by ``cli.main``):

- ``-v/--verbose`` → per-invocation logging to **stderr** (repeat for DEBUG).
- ``--log-file`` / ``INKBRIDGE_LOG`` → the same to a **file**, which never
  touches stdout/stderr.

Contract-safety rule for machine consumers: a process that parses inkbridge's
stderr error envelope must NOT pass ``-v`` (extra stderr lines would corrupt the
parse) — use ``--log-file`` instead. The assistant adapter passes neither by
default, so its stderr stays a clean ``error.v1`` envelope.

Library default is enforced at import: a :class:`~logging.NullHandler` plus
``propagate = False``, so a stray ``warning``/``error`` never escapes to the
root "last resort" handler and leaks onto stderr.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

LOGGER_NAME = "inkbridge"

_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_DATEFMT = "%H:%M:%S"


def get_logger(child: Optional[str] = None) -> logging.Logger:
    """The ``inkbridge`` logger, or a named child (e.g. ``get_logger("cloud")``)."""
    base = logging.getLogger(LOGGER_NAME)
    return base.getChild(child) if child else base


def configure_logging(verbosity: int = 0, log_file: Optional[Path] = None) -> None:
    """Wire handlers for this process per the requested verbosity / log file.

    ``verbosity`` is the ``-v`` count (0 silent, 1 INFO to stderr, ≥2 DEBUG to
    stderr). ``log_file`` (from ``--log-file``/``INKBRIDGE_LOG``) always captures
    at DEBUG to the file. With neither, the logger stays silent (NullHandler).

    Replaces any handlers a previous call attached, so it is safe to call once
    from the CLI group callback without duplicating output.
    """
    logger = logging.getLogger(LOGGER_NAME)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)
    handlers: list[logging.Handler] = []

    stderr_level: Optional[int] = None
    if verbosity >= 2:
        stderr_level = logging.DEBUG
    elif verbosity == 1:
        stderr_level = logging.INFO
    if stderr_level is not None:
        stream = logging.StreamHandler(sys.stderr)
        stream.setLevel(stderr_level)
        handlers.append(stream)

    if log_file is not None:
        file_handler = logging.FileHandler(str(log_file))
        file_handler.setLevel(logging.DEBUG)
        handlers.append(file_handler)

    if handlers:
        for handler in handlers:
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        logger.setLevel(min(handler.level for handler in handlers))
    else:
        logger.addHandler(logging.NullHandler())
        logger.setLevel(logging.WARNING)

    # Never propagate to root: keeps the byte-for-byte stdout/stderr contract even
    # if the embedding process configures its own root logging.
    logger.propagate = False


# Enforce the silent-by-default library posture at import time.
_root_logger = logging.getLogger(LOGGER_NAME)
if not _root_logger.handlers:
    _root_logger.addHandler(logging.NullHandler())
_root_logger.propagate = False


__all__ = ["LOGGER_NAME", "get_logger", "configure_logging"]
