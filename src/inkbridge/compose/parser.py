"""Markdown → block IR for the compose renderer.

Parsing is off-the-shelf (markdown-it-py); this module only walks the token
stream into a flat list of blocks the row-grid renderer can deal onto rows.

Inline styling survives as (text, style) segments on paragraph-like blocks
(0012 finding 9.1): styles are "body" / "bold" / "italic" / "bolditalic" /
"code", and the renderer maps them onto the pinned Vera variants. ``text``
on those blocks stays the flattened concatenation, which is what directive
detection and cell labels use.

v1 degradation rules (0012 finding 8, "any markdown renders, nothing
crashes"):
- tables render as monospace column-padded text rows (no input cells);
- raw HTML becomes a labeled placeholder block;
- images flatten to "[image: alt]" text;
- list nesting flattens past depth 2 (renderer clamps the indent).

Extended directives are plain paragraphs, so any markdown editor accepts
them:  {capture: label rows=6}   {choice: label | a | b | c}   {ack: label}
{comb: label n=8}
A malformed directive stays a visible Paragraph rather than erroring.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from markdown_it import MarkdownIt

# (text, style) segment; style is one of body/bold/italic/bolditalic/code.
Segment = tuple[str, str]


def _plain(text: str) -> list[Segment]:
    return [(text, "body")] if text else []


@dataclass
class Heading:
    level: int
    text: str


@dataclass
class Paragraph:
    text: str
    segments: list[Segment] = field(default_factory=list)

    def __post_init__(self):
        if not self.segments:
            self.segments = _plain(self.text)


@dataclass
class ListItem:
    text: str
    depth: int = 0
    marker: str = "•"  # empty marker = continuation line of an item
    segments: list[Segment] = field(default_factory=list)

    def __post_init__(self):
        if not self.segments:
            self.segments = _plain(self.text)


@dataclass
class Checkbox:
    label: str
    depth: int = 0


@dataclass
class Quote:
    text: str
    segments: list[Segment] = field(default_factory=list)

    def __post_init__(self):
        if not self.segments:
            self.segments = _plain(self.text)


@dataclass
class CodeBlock:
    lines: list[str] = field(default_factory=list)


@dataclass
class Rule:
    pass


@dataclass
class Placeholder:
    detail: str


@dataclass
class Table:
    rows: list[list[str]] = field(default_factory=list)  # rows[0] is the header


@dataclass
class Capture:
    label: str
    rows: int = 7


@dataclass
class Choice:
    label: str
    options: list[str] = field(default_factory=list)


@dataclass
class Ack:
    label: str


@dataclass
class Comb:
    label: str
    n: int = 8


_DIRECTIVE_RE = re.compile(r"^\{\s*(capture|choice|ack|comb)\s*:\s*(.+?)\s*\}$", re.DOTALL)
_ROWS_RE = re.compile(r"\s+rows\s*=\s*(\d+)\s*$")
_N_RE = re.compile(r"\s+n\s*=\s*(\d+)\s*$")
_TASK_RE = re.compile(r"^\[( |x|X)\]\s+(.*)$", re.DOTALL)


def _directive(text: str):
    m = _DIRECTIVE_RE.match(text.strip())
    if not m:
        return None
    kind, body = m.group(1), m.group(2)
    if kind == "capture":
        rows = 7
        rm = _ROWS_RE.search(body)
        if rm:
            rows = int(rm.group(1))
            body = body[: rm.start()]
        return Capture(body.strip() or "capture", rows)
    if kind == "ack":
        return Ack(body.strip() or "acknowledged")
    if kind == "comb":
        n = 8
        nm = _N_RE.search(body)
        if nm:
            n = max(1, int(nm.group(1)))
            body = body[: nm.start()]
        label = body.strip()
        return Comb(label, n) if label else None
    parts = [p.strip() for p in body.split("|")]
    options = [p for p in parts[1:] if p]
    if parts[0] and options:
        return Choice(parts[0], options)
    return None


def _segments(tok) -> list[Segment]:
    """Walk an inline token's children into merged (text, style) segments."""
    segs: list[Segment] = []
    bold = 0
    italic = 0

    def style() -> str:
        if bold and italic:
            return "bolditalic"
        if bold:
            return "bold"
        if italic:
            return "italic"
        return "body"

    def emit(text: str, sty: str | None = None) -> None:
        if not text:
            return
        sty = sty or style()
        if segs and segs[-1][1] == sty:
            segs[-1] = (segs[-1][0] + text, sty)
        else:
            segs.append((text, sty))

    for ch in tok.children or []:
        ty = ch.type
        if ty == "text":
            emit(ch.content)
        elif ty == "code_inline":
            emit(ch.content, "code")
        elif ty == "strong_open":
            bold += 1
        elif ty == "strong_close":
            bold -= 1
        elif ty == "em_open":
            italic += 1
        elif ty == "em_close":
            italic -= 1
        elif ty in ("softbreak", "hardbreak"):
            emit(" ")
        elif ty == "image":
            emit(f"[image: {ch.content or 'image'}]")
    # strip outer whitespace without losing interior styling
    if segs:
        first_text = segs[0][0].lstrip()
        segs[0] = (first_text, segs[0][1])
        last_text = segs[-1][0].rstrip()
        segs[-1] = (last_text, segs[-1][1])
        segs = [s for s in segs if s[0]]
    return segs


