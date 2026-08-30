"""Structural loop detection (design-notes 14.4, MILESTONE_D_PLAN.md 2).

No model call. Three structural flags over the recent step history:
  - repeated_action  — the same normalized action hash >= R of the last W steps
  - repeated_error   — the same normalized error signature >= E times running
  - diff_thrash      — successive diffs near-identical >= T times running

A step that made hard progress clears the history: a repeat that is making
progress is not a loop (the false-positive guard from MILESTONE_D_PLAN §8).
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

# tunables — recalibrate from data (MILESTONE_D_PLAN §7)
REPEAT_WINDOW = 5
REPEAT_THRESHOLD = 3
ERROR_THRESHOLD = 3
THRASH_THRESHOLD = 3
THRASH_SIMILARITY = 0.9

_NUM = re.compile(r"\b0x[0-9a-fA-F]+\b|\b\d+\b")
_PATH = re.compile(r"[A-Za-z]:[\\/][^\s'\"]+|/[^\s'\"]+")
_ADDR = re.compile(r"at 0x[0-9a-fA-F]+")


def normalize_args(args: dict[str, Any]) -> str:
    def norm(v: Any) -> Any:
        if isinstance(v, str):
            return _NUM.sub("N", _PATH.sub("PATH", v))
        if isinstance(v, dict):
            return {k: norm(x) for k, x in sorted(v.items())}
        if isinstance(v, (list, tuple)):
            return [norm(x) for x in v]
        return v

    return json.dumps(norm(args), sort_keys=True, default=str)


def action_hash(operation: str, target: str, args: dict[str, Any]) -> str:
    norm_target = _NUM.sub("N", (target or "").replace("\\", "/"))
    payload = f"{operation}|{norm_target}|{normalize_args(args or {})}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def normalize_error(text: str | None) -> str | None:
    if not text:
        return None
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    exc_line = None
    for ln in reversed(lines):
        s = ln.lstrip("E ").strip()
        if re.match(r"^[A-Za-z_][\w.]*(Error|Exception|Warning)\b", s) or ": " in s and s.split(":", 1)[0].endswith(("Error", "Exception")):
            exc_line = s
            break
    frame = None
    for ln in reversed(lines):
        mobj = re.search(r'File "[^"]+", line \d+, in (\S+)', ln)
        if mobj:
            frame = mobj.group(1)
            break
    basis = exc_line or lines[-1]
    basis = _ADDR.sub("at ADDR", _PATH.sub("PATH", _NUM.sub("N", basis)))
    sig = basis if frame is None else f"{frame}: {basis}"
    return hashlib.sha1(sig.encode("utf-8")).hexdigest()[:16]


def diff_similarity(a: str, b: str) -> float:
    if not a.strip() and not b.strip():
        return 1.0
    return difflib.SequenceMatcher(
        None, a.splitlines(), b.splitlines()
    ).ratio()


@dataclass
class LoopReport:
    loop_risk: bool
    flags: list[str] = field(default_factory=list)


class LoopDetector:
    def __init__(
        self,
        repeat_window: int = REPEAT_WINDOW,
        repeat_threshold: int = REPEAT_THRESHOLD,
        error_threshold: int = ERROR_THRESHOLD,
        thrash_threshold: int = THRASH_THRESHOLD,
        thrash_similarity: float = THRASH_SIMILARITY,
    ) -> None:
        self.repeat_window = repeat_window
        self.repeat_threshold = repeat_threshold
        self.error_threshold = error_threshold
        self.thrash_threshold = thrash_threshold
        self.thrash_similarity = thrash_similarity
        self._hashes: list[str] = []
        self._errors: list[str] = []
        self._last_diff: str | None = None
        self._thrash_run = 0

    def record(
        self,
        *,
        act_hash: str,
        error_signature: str | None,
        diff_text: str,
        made_progress: bool = False,
    ) -> LoopReport:
        if made_progress:
            # a step that worked is not part of any loop — forget the history
            self._hashes.clear()
            self._errors.clear()
            self._thrash_run = 0
            self._last_diff = diff_text
            return LoopReport(loop_risk=False)

        self._hashes.append(act_hash)
        if error_signature:
            self._errors.append(error_signature)
        else:
            self._errors.clear()

        if self._last_diff is not None and diff_text.strip():
            if diff_similarity(self._last_diff, diff_text) >= self.thrash_similarity:
                self._thrash_run += 1
            else:
                self._thrash_run = 0
        self._last_diff = diff_text

        return self.report()

    def report(self) -> LoopReport:
        flags: list[str] = []
        recent = self._hashes[-self.repeat_window :]
        if recent and recent.count(recent[-1]) >= self.repeat_threshold:
            flags.append("repeated_action")
        if len(self._errors) >= self.error_threshold and (
            len(set(self._errors[-self.error_threshold :])) == 1
        ):
            flags.append("repeated_error")
        # _thrash_run counts consecutive near-identical *successive* diffs;
        # threshold T means T diffs in a row alike -> _thrash_run >= T - 1
        if self._thrash_run >= max(1, self.thrash_threshold - 1):
            flags.append("diff_thrash")
        return LoopReport(loop_risk=bool(flags), flags=flags)
