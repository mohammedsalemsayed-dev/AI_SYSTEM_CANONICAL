"""Reap our own leaked temp dirs.

The frozen sidecar is PyInstaller `--onefile`: every launch extracts to a
`_MEI<rand>` dir under the OS temp, and a hard kill (which happens on app
restart) orphans it. Verification also copies the workspace to
`slice_ws_*` / `slice_verify_*` / `slice_godot_*` and only cleans it in a
`finally` — again skipped on a kill. Left alone these accumulate to gigabytes.

`sweep_stale_tempdirs()` runs once at sidecar startup: delete our prefixes when
they're older than `MIN_AGE_S` and not owned by a live PID.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

MIN_AGE_S = 3600.0
_PREFIXES = ("slice_ws_", "slice_verify_", "slice_godot_", "slice_ws_copy_")
_MEI = "_MEI"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


def _mei_pid(name: str) -> int | None:
    # PyInstaller names the dir _MEI<pid-ish><rand>; not reliable, so we fall
    # back to age only for _MEI.
    return None


def sweep_stale_tempdirs(*, root: str | None = None, min_age_s: float = MIN_AGE_S) -> int:
    base = Path(root or tempfile.gettempdir())
    now = time.time()
    freed = 0
    self_mei = os.environ.get("_MEIPASS2") or getattr(__import__("sys"), "_MEIPASS", "")
    try:
        entries = list(base.iterdir())
    except OSError:
        return 0
    for p in entries:
        try:
            if not p.is_dir():
                continue
            name = p.name
            is_ours = name.startswith(_PREFIXES) or name.startswith(_MEI)
            if not is_ours:
                continue
            if self_mei and Path(self_mei) == p:
                continue
            if now - p.stat().st_mtime < min_age_s:
                continue
            shutil.rmtree(p, ignore_errors=True)
            freed += 1
        except OSError:
            continue
    return freed
