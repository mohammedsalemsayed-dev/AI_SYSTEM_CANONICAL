"""Android / Gradle adapter (MILESTONE_N_PLAN.md §2)."""

from __future__ import annotations

import re
from pathlib import Path

from app.services.engines.base import EngineInfo, ExpertProfile

_INCLUDE = re.compile(r'include\s*\(?\s*["\']([:A-Za-z0-9_\-]+)["\']')
_COMPILE_SDK = re.compile(r'compileSdk(?:Version)?\s*[=(]?\s*["\']?(\d{2})')


class AndroidAdapter:
    name = "android"

    def _settings(self, root: str) -> Path | None:
        for n in ("settings.gradle", "settings.gradle.kts"):
            p = Path(root) / n
            if p.is_file():
                return p
        return None

    def detect(self, root: str) -> float:
        r = Path(root)
        settings = self._settings(root)
        has_manifest = any(r.rglob("AndroidManifest.xml"))
        if settings and has_manifest:
            return 0.9
        for g in list(r.glob("build.gradle")) + list(r.glob("*/build.gradle")):
            try:
                if "com.android.application" in g.read_text(encoding="utf-8", errors="replace"):
                    return 0.7
            except OSError:
                continue
        return 0.0

    def info(self, root: str) -> EngineInfo:
        r = Path(root)
        modules: list[str] = []
        settings = self._settings(root)
        if settings:
            try:
                modules = _INCLUDE.findall(settings.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass
        sdk = ""
        for g in list(r.rglob("build.gradle")) + list(r.rglob("build.gradle.kts")):
            try:
                m = _COMPILE_SDK.search(g.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if m:
                sdk = "API " + m.group(1)
                break
        return EngineInfo(
            engine="android", version_hint=sdk,
            source_globs=["**/src/main/java/**/*.java", "**/src/main/kotlin/**/*.kt", "**/*.kt"],
            asset_globs=["**/src/main/res/**", "**/AndroidManifest.xml"],
            build_cmd="./gradlew assembleDebug",
            test_cmd="./gradlew testDebugUnitTest connectedCheck",
            entrypoints=[settings.name] if settings else [],
            conventions={
                "structure": "package-by-feature; modules: " + ", ".join(modules[:8]),
                "arch": "state/logic in ViewModel, not Activity/Fragment",
                "resources": "strings/dimens/colors in res/, not hardcoded",
            },
            confidence=self.detect(root),
        )

    def expert_profile(self) -> ExpertProfile:
        return ExpertProfile(
            name="android",
            prompt="Android (Gradle) project. Follow modern Android architecture.",
            do=[
                "keep UI state and logic in a ViewModel; keep Activities/Fragments thin",
                "use the repository pattern for data; inject dependencies",
                "put user-facing strings and dimensions in res/",
                "respect the lifecycle; use coroutines/Flow for async",
            ],
            dont=[
                "do I/O or long work on the main thread",
                "hold a Context/View reference in a ViewModel",
                "hardcode strings, sizes, or colors in code",
            ],
        )
