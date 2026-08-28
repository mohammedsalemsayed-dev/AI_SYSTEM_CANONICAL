"""Godot adapter (MILESTONE_N_PLAN.md §2)."""

from __future__ import annotations

import re
from pathlib import Path

from app.services.engines.base import EngineInfo, ExpertProfile

_FEATURES = re.compile(r'config/features\s*=\s*PackedStringArray\(([^)]*)\)')


class GodotAdapter:
    name = "godot"

    def detect(self, root: str) -> float:
        r = Path(root)
        if not (r / "project.godot").is_file():
            return 0.0
        conf = 0.7
        if any(r.rglob("*.gd")):
            conf += 0.15
        if any(r.rglob("*.tscn")):
            conf += 0.15
        return min(conf, 1.0)

    def info(self, root: str) -> EngineInfo:
        r = Path(root)
        version = ""
        try:
            txt = (r / "project.godot").read_text(encoding="utf-8", errors="replace")
            m = _FEATURES.search(txt)
            if m:
                nums = re.findall(r'"(\d\.\d?)"', m.group(1))
                version = nums[0] if nums else ""
            elif "config_version=5" in txt:
                version = "4.x"
            elif "config_version=4" in txt:
                version = "3.x"
        except OSError:
            pass
        return EngineInfo(
            engine="godot", version_hint=version,
            source_globs=["*.gd", "*.cs"],
            asset_globs=["*.tscn", "*.tres", "*.res", "*.import"],
            build_cmd="godot --headless --export-release",
            test_cmd="godot --headless --run-tests",   # GUT / GdUnit
            entrypoints=["project.godot"],
            conventions={
                "files": "snake_case; one script per node",
                "signals": "prefer signals over polling in _process",
                "nodes": "get_node()/@onready, not deep absolute paths",
            },
            confidence=self.detect(root),
        )

    def expert_profile(self) -> ExpertProfile:
        return ExpertProfile(
            name="godot",
            prompt="Godot project. Scenes are .tscn trees of nodes; scripts (.gd/.cs) attach to nodes.",
            do=[
                "attach behaviour to the node it belongs to; use @onready for node refs",
                "prefer signals and await over per-frame polling",
                "keep scene structure in .tscn; put logic in the script",
                "use snake_case for files and functions, PascalCase for classes/nodes",
            ],
            dont=[
                "hardcode deep absolute node paths",
                "do heavy work in _process/_physics_process every frame",
                "edit .tscn/.tres binary/text internals by hand unless trivial",
            ],
        )
