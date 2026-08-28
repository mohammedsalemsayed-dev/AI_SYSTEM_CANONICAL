"""Generic adapter (MILESTONE_N_PLAN.md §2). Always matches at a low floor;
picks the ecosystem's build/test command from the manifest file present."""

from __future__ import annotations

from pathlib import Path

from app.services.engines.base import EngineInfo, ExpertProfile

FLOOR = 0.05

_ECOSYSTEMS = [
    ("pyproject.toml", "python", "python -m pytest -q", "python -m build", ["*.py"]),
    ("setup.py", "python", "python -m pytest -q", "python setup.py sdist", ["*.py"]),
    ("package.json", "node", "npm test", "npm run build", ["*.js", "*.ts", "*.tsx"]),
    ("go.mod", "go", "go test ./...", "go build ./...", ["*.go"]),
    ("Cargo.toml", "rust", "cargo test", "cargo build --release", ["*.rs"]),
    ("pom.xml", "java", "mvn -q test", "mvn -q package", ["*.java"]),
    ("build.gradle", "java", "./gradlew test", "./gradlew build", ["*.java", "*.kt"]),
    ("build.gradle.kts", "java", "./gradlew test", "./gradlew build", ["*.java", "*.kt"]),
]


class GenericAdapter:
    name = "generic"

    def detect(self, root: str) -> float:
        return FLOOR

    def info(self, root: str) -> EngineInfo:
        r = Path(root)
        for manifest, eco, test_cmd, build_cmd, globs in _ECOSYSTEMS:
            if (r / manifest).is_file():
                return EngineInfo(
                    engine=eco, source_globs=globs, build_cmd=build_cmd,
                    test_cmd=test_cmd, entrypoints=[manifest], confidence=FLOOR,
                    conventions={"style": f"follow the {eco} project's existing conventions"},
                )
        return EngineInfo(engine="generic", confidence=FLOOR)

    def expert_profile(self) -> ExpertProfile:
        return ExpertProfile(
            name="generic",
            prompt="Match the surrounding code: its conventions, comment density, and idioms.",
            do=["read a nearby file before writing", "keep the change minimal and local"],
            dont=["introduce a new dependency or framework without cause"],
        )
