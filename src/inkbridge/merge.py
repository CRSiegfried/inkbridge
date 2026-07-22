"""PDF <-> notes chaining — the feature Supernote's own software lacks.

Phase 3 on the roadmap. The PDF-merge half is real and usable today;
.note inputs go through convert.notebook.note_to_pdf first, which is still a
Phase 1 stub. Merges go through a PDF intermediate rather than writing to
.note directly.
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader, PdfWriter

from inkbridge.convert.notebook import note_to_pdf


def _as_pdf(path: Path, tmp_dir: Path) -> Path:
    if path.suffix.lower() == ".note":
        out = tmp_dir / (path.stem + ".pdf")
        return note_to_pdf(path, out)
    return path


def merge_pdfs(
    base: Path,
    addition: Path,
    output: Path,
    *,
    position: str = "append",
    tmp_dir: Path | None = None,
) -> Path:
    """Combine two documents (PDF and/or .note) into one PDF.

    `position` is "append" (addition's pages go after base's) or "prepend".
    .note inputs are converted to PDF first via supernotelib.
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
