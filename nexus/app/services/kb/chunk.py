"""Heading-aware sliding-window chunking (MILESTONE_L_PLAN.md §2).

Split on Markdown headings and blank lines, pack to ~`target_chars` with
`overlap`, and carry the nearest heading onto every chunk. Deterministic.
"""

from __future__ import annotations

import re

TARGET_CHARS = 1000
OVERLAP = 150

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def chunk(
    text: str,
    *,
    target_chars: int = TARGET_CHARS,
    overlap: int = OVERLAP,
    headings: bool = True,
) -> list[tuple[str, str]]:
    """Return [(heading, chunk_text)]. `heading` is "" when none applies."""
    if not text.strip():
        return []

    # split into (heading, block) paragraphs
    blocks: list[tuple[str, str]] = []
    cur_heading = ""
    buf: list[str] = []

    def flush() -> None:
        if buf:
            para = "\n".join(buf).strip()
            if para:
                blocks.append((cur_heading, para))
            buf.clear()

    for line in text.splitlines():
        m = _HEADING.match(line.strip()) if headings else None
        if m:
            flush()
            cur_heading = m.group(2).strip()
            continue
        if not line.strip():
            flush()
            continue
        buf.append(line)
    flush()

    if not blocks:
        blocks = [("", text.strip())]

    # pack paragraphs into ~target_chars chunks, splitting oversized paragraphs
    out: list[tuple[str, str]] = []
    cur_h = blocks[0][0]
    acc: list[str] = []
    acc_len = 0

    def emit() -> None:
        nonlocal acc, acc_len
        if acc:
            out.append((cur_h, "\n\n".join(acc).strip()))
            acc, acc_len = [], 0

    for h, para in blocks:
        for piece in _split_oversized(para, target_chars):
            if acc and (h != cur_h or acc_len + len(piece) > target_chars):
                emit()
            if not acc:
                cur_h = h
            acc.append(piece)
            acc_len += len(piece) + 2
    emit()

    if overlap > 0 and len(out) > 1:
        out = _apply_overlap(out, overlap)
    return out


def _split_oversized(para: str, target: str | int) -> list[str]:
    target = int(target)
    if len(para) <= target:
        return [para]
    pieces, i = [], 0
    while i < len(para):
        end = min(len(para), i + target)
        if end < len(para):
            sp = para.rfind(" ", i + target // 2, end)
            if sp > i:
                end = sp
        pieces.append(para[i:end].strip())
        i = end
    return [p for p in pieces if p]


def _apply_overlap(chunks: list[tuple[str, str]], overlap: int) -> list[tuple[str, str]]:
    out = [chunks[0]]
    for i in range(1, len(chunks)):
        h, body = chunks[i]
        prev = chunks[i - 1][1]
        tail = prev[-overlap:]
        sp = tail.find(" ")
        tail = tail[sp + 1:] if sp != -1 else tail
        out.append((h, (tail + "\n\n" + body).strip() if tail.strip() else body))
    return out
