from pathlib import Path

from pypdf import PdfReader, PdfWriter

from inkbridge.merge import merge_pdfs


def _make_pdf(path: Path, num_pages: int) -> Path:
    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=200, height=200)
    with open(path, "wb") as f:
        writer.write(f)
    return path


def test_merge_pdfs_append(tmp_path: Path) -> None:
    base = _make_pdf(tmp_path / "base.pdf", 2)
    addition = _make_pdf(tmp_path / "addition.pdf", 3)
    output = tmp_path / "combined.pdf"

    result = merge_pdfs(base, addition, output, position="append")

    assert result == output
    assert len(PdfReader(output).pages) == 5


def test_merge_pdfs_prepend(tmp_path: Path) -> None:
    base = _make_pdf(tmp_path / "base.pdf", 2)
    addition = _make_pdf(tmp_path / "addition.pdf", 3)
    output = tmp_path / "combined.pdf"

    merge_pdfs(base, addition, output, position="prepend")

    assert len(PdfReader(output).pages) == 5


def test_merge_pdfs_rejects_bad_position(tmp_path: Path) -> None:
    base = _make_pdf(tmp_path / "base.pdf", 1)
    addition = _make_pdf(tmp_path / "addition.pdf", 1)
    output = tmp_path / "combined.pdf"

    try:
        merge_pdfs(base, addition, output, position="sideways")
    except ValueError:
        return
    raise AssertionError("expected ValueError for bad position")
