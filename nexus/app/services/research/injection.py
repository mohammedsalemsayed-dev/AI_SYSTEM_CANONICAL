"""Instruction-like-content scan for retrieved sources (MILESTONE_K_PLAN.md §2, §12).

A pattern-based *signal*, not a gate: a flagged source still contributes claims,
but the flag rides on the answer's `uncertainty`. The real protection is the
trust boundary — source text never reaches a decision prompt, and every research
output is `retrieved_web` trust.
"""

from __future__ import annotations

import re

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("override-instruction", re.compile(
        r"\b(ignore|disregard|forget)\b.{0,30}\b(previous|prior|above|earlier|all)\b.{0,20}"
        r"\b(instruction|prompt|rule|context|message)s?\b", re.I)),
    ("role-injection", re.compile(
        r"\b(you are now|from now on,? you|act as|pretend to be|new persona|new role)\b", re.I)),
    ("system-marker", re.compile(
        r"(^|\n)\s*(system\s*:|<\s*/?\s*system\s*>|\[/?INST\]|<\|im_start\|>|### instruction)", re.I)),
    ("tool-directive", re.compile(
        r"\b(run|execute|call|invoke)\b.{0,20}\b(the following|this)\b.{0,20}"
        r"\b(command|code|script|tool|function)\b", re.I)),
    ("exfiltration", re.compile(
        r"\b(send|post|upload|email|exfiltrate|leak)\b.{0,40}\b(to|at)\b.{0,40}"
        r"(https?://|@|\bkey\b|\btoken\b|\bsecret\b|\bcredential)", re.I)),
    ("prompt-echo-request", re.compile(
        r"\b(repeat|print|reveal|output|show)\b.{0,20}\b(your|the)\b.{0,20}"
        r"\b(system\s*prompt|instructions|rules|configuration)\b", re.I)),
]


def scan(text: str) -> list[str]:
    if not text:
        return []
    hits = sorted({name for name, pat in _PATTERNS if pat.search(text)})
    return hits


def is_suspicious(text: str) -> bool:
    return bool(scan(text))
