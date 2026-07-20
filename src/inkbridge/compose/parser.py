"""Markdown → block IR for the compose renderer (Analysis 0012 finding 9).

Parsing is off-the-shelf (markdown-it-py); this module only walks the token
stream into a flat list of blocks the row-grid renderer can deal onto rows.

v1 degradation rules (0012 finding 8, "any markdown renders, nothing
crashes"):
- inline styling (bold/italic/links/inline code) is flattened to plain text;
- tables and raw HTML become labeled placeholder blocks;
- images flatten to "[image: alt]" text;
- list nesting flattens past depth 2 (renderer clamps the indent).

Extended directives are plain paragraphs, so any markdown editor accepts
them:  {capture: label rows=6}   {choice: label | a | b | c}   {ack: label}
A malformed directive stays a visible Paragraph rather than erroring.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from markdown_it import MarkdownIt


@dataclass
class Heading:
    level: int
    text: str


@dataclass
class Paragraph:
    text: str


@dataclass
class ListItem:
    text: str
    depth: int = 0
    marker: str = "•"  # empty marker = continuation line of an item


@dataclass
class Checkbox:
    label: str
    depth: int = 0


@dataclass
class Quote:
    text: str


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


_DIRECTIVE_RE = re.compile(r"^\{\s*(capture|choice|ack)\s*:\s*(.+?)\s*\}$", re.S)
_ROWS_RE = re.compile(r"\s+rows\s*=\s*(\d+)\s*$")
_TASK_RE = re.compile(r"^\[( |x|X)\]\s+(.*)$", re.S)


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
    parts = [p.strip() for p in body.split("|")]
    options = [p for p in parts[1:] if p]
    if parts[0] and options:
        return Choice(parts[0], options)
    return None


def _flatten(tok) -> str:
    parts: list[str] = []
    for ch in tok.children or []:
        if ch.type in ("text", "code_inline"):
            parts.append(ch.content)
        elif ch.type in ("softbreak", "hardbreak"):
            parts.append(" ")
        elif ch.type == "image":
            parts.append(f"[image: {ch.content or 'image'}]")
    return "".join(parts).strip()


def parse(text: str) -> list:
    md = MarkdownIt("commonmark")
    try:
        md.enable("table")
    except Exception:
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
            j, nrows = i, 0
            while j < len(toks) and toks[j].type != "table_close":
                if toks[j].type == "tr_open":
                    nrows += 1
                j += 1
            blocks.append(Placeholder(f"table ({nrows} rows) not rendered"))
            i = j + 1
        elif ty == "html_block":
            blocks.append(Placeholder("embedded HTML not rendered"))
            i += 1
        elif ty == "paragraph_open":
            txt = _flatten(toks[i + 1])
            i += 3
            if quote_depth:
                blocks.append(Quote(txt))
            elif lists:
                depth = len(lists) - 1
                m = _TASK_RE.match(txt)
                if item_first and m and not lists[-1]["ordered"]:
                    blocks.append(Checkbox(m.group(2).strip(), depth))
                else:
                    blocks.append(ListItem(txt, depth, cur_marker if item_first else ""))
                item_first = False
            else:
                d = _directive(txt)
                blocks.append(d if d is not None else Paragraph(txt))
        else:
            i += 1
    return blocks
