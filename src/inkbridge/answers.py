"""Semantic, question-level results (Analysis 0017 finding 1).

``collect``/``readback`` hand back raw cells; the agent's real question is
never "what is the ink coverage of ``choice.next-store-run.heb``" but "what
did the human answer." This module groups the cell-level readings that
:func:`inkbridge.readback.read_mark` already produces back into the *question*
each cell belongs to, and applies per-type resolution once, in one place,
instead of every agent re-deriving it from raw cells.

It sits strictly ON TOP of the readback cell decoder: the input is the
``list[PageReading]`` ``read_mark`` returns — there is no second decoder here.

Per-type resolution (finding 1):

- **choice** — the form vocabulary's option boxes are single-select (a
  multi-select is authored as separate ``- [ ]`` checkboxes, each its own
  boolean cell), so a choice group resolves to the one ANSWERED option, or
  ``conflict`` when two read ANSWERED. See the "multi-choice" note below.
- **checkbox / ack** — boolean: ANSWERED → given (``true``), BLANK →
  not-given (``false``).
- **comb / capture** — presence at cell granularity: ANSWERED means there is
  ink to read. The precise comb per-box fill (finding 1) is NOT extracted here
  — it needs a decoder refinement beyond what ``read_mark`` returns per cell
  (a per-``boxes_norm`` coverage pass), deliberately deferred so ``answers``
  stays a pure consumer of the existing decoder. ``value`` is ``null`` and the
  cell id is carried so the agent can ``composite`` it.
- **any lone AMBIGUOUS** → ``needs_review``, carrying the cell id so the agent
  can ``composite`` that cell and look.
- **capture_trigger** cells are excluded — the page AI-parse trigger belongs
  to the (future) ``triggers`` command, not to question resolution.

Learned scope for later commands:

- The manifest carries no explicit question-group id, so choice options are
  grouped by ``(page, question-label)`` recovered from the cell label
  (``"<question>: <option>"``). Two genuinely distinct choice questions with
  the *same* label on the *same* page would merge. Giving compose an explicit
  per-question ``group`` id would fix this cleanly and is exactly the
  de-collision key manifest-aware ``merge`` (finding 4) will also want.
- There is no multi-select directive today, so "multi-choice → set"
  (finding 1) has nothing to resolve yet; a multi-select choice would surface
  here as ``conflict``. Revisit if/when a multi-select directive lands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from inkbridge.readback import CellReading, Decision, PageReading

ANSWERS_SCHEMA = "answers.v1"

# Cell types handled as a single-cell answer (vs. the multi-cell choice group).
# capture_trigger is intentionally absent — it is not a question. Booleans
# resolve to true/false; every other single-cell type (comb, capture, and any
# unknown) reports presence only.
_BOOLEAN_TYPES = {"checkbox", "ack"}


class Status(str, Enum):
    ANSWERED = "answered"          # resolved to a value (incl. boolean false)
    UNANSWERED = "unanswered"      # nothing marked
    CONFLICT = "conflict"          # >1 option in a single-select choice
    NEEDS_REVIEW = "needs_review"  # AMBIGUOUS ink — composite the carried cell


def _slug(s: str) -> str:
    """Mirror of ``compose.render._slug`` (kept local to keep this read path
    free of the reportlab-heavy render import). Used only to reconstruct a
    choice group's id as ``choice.<question-slug>`` — the same prefix compose
    stamped onto each option cell — so an agent can map answer → cells."""
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return (s or "x")[:24]


@dataclass
class Answer:
    """One resolved question. ``value`` is type-specific: the option string
    (choice), a bool (checkbox/ack), a list of options (choice conflict), or
    ``None`` (unanswered / needs_review / presence-only comb·capture).
    ``cells`` carries the cell ids to escalate to (composite), when any."""

    id: str
    type: str
    label: str | None
    page: int
    status: Status
    value: object = None
    cells: list[str] | None = None

    def as_dict(self) -> dict:
        d: dict = {
            "id": self.id,
            "type": self.type,
            "label": self.label,
            "page": self.page,
            "status": self.status.value,
            "value": self.value,
        }
        if self.cells:
            d["cells"] = self.cells
        return d


def _resolve_choice(label: str, page: int, options: list[tuple[str, CellReading]]) -> Answer:
    """Single-select resolution over a question's option cells."""
    group_id = f"choice.{_slug(label)}"
    answered = [(opt, c) for opt, c in options if c.decision is Decision.ANSWERED]
    ambiguous = [(opt, c) for opt, c in options if c.decision is Decision.AMBIGUOUS]

    if len(answered) == 1:
        opt, cell = answered[0]
        return Answer(group_id, "choice", label, page, Status.ANSWERED, value=opt,
                      cells=[cell.id])
    if len(answered) >= 2:
        return Answer(group_id, "choice", label, page, Status.CONFLICT,
                      value=[opt for opt, _ in answered],
                      cells=[c.id for _, c in answered])
    if ambiguous:
        return Answer(group_id, "choice", label, page, Status.NEEDS_REVIEW,
                      cells=[c.id for _, c in ambiguous])
    return Answer(group_id, "choice", label, page, Status.UNANSWERED)


