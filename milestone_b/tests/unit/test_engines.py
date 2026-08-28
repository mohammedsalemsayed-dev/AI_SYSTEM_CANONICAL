"""Acceptance (Unit): engine detection, EngineInfo, expert profiles, registry
(MILESTONE_N_PLAN.md §6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.engines.base import render_profile
from app.services.engines.profiles import domain_names, profile_from_constraints
from app.services.engines.registry import EngineRegistry


def _sub(tmp_path: Path, name: str) -> Path:
    d = tmp_path / name
    d.mkdir()
    return d


@pytest.fixture
def godot_repo(tmp_path: Path) -> str:
    d = _sub(tmp_path, "godot")
    (d / "project.godot").write_text(
        'config_version=5\n[application]\nconfig/features=PackedStringArray("4.2")\n', encoding="utf-8")
    (d / "player.gd").write_text("extends CharacterBody2D\n", encoding="utf-8")
    (d / "main.tscn").write_text("[gd_scene format=3]\n", encoding="utf-8")
    return str(d)


@pytest.fixture
def unreal_repo(tmp_path: Path) -> str:
    d = _sub(tmp_path, "unreal")
    (d / "Game.uproject").write_text(
        '{"EngineAssociation": "5.3", "Modules": [{"Name": "Game"}]}', encoding="utf-8")
    src = d / "Source" / "Game"
    src.mkdir(parents=True)
    (src / "Game.Build.cs").write_text("public class Game : ModuleRules {}", encoding="utf-8")
    return str(d)


@pytest.fixture
def android_repo(tmp_path: Path) -> str:
    d = _sub(tmp_path, "android")
    (d / "settings.gradle").write_text('include(":app")\ninclude(":core")\n', encoding="utf-8")
    app = d / "app" / "src" / "main"
    app.mkdir(parents=True)
    (app / "AndroidManifest.xml").write_text("<manifest/>", encoding="utf-8")
    (d / "app" / "build.gradle").write_text(
        "android { compileSdk 34 }\napply plugin: 'com.android.application'\n", encoding="utf-8")
    return str(d)


@pytest.fixture
def python_repo(tmp_path: Path) -> str:
    d = _sub(tmp_path, "py")
    (d / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    (d / "m.py").write_text("x = 1\n", encoding="utf-8")
    return str(d)


def test_each_adapter_detects_its_own_and_not_the_others(
    godot_repo, unreal_repo, android_repo, python_repo
) -> None:
    reg = EngineRegistry()
    assert reg.detect(godot_repo)[0].name == "godot"
    assert reg.detect(unreal_repo)[0].name == "unreal"
    assert reg.detect(android_repo)[0].name == "android"
    assert reg.detect(python_repo)[0].name == "generic"

    from app.services.engines.godot import GodotAdapter

    assert GodotAdapter().detect(python_repo) == 0.0


def test_engine_info_fields(godot_repo, unreal_repo, android_repo, python_repo) -> None:
    reg = EngineRegistry()
    g = reg.detect(godot_repo)[1]
    assert g.engine == "godot" and g.version_hint == "4.2"
    assert "*.gd" in g.source_globs and "headless" in g.test_cmd and g.conventions

    u = reg.detect(unreal_repo)[1]
    assert u.engine == "unreal" and u.version_hint == "5.3"
    assert "Automation RunTests" in u.test_cmd

    a = reg.detect(android_repo)[1]
    assert a.engine == "android" and "API 34" == a.version_hint
    assert "gradlew" in a.test_cmd and "core" in a.conventions["structure"]

    p = reg.detect(python_repo)[1]
    assert p.engine == "python" and p.test_cmd == "python -m pytest -q"


def test_registry_prefers_specific_over_generic(tmp_path: Path) -> None:
    # a repo that is both Gradle-ish and generic -> android wins
    (tmp_path / "settings.gradle").write_text('include(":app")', encoding="utf-8")
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "AndroidManifest.xml").write_text("<manifest/>", encoding="utf-8")
    (tmp_path / "build.gradle").write_text("android {}", encoding="utf-8")
    assert EngineRegistry().detect(str(tmp_path))[0].name == "android"
    # empty repo -> generic, never nothing
    empty = tmp_path / "empty"
    empty.mkdir()
    ad, info = EngineRegistry().detect(str(empty))
    assert ad.name == "generic" and info.engine == "generic"


def test_expert_profiles_render_bounded_blocks(godot_repo) -> None:
    reg = EngineRegistry()
    ad, info = reg.detect(godot_repo)
    block = render_profile(ad.expert_profile(), info)
    assert block.startswith("EXPERT MODE") and block.count("\n") <= 12
    assert "do:" in block and "don't:" in block and "ENGINE: godot" in block


def test_domain_profile_selection() -> None:
    assert "security-review" in domain_names()
    p = profile_from_constraints(["risk_level: low", "expert: security-review"])
    assert p and p.name == "security-review"
    assert profile_from_constraints(["expert: nonsense"]) is None
    assert profile_from_constraints(["no expert here"]) is None
