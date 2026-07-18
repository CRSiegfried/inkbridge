"""Notebook (.note) to PDF/PNG/text conversion via supernotelib."""

from __future__ import annotations

from pathlib import Path


def note_to_pdf(note_path: Path, pdf_path: Path) -> Path:
    """Convert a .note file to PDF using supernotelib's converter."""
    raise NotImplementedError("Phase 1: wire up supernotelib.converter")


def note_to_text(note_path: Path) -> str:
    """Extract real-time-recognition text from a .note file, if present."""
    raise NotImplementedError("Phase 1: wire up supernotelib's text extraction")