def _resolve_single(cell: CellReading) -> Answer:
    """Boolean (checkbox/ack) or presence (comb/capture, and any unknown type)
    resolution for a one-cell question."""
    if cell.decision is Decision.AMBIGUOUS:
        return Answer(cell.id, cell.type, cell.label, cell.page,
                      Status.NEEDS_REVIEW, cells=[cell.id])
    if cell.type in _BOOLEAN_TYPES:
        given = cell.decision is Decision.ANSWERED
        return Answer(cell.id, cell.type, cell.label, cell.page,
                      Status.ANSWERED, value=given)
    # presence types (and any unknown type): report that ink is/ isn't there;
    # the precise value needs a decoder refinement (see module docstring).
    if cell.decision is Decision.ANSWERED:
        return Answer(cell.id, cell.type, cell.label, cell.page,
                      Status.ANSWERED, cells=[cell.id])
    return Answer(cell.id, cell.type, cell.label, cell.page, Status.UNANSWERED)


def resolve_answers(pages: list[PageReading]) -> list[Answer]:
    """Group :class:`PageReading` cells into questions and resolve each,
    preserving document order (page, then cell order within the page).

    Pure of I/O — the caller decodes with ``read_mark`` and hands the readings
    here, exactly as ``read_pages`` is the pure core under ``read_mark``.
    """
    answers: list[Answer] = []
    # Order-preserving registry of choice groups: key -> resolved slot index.
    choice_groups: dict[tuple[int, str], list[tuple[str, CellReading]]] = {}
    plan: list[tuple[str, object]] = []  # ("choice", key) | ("single", cell)

    for page in pages:
        for cell in page.cells:
            if cell.type == "capture_trigger":
                continue
            if cell.type == "choice":
                # Cell label is "<question>: <option>"; all options of one
                # question share the "<question>: " prefix (partition on the
                # first ": "). Group by (page, question) — see module docstring
                # on the same-label collision limit.
                question, _, option = (cell.label or "").partition(": ")
                key = (page.page, question)
                if key not in choice_groups:
                    choice_groups[key] = []
                    plan.append(("choice", key))
                choice_groups[key].append((option, cell))
            else:
                plan.append(("single", cell))

    for kind, ref in plan:
        if kind == "choice":
            page_no, question = ref  # type: ignore[misc]
            answers.append(_resolve_choice(question, page_no, choice_groups[ref]))
        else:
            answers.append(_resolve_single(ref))  # type: ignore[arg-type]
    return answers


def answers_payload(
    doc_id: str | None,
    mark_file,
    resolved: list[Answer],
    *,
    mark_md5: str | None = None,
) -> dict:
    """The ``answers.v1`` payload body (the object under the ``schema_version``
    envelope key). Shared by the ``answers`` command's ``--json`` output and
    the ``<doc>.answers.json`` sidecar that ``collect`` materializes
    (ADR-0003), so the live and persisted shapes cannot drift. ``mark_md5`` —
    the provenance of the ink these answers reflect — is included only when
    known (``collect`` has it from the pull; the ad-hoc command does not)."""
    payload: dict = {"doc_id": doc_id, "mark_file": str(mark_file)}
    if mark_md5 is not None:
        payload["mark_md5"] = mark_md5
    payload["answers"] = [a.as_dict() for a in resolved]
    return payload
