"""Cell-type registry (G3): the extension seam for input cell types beyond the
built-in vocabulary (checkbox/ack/choice/comb/capture).

A registered type supplies two callables — one that draws the cell and stamps
its manifest cell(s), one that resolves a decoded reading to an answer — so a
new type flows compose→readback→answers with no edit to the render or answers
core. ``readback`` is already type-agnostic (pure coverage), so it needs
nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class CellType:
    """A registered input cell type.

    ``render(renderer, block)`` draws the block on the ``Renderer`` and adds its
    manifest cell(s) (via ``renderer._add_cell`` / the drawing primitives).
    ``resolve(cell_reading)`` maps one decoded :class:`~inkbridge.readback.CellReading`
    to an :class:`~inkbridge.answers.Answer`.
    """

    name: str
    render: Callable  # (Renderer, CustomBlock) -> None
    resolve: Callable  # (CellReading) -> Answer


@dataclass
class CustomBlock:
    """A block of a registered (non-built-in) cell type carried through the
    block list — the IR ``{"kind": "<registered>", ...}`` becomes one of these."""

    type: str
    label: str
    ir: dict


REGISTRY: dict[str, CellType] = {}


def register(name: str, *, render: Callable, resolve: Callable) -> None:
    """Register a cell type's render + resolve callables under ``name``."""
    REGISTRY[name] = CellType(name=name, render=render, resolve=resolve)


def is_registered(name: str) -> bool:
    return name in REGISTRY
