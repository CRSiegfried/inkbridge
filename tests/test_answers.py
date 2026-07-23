"""`answers` resolver + CLI-contract tests.

The resolver is pure over the PageReading list read_mark returns, so — as in
test_readback — we build CellReading/PageReading objects directly instead of
decoding a real .mark. The CLI tests monkeypatch read_mark to feed those same
synthetic readings through the command, exercising the ADR-0002 contract
(exit codes, JSON on stderr, reads never mutate) without supernotelib.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from inkbridge.answers import Status, resolve_answers
from inkbridge.readback import CellReading, Decision, PageReading


def cell(id_, type_, decision, label=None, page=1, coverage=0.0):
    return CellReading(id=id_, type=type_, label=label, page=page,
                       coverage=coverage, decision=decision)


def page(cells, page_no=1, ink_hash="h"):
    return PageReading(page=page_no, ink_hash=ink_hash, cells=cells)


A = Decision.ANSWERED
B = Decision.BLANK
X = Decision.AMBIGUOUS


# -- choice grouping / single-select resolution ----------------------------

def _choice_cells(decisions: dict[str, Decision]):
    return [cell(f"choice.meal.{k}", "choice", d, label=f"meal: {k}")
            for k, d in decisions.items()]


def test_choice_single_winner():
    (a,) = resolve_answers([page(_choice_cells({"eggs": A, "oats": B, "fruit": B}))])
    assert a.type == "choice" and a.id == "choice.meal"
    assert a.label == "meal" and a.status is Status.ANSWERED
    assert a.value == "eggs"
    assert a.cells == ["choice.meal.eggs"]


def test_choice_two_answered_is_conflict():
    (a,) = resolve_answers([page(_choice_cells({"eggs": A, "oats": A, "fruit": B}))])
    assert a.status is Status.CONFLICT
    assert a.value == ["eggs", "oats"]
    assert a.cells == ["choice.meal.eggs", "choice.meal.oats"]


def test_choice_lone_ambiguous_needs_review_with_cell():
    (a,) = resolve_answers([page(_choice_cells({"eggs": X, "oats": B}))])
    assert a.status is Status.NEEDS_REVIEW
    assert a.value is None
    assert a.cells == ["choice.meal.eggs"]  # the id to composite (finding 1)


def test_choice_nothing_marked_is_unanswered():
    (a,) = resolve_answers([page(_choice_cells({"eggs": B, "oats": B}))])
    assert a.status is Status.UNANSWERED
    assert a.value is None and not a.cells


def test_answered_beats_ambiguous_no_review():
    # a clean winner alongside a stray ambiguous mark still resolves cleanly
    (a,) = resolve_answers([page(_choice_cells({"eggs": A, "oats": X}))])
    assert a.status is Status.ANSWERED and a.value == "eggs"


# -- boolean checkbox / ack ------------------------------------------------

def test_checkbox_true_false():
    checked, unchecked = resolve_answers([page([
        cell("checkbox.milk", "checkbox", A, label="milk"),
        cell("checkbox.eggs", "checkbox", B, label="eggs"),
    ])])
    assert checked.status is Status.ANSWERED and checked.value is True
    assert unchecked.status is Status.ANSWERED and unchecked.value is False


def test_ack_ambiguous_needs_review():
    (a,) = resolve_answers([page([cell("ack.terms", "ack", X, label="terms")])])
    assert a.status is Status.NEEDS_REVIEW and a.cells == ["ack.terms"]


# -- presence types (comb / capture) ---------------------------------------

@pytest.mark.parametrize("ctype", ["comb", "capture"])
def test_presence_answered_carries_cell_no_value(ctype):
    (a,) = resolve_answers([page([cell(f"{ctype}.x", ctype, A, label="x")])])
    assert a.status is Status.ANSWERED
    assert a.value is None            # precise position/fill deferred
    assert a.cells == [f"{ctype}.x"]  # composite target


@pytest.mark.parametrize("ctype", ["comb", "capture"])
def test_presence_blank_is_unanswered(ctype):
    (a,) = resolve_answers([page([cell(f"{ctype}.x", ctype, B, label="x")])])
    assert a.status is Status.UNANSWERED and not a.cells


# -- structural: triggers excluded, order + pages preserved ----------------

def test_capture_trigger_excluded():
    resolved = resolve_answers([page([
        cell("cmd.capture.p1", "capture_trigger", A, label="capture page 1"),
        cell("checkbox.milk", "checkbox", A, label="milk"),
    ])])
    assert [a.id for a in resolved] == ["checkbox.milk"]


def test_order_and_multipage_grouping_preserved():
    resolved = resolve_answers([
        page([cell("checkbox.a", "checkbox", A, label="a"),
              *_choice_cells({"eggs": A, "oats": B})], page_no=1),
        page([cell("ack.z", "ack", B, label="z", page=2)], page_no=2),
    ])
    assert [(a.id, a.page) for a in resolved] == [
        ("checkbox.a", 1), ("choice.meal", 1), ("ack.z", 2)]


def test_same_label_different_page_are_distinct_groups():
    # grouping is (page, question): the same question label on two pages must
    # not collapse into one answer.
    resolved = resolve_answers([
        page(_choice_cells({"eggs": A, "oats": B}), page_no=1),
        page([cell("choice.meal.eggs", "choice", B, label="meal: eggs", page=2),
              cell("choice.meal.oats", "choice", A, label="meal: oats", page=2)],
             page_no=2),
    ])
    assert [(a.page, a.value) for a in resolved] == [(1, "eggs"), (2, "oats")]


# -- CLI contract (ADR-0002) ----------------------------------------------

@pytest.fixture()
def form(tmp_path):
    """A manifest file + a placeholder mark file on disk; read_mark is patched
    so the mark bytes are never actually decoded."""
    manifest = tmp_path / "form.manifest.json"
    manifest.write_text(json.dumps({"doc_id": "form-abc12345", "cells": []}))
    mark = tmp_path / "form.pdf.mark"
    mark.write_bytes(b"not-a-real-mark")
    return manifest, mark


@pytest.fixture()
def patched_read_mark(monkeypatch):
    """Feed synthetic readings through the command in place of a real decode."""
    def _install(pages):
        monkeypatch.setattr("inkbridge.readback.read_mark",
                            lambda manifest, mark_path, **kw: pages)
    return _install


def test_cli_json_payload_and_exit_ok(form, patched_read_mark):
    manifest, mark = form
    patched_read_mark([page([
        cell("choice.meal.eggs", "choice", A, label="meal: eggs"),
        cell("choice.meal.oats", "choice", B, label="meal: oats"),
        cell("ack.terms", "ack", X, label="terms"),
    ])])
    from inkbridge.cli import main

    res = CliRunner().invoke(main, ["answers", str(manifest), str(mark), "--json"])
    assert res.exit_code == 0
    doc = json.loads(res.stdout)
    assert doc["schema_version"] == "answers.v1"
    assert doc["doc_id"] == "form-abc12345"
    by_id = {a["id"]: a for a in doc["answers"]}
    assert by_id["choice.meal"]["status"] == "answered"
    assert by_id["choice.meal"]["value"] == "eggs"
    assert by_id["ack.terms"]["status"] == "needs_review"
    assert by_id["ack.terms"]["cells"] == ["ack.terms"]


def test_cli_missing_manifest_is_json_error_on_stderr_exit_4(tmp_path, patched_read_mark):
    from inkbridge.cli import main

    res = CliRunner().invoke(
        main, ["answers", str(tmp_path / "nope.json"), str(tmp_path / "x.mark"), "--json"])
    assert res.exit_code == 4          # NOT_FOUND, not Click's usage exit 2
    assert res.stdout == ""            # nothing on stdout on failure
    err = json.loads(res.stderr)
    assert err["schema_version"] == "error.v1"
    assert err["error"]["code"] == "not_found"


def test_cli_malformed_manifest_is_contract_error_not_traceback(tmp_path):
    # ADR-0002 §4: a failure is a JSON envelope on stderr, never a traceback.
    bad = tmp_path / "bad.manifest.json"
    bad.write_text("this is not json {")
    mark = tmp_path / "m.pdf.mark"
    mark.write_bytes(b"x")
    from inkbridge.cli import main

    res = CliRunner().invoke(main, ["answers", str(bad), str(mark), "--json"])
    assert res.exit_code == 1
    assert res.stdout == "" and "Traceback" not in res.stderr
    err = json.loads(res.stderr)
    assert err["error"]["code"] == "invalid_manifest"


def test_cli_sparse_mark_is_precondition_not_traceback(form, monkeypatch):
    # ADR-0004: a sparse mark (a manifest page absent from the .mark) is a
    # typed PRECONDITION(6) contract error, never an uncaught traceback.
    manifest, mark = form
    from inkbridge.readback import SparseMarkError

    def _raise(manifest, mark_path, **kw):
        raise SparseMarkError("manifest references page 3 but it is absent")

    monkeypatch.setattr("inkbridge.readback.read_mark", _raise)
    from inkbridge.cli import main

    res = CliRunner().invoke(main, ["answers", str(manifest), str(mark), "--json"])
    assert res.exit_code == 6
    assert res.stdout == "" and "Traceback" not in res.stderr
    err = json.loads(res.stderr)
    assert err["error"]["code"] == "sparse_mark"


def test_cli_missing_mark_human_error_on_stderr(form):
    manifest, _ = form
    from inkbridge.cli import main

    res = CliRunner().invoke(main, ["answers", str(manifest), "/no/such.mark"])
    assert res.exit_code == 4
    assert res.stdout == ""
    assert res.stderr.startswith("error: mark file not found")


def test_cli_read_never_mutates(form, patched_read_mark):
    # ADR-0002 §5: a report leaves every input byte-identical.
    manifest, mark = form
    patched_read_mark([page([cell("checkbox.milk", "checkbox", A, label="milk")])])
    before = (manifest.read_bytes(), mark.read_bytes())
    from inkbridge.cli import main

    CliRunner().invoke(main, ["answers", str(manifest), str(mark), "--json"])
    assert (manifest.read_bytes(), mark.read_bytes()) == before


def test_cli_human_output_no_json_noise(form, patched_read_mark):
    manifest, mark = form
    patched_read_mark([page([cell("checkbox.milk", "checkbox", A, label="milk")])])
    from inkbridge.cli import main

    res = CliRunner().invoke(main, ["answers", str(manifest), str(mark)])
    assert res.exit_code == 0
    assert "form-abc12345" in res.stdout
    assert "checkbox.milk" in res.stdout
    assert not res.stdout.lstrip().startswith("{")  # human path, not JSON
