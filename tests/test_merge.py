import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from pypdf import PdfReader, PdfWriter

from inkbridge.merge import UnsupportedInputError, merge_pdfs


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


def test_note_input_is_handled_or_typed_error(tmp_path: Path) -> None:
    # D2: a .note input must NEVER surface an uncaught NotImplementedError. It
    # either produces a valid combined PDF (if .note→PDF is implemented) or
    # exits with a typed "unsupported input" error. Today: the typed rejection.
    base = _make_pdf(tmp_path / "base.pdf", 1)
    note = tmp_path / "scribble.note"
    note.write_bytes(b"note SN_FILE_VER placeholder bytes")
    output = tmp_path / "combined.pdf"

    # Library layer: a typed error, not NotImplementedError.
    with pytest.raises(UnsupportedInputError):
        merge_pdfs(note, base, output)
    assert not isinstance(UnsupportedInputError(), NotImplementedError)

    # CLI layer: a typed contract error on stderr, never a traceback.
    from inkbridge.cli import main
    res = CliRunner().invoke(
        main, ["merge", str(note), str(base), "-o", str(output), "--json"])
    if res.exit_code == 0:
        # The implemented branch: a real combined PDF is acceptable too.
        assert PdfReader(output).pages
    else:
        assert res.exit_code == 1
        assert res.stdout == ""
        assert "NotImplementedError" not in (res.stderr + str(res.exception or ""))
        assert json.loads(res.stderr)["error"]["code"] == "unsupported_input"
