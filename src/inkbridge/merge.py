"""PDF <-> notes chaining — the feature Supernote's own software lacks.

Phase 3 on the roadmap. The PDF-merge half is real and usable today. `.note`
inputs are **not** supported yet (the `convert.notebook` converter is still a
Phase 1 stub); rather than route through it and traceback with a bare
``NotImplementedError``, merge rejects a `.note` input up front with a typed
:class:`UnsupportedInputError` (D2). Wiring supernotelib's `.note`→PDF
conversion in is the tracked follow-up.
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader, PdfWriter


class UnsupportedInputError(ValueError):
    """An input file type merge can't handle yet (today: `.note`). A
    ``ValueError`` so callers already catching that keep working, but distinct
    so the CLI can map it to its own typed exit code rather than a traceback."""


def _as_pdf(path: Path, tmp_dir: Path) -> Path:
    if path.suffix.lower() == ".note":
        raise UnsupportedInputError(
            f"merging .note inputs is not supported yet ({path.name}); convert it "
            "to PDF first, or merge PDF inputs. (.note→PDF is tracked follow-up.)")
    return path


def merge_pdfs(
    base: Path,
    addition: Path,
    output: Path,
    *,
    position: str = "append",
    tmp_dir: Path | None = None,
) -> Path:
    """Combine two PDF documents into one.

    `position` is "append" (addition's pages go after base's) or "prepend".
    A `.note` input raises :class:`UnsupportedInputError` (not yet supported).
    """
    if position not in ("append", "prepend"):
        raise ValueError(f"position must be 'append' or 'prepend', got {position!r}")

    tmp_dir = tmp_dir or output.parent
    base_pdf = _as_pdf(base, tmp_dir)
    addition_pdf = _as_pdf(addition, tmp_dir)

    writer = PdfWriter()
    ordered = [base_pdf, addition_pdf] if position == "append" else [addition_pdf, base_pdf]
    for pdf_path in ordered:
        reader = PdfReader(pdf_path)
        for page in reader.pages:
            writer.add_page(page)

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "wb") as f:
        writer.write(f)
    return output
