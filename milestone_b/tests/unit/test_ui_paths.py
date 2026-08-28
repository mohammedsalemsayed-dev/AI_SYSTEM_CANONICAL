"""Acceptance (Unit): frozen-aware path resolution + the Tauri project config
are well-formed (MILESTONE_H_TAURI_PLAN.md §6)."""

from __future__ import annotations

import json
from pathlib import Path

from app.ui import paths

_DESKTOP = Path(__file__).resolve().parents[2] / "desktop"


def test_web_dir_from_source_has_the_frontend() -> None:
    w = paths.web_dir()
    assert w.is_dir()
    for f in ("index.html", "app.js", "style.css"):
        assert (w / f).is_file()


def test_default_db_path_is_under_a_creatable_user_dir() -> None:
    p = paths.default_db_path()
    assert p.name == "events.db"
    assert p.parent == paths.user_data_dir()
    assert "nexus" in str(p).lower()
    assert not paths.is_frozen()  # running from source


def test_tauri_conf_parses_and_carries_the_keys_main_rs_reads() -> None:
    conf = json.loads((_DESKTOP / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))
    assert conf["identifier"] == "com.nexus.controlplane"
    assert conf["build"]["frontendDist"] == "../dist"
    win = conf["app"]["windows"][0]
    assert win["label"] == "main" and win["url"] == "splash.html"
    assert conf["bundle"]["externalBin"] == ["binaries/nexus-server"]
    assert "nsis" in conf["bundle"]["targets"] and "dmg" in conf["bundle"]["targets"]


def test_capabilities_scope_only_the_sidecar() -> None:
    cap = json.loads(
        (_DESKTOP / "src-tauri" / "capabilities" / "default.json").read_text(encoding="utf-8")
    )
    assert cap["windows"] == ["main"]
    execs = [
        p for p in cap["permissions"]
        if isinstance(p, dict) and p.get("identifier") == "shell:allow-execute"
    ]
    assert len(execs) == 1
    allowed = execs[0]["allow"]
    assert [a["name"] for a in allowed] == ["binaries/nexus-server"]
    assert all(a.get("sidecar") for a in allowed)


def test_splash_and_icons_present() -> None:
    assert (_DESKTOP / "dist" / "splash.html").is_file()
    icons = _DESKTOP / "src-tauri" / "icons"
    for f in ("32x32.png", "128x128.png", "128x128@2x.png", "icon.ico"):
        assert (icons / f).is_file()