def _flatten(tok) -> str:
    return "".join(text for text, _ in _segments(tok))


def parse(text: str) -> list:
    md = MarkdownIt("commonmark")
    try:
        md.enable("table")
    except ValueError:
        pass  # tables then parse as paragraphs; still renders
    toks = md.parse(text)

    blocks: list = []
    lists: list[dict] = []  # stack: {"ordered": bool, "index": int}
    quote_depth = 0
    item_first = False
    cur_marker = ""
    i = 0
    while i < len(toks):
        t = toks[i]
        ty = t.type
        if ty == "heading_open":
            blocks.append(Heading(int(t.tag[1:]), _flatten(toks[i + 1])))
            i += 3
        elif ty in ("fence", "code_block"):
            blocks.append(CodeBlock(t.content.rstrip("\n").splitlines() or [""]))
            i += 1
        elif ty == "hr":
            blocks.append(Rule())
            i += 1
        elif ty == "blockquote_open":
            quote_depth += 1
            i += 1
        elif ty == "blockquote_close":
            quote_depth -= 1
            i += 1
        elif ty in ("bullet_list_open", "ordered_list_open"):
            start = t.attrGet("start") if ty == "ordered_list_open" else None
            lists.append({"ordered": ty == "ordered_list_open", "index": int(start or 1)})
            i += 1
        elif ty in ("bullet_list_close", "ordered_list_close"):
            lists.pop()
            i += 1
        elif ty == "list_item_open":
            top = lists[-1]
            cur_marker = f"{top['index']}." if top["ordered"] else "•"
            if top["ordered"]:
                top["index"] += 1
            item_first = True
            i += 1
        elif ty == "table_open":
            rows: list[list[str]] = []
            cur_row: list[str] = []
            j = i + 1
            while j < len(toks) and toks[j].type != "table_close":
                tj = toks[j]
                if tj.type == "tr_open":
                    cur_row = []
                elif tj.type == "tr_close":
                    rows.append(cur_row)
                elif tj.type == "inline":
                    cur_row.append(_flatten(tj))
                j += 1
            blocks.append(Table(rows))
            i = j + 1
        elif ty == "html_block":
            blocks.append(Placeholder("embedded HTML not rendered"))
            i += 1
        elif ty == "paragraph_open":
            segs = _segments(toks[i + 1])
            txt = "".join(text for text, _ in segs)
            i += 3
            if quote_depth:
                blocks.append(Quote(txt, segments=segs))
            elif lists:
                depth = len(lists) - 1
                m = _TASK_RE.match(txt)
                if item_first and m and not lists[-1]["ordered"]:
                    blocks.append(Checkbox(m.group(2).strip(), depth))
                else:
                    blocks.append(
                        ListItem(txt, depth, cur_marker if item_first else "", segments=segs))
                item_first = False
            else:
                d = _directive(txt)
                blocks.append(d if d is not None else Paragraph(txt, segments=segs))
        else:
            i += 1
    return blocks


def block_from_ir(spec: dict):
    """Build one block object from a block-IR dict (G3) — the structured
    alternative to Markdown. Built-in kinds map to their dataclasses; a kind
    registered in the cell-type registry becomes a ``CustomBlock``; an unknown
    kind is a ``ValueError``."""
    from .celltypes import CustomBlock, is_registered

    kind = spec.get("kind")
    if kind == "heading":
        return Heading(int(spec.get("level", 1)), spec.get("text", ""))
    if kind in ("paragraph", "text"):
        return Paragraph(spec.get("text", ""))
    if kind == "listitem":
        return ListItem(spec.get("text", ""), int(spec.get("depth", 0)),
                        spec.get("marker", "•"))
    if kind == "checkbox":
        return Checkbox(spec["label"], int(spec.get("depth", 0)))
    if kind == "ack":
        return Ack(spec["label"])
    if kind == "choice":
        return Choice(spec["label"], list(spec.get("options", [])))
    if kind == "capture":
        return Capture(spec["label"], int(spec.get("rows", 7)))
    if kind == "comb":
        return Comb(spec["label"], int(spec.get("n", 8)))
    if kind == "rule":
        return Rule()
    if is_registered(kind):
        return CustomBlock(type=kind, label=spec.get("label", ""), ir=spec)
    raise ValueError(f"unknown IR block kind {kind!r}")
