"""Turn a finished answer into display blocks.

The generated answer is plain text. Its only structure is line-based: blank
lines separate paragraphs, lines starting with "- " are list items, lines
starting with "1." are steps, and lines whose cells are separated by " | "
are table rows. This module reads that structure once, server-side, so the
template can render real paragraphs, lists and tables instead of a wall of
text. The client script mirrors the same rules for streamed answers.

Nothing here interprets the text as markup. Every value the blocks carry is
rendered with autoescaping (template) or textContent (script).
"""

from __future__ import annotations

import re

STEP_LINE = re.compile(r"^\d{1,2}[.)]\s+")


def _is_table_row(line: str) -> bool:
    return " | " in line


def answer_blocks(text: str) -> list[dict[str, object]]:
    """Split an answer into paragraph, list, steps and table blocks.

    Consecutive prose lines up to a blank line form one paragraph and are
    joined with spaces. The "entries" key is deliberately not called "items"
    because Jinja resolves dict.items, the method, before the key.
    """
    blocks: list[dict[str, object]] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            blocks.append({"kind": "paragraph", "text": " ".join(paragraph)})
            paragraph.clear()

    lines = text.split("\n")
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        if _is_table_row(lines[i]):
            flush()
            rows: list[list[str]] = []
            while i < len(lines) and _is_table_row(lines[i]):
                rows.append([cell.strip() for cell in lines[i].split(" | ")])
                i += 1
            blocks.append({"kind": "table", "rows": rows})
            continue

        if stripped.startswith("- "):
            flush()
            entries: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                entries.append(lines[i].strip()[2:].strip())
                i += 1
            blocks.append({"kind": "list", "entries": entries})
            continue

        if STEP_LINE.match(stripped):
            flush()
            start = int(re.match(r"\d+", stripped).group())  # type: ignore[union-attr]
            steps: list[str] = []
            while i < len(lines) and STEP_LINE.match(lines[i].strip()):
                steps.append(STEP_LINE.sub("", lines[i].strip()))
                i += 1
            blocks.append({"kind": "steps", "entries": steps, "start": start})
            continue

        if stripped:
            paragraph.append(stripped)
        else:
            flush()
        i += 1

    flush()
    return blocks
