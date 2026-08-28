"""Path resolution for the shell, source-tree and PyInstaller-bundle aware
(MILESTONE_H_TAURI_PLAN.md §2).

When frozen by PyInstaller, data files live under `sys._MEIPASS`; the per-user
event-log DB lives under the OS application-data directory.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_APP_DIR_NAME = "nexus"


def is_frozen() -> bool:
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def _bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))


def web_dir() -> Path:
    """The frontend directory (`index.html`, `app.js`, `style.css`)."""
    if is_frozen():
        cand = _bundle_root() / "app" / "ui" / "web"
        if cand.is_dir():
            return cand
        return _bundle_root() / "web"  # flattened add-data layout
    return Path(__file__).resolve().parent / "web"


def user_data_dir() -> Path:
    """Per-user writable directory for the event-log DB and logs."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / _APP_DIR_NAME


def default_db_path() -> Path:
    return user_data_dir() / "events.db"
