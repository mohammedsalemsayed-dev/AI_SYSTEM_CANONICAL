"""Unreal Engine adapter (MILESTONE_N_PLAN.md §2)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.services.engines.base import EngineInfo, ExpertProfile


class UnrealAdapter:
    name = "unreal"

    def _uproject(self, root: str) -> Path | None:
        return next(iter(Path(root).glob("*.uproject")), None)

    def detect(self, root: str) -> float:
        up = self._uproject(root)
        if up is None:
            return 0.0
        conf = 0.8
        if any(Path(root).rglob("*.Build.cs")):
            conf += 0.2
        return min(conf, 1.0)

    def info(self, root: str) -> EngineInfo:
        up = self._uproject(root)
        version = ""
        modules: list[str] = []
        if up is not None:
            try:
                data = json.loads(up.read_text(encoding="utf-8", errors="replace"))
                version = str(data.get("EngineAssociation", ""))
                modules = [m.get("Name", "") for m in data.get("Modules", []) if m.get("Name")]
            except (OSError, json.JSONDecodeError):
                pass
        if not modules:
            modules = [
                re.sub(r"\.Build\.cs$", "", p.name)
                for p in Path(root).rglob("*.Build.cs")
            ]
        return EngineInfo(
            engine="unreal", version_hint=version,
            source_globs=["Source/**/*.cpp", "Source/**/*.h", "Source/**/*.cs"],
            asset_globs=["Content/**/*.uasset", "Content/**/*.umap"],
            build_cmd='UnrealBuildTool <Target> <Platform> Development -project="<uproject>"',
            test_cmd='UnrealEditor-Cmd "<uproject>" -ExecCmds="Automation RunTests <Suite>; Quit" -unattended -nopause',
            entrypoints=[up.name] if up else [],
            conventions={
                "prefixes": "A=Actor, U=UObject, F=struct, E=enum, I=interface",
                "reflection": "UPROPERTY/UFUNCTION/UCLASS macros for anything the engine touches",
                "modules": "gameplay code in game modules, not the editor target; " + ", ".join(modules[:6]),
            },
            confidence=self.detect(root),
        )

    def expert_profile(self) -> ExpertProfile:
        return ExpertProfile(
            name="unreal",
            prompt="Unreal Engine C++ project. Gameplay classes derive from engine base types and use the reflection macros.",
            do=[
                "derive gameplay classes from AActor/UObject/UActorComponent as appropriate",
                "mark engine-visible members with UPROPERTY/UFUNCTION and classes with UCLASS",
                "use the A/U/F/E/I prefix convention",
                "put logic in game modules; keep editor-only code in an editor module",
                "use TObjectPtr / smart pointers, not raw new/delete for UObjects",
            ],
            dont=[
                "call engine APIs from a raw constructor (use BeginPlay / PostInitProperties)",
                "hand-edit .uasset / .umap",
                "block the game thread on long work",
            ],
        )
