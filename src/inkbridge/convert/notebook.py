"""Notebook (.note) to PDF/PNG/text conversion via supernotelib.

inkbridge intentionally does not reimplement `.note` parsing; it builds
on `supernotelib`.
"""

from __future__ import annotations

from pathlib import Path


def note_to_pdf(note_path: Path, pdf_path: Path) -> Path:
    """Convert a .note file to PDF using supernotelib's converter.

    Not yet implemented. As a workaround, convert the `.note` file to
    PDF directly with an external tool such as supernotelib's own CLI
    (``python -m supernotelib convert``) until this is wired up.
    """
    raise NotImplementedError(
        "note_to_pdf is not yet implemented. As a workaround, convert the "
        ".note file to PDF with an external tool such as supernotelib's "
        "CLI (`python -m supernotelib convert`)."
    )


def note_to_text(note_path: Path) -> str:
    """Extract real-time-recognition text from a .note file, if present.

    Not yet implemented. As a workaround, use supernotelib directly (its
    CLI or Python API) to extract any recognized text from the file.
    """
    raise NotImplementedError(
        "note_to_text is not yet implemented. As a workaround, use "
        "supernotelib directly (its CLI or Python API) to extract any "
        "recognized text from the .note file."
    )
