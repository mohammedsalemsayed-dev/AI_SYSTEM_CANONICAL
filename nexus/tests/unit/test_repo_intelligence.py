"""Acceptance (Unit): Git adapter, symbol index, module graph, impact analysis,
breadth classification (MILESTONE_J_PLAN.md §6)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.services.capability.registry import is_side_effecting, spec_for
from app.services.repo.breadth import classify_breadth
from app.services.repo.git_adapter import GitAdapter, GitError
from app.services.repo.graph import ModuleGraph
from app.services.repo.impact import analyze
from app.services.repo.index import RepoIndex


def _git(d: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(d), "-c", "user.email=x@x", "-c", "user.name=x", *args],
                   check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    d = tmp_path / "r"
    (d / "pkg").mkdir(parents=True)
    (d / "pkg" / "__init__.py").write_text("", newline="\n")
    (d / "pkg" / "core.py").write_text(
        "def helper():\n    return 1\n\n\nclass Engine:\n    pass\n", newline="\n")
    (d / "pkg" / "api.py").write_text(
        "from pkg.core import helper, Engine\n\n\ndef run():\n    return helper()\n", newline="\n")
    (d / "pkg" / "cli.py").write_text("from pkg.api import run\n\nrun()\n", newline="\n")
    (d / "test_core.py").write_text(
        "from pkg.core import helper\n\n\ndef test_h():\n    assert helper() == 1\n", newline="\n")
    (d / "notes.md").write_text("# not source\n", newline="\n")
    _git(d, "init", "-q")
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "init")
    return d


# --- git adapter -------------------------------------------- #
def test_git_adapter_read_ops(repo: Path) -> None:
    g = GitAdapter(repo)
    assert g.is_repo()
    assert g.current_branch() in ("master", "main")
    assert len(g.head_sha()) == 40
    assert g.is_clean()
    tracked = g.tracked_files()
    assert "pkg/core.py" in tracked and "notes.md" in tracked
    assert g.log(limit=5)[0]["subject"] == "init"

    (repo / "pkg" / "core.py").write_text("def helper():\n    return 2\n", newline="\n")
    assert not g.is_clean()
    assert g.changed_files() == ["pkg/core.py"]
    st = g.status()
    assert "pkg/core.py" in st.unstaged


def test_git_adapter_bad_ref_raises_giterror(repo: Path) -> None:
    with pytest.raises(GitError):
        GitAdapter(repo).show("no-such-ref")


def test_git_adapter_write_is_gated(repo: Path) -> None:
    ro = GitAdapter(repo)  # write_allowed defaults to False
    with pytest.raises(GitError):
        ro.create_branch("feature/x")
    rw = GitAdapter(repo, write_allowed=lambda: True)
    assert rw.create_branch("feature/x") == "feature/x"
    (repo / "pkg" / "core.py").write_text("def helper():\n    return 9\n", newline="\n")
    assert len(rw.commit("tweak")) == 40


def test_no_network_subcommand_exposed() -> None:
    for banned in ("fetch", "pull", "push", "remote", "clone"):
        assert not hasattr(GitAdapter, banned)


# --- symbol index ---------------------------------------- #
def test_index_extracts_python_defs_and_imports(repo: Path) -> None:
    idx = RepoIndex.build(repo)
    core = idx.facts_for("pkg/core.py")
    assert core and core.lang == "python" and not core.approximate
    assert set(core.defs) == {"helper", "Engine"}
    api = idx.facts_for("pkg/api.py")
    assert "pkg.core" in api.imports
    assert idx.file_for("pkg.core") == "pkg/core.py"
    assert idx.symbols()["helper"] == ["pkg/core.py"]
    assert "notes.md" not in idx.files  # not a source suffix


def test_index_skips_broken_python_but_keeps_the_rest(repo: Path) -> None:
    (repo / "pkg" / "broken.py").write_text("def (:\n", newline="\n")
    idx = RepoIndex.build(repo)
    assert idx.facts_for("pkg/broken.py").error is not None
    assert idx.facts_for("pkg/broken.py").approximate
    assert idx.facts_for("pkg/core.py").defs  # others still indexed


def test_index_generic_fallback_is_flagged(tmp_path: Path) -> None:
    (tmp_path / "m.ts").write_text(
        "import { x } from './dep';\nexport function go() { return 1; }\n", newline="\n")
    idx = RepoIndex.build(tmp_path)
    ff = idx.facts_for("m.ts")
    assert ff.approximate and "go" in ff.defs


# --- module graph -------------------------------------- #
def test_graph_dependents_transitive_and_cycle_safe(repo: Path) -> None:
    idx = RepoIndex.build(repo)
    g = ModuleGraph.from_index(idx)
    assert g.dependencies("pkg.api") == {"pkg.core"}
    assert g.dependents("pkg.core") == {"pkg.api", "test_core"}
    assert "pkg.cli" in g.dependents("pkg.core", transitive=True)
    assert g.fan_in("pkg.core") == 2

    # introduce a cycle: core imports api
    (repo / "pkg" / "core.py").write_text(
        "import pkg.api\n\ndef helper():\n    return 1\n", newline="\n")
    g2 = ModuleGraph.from_index(RepoIndex.build(repo))
    assert "pkg.api" in g2.dependents("pkg.core", transitive=True)  # terminates


def test_reachable_dependents_excludes_the_changed_set(repo: Path) -> None:
    g = ModuleGraph.from_index(RepoIndex.build(repo))
    r = g.reachable_dependents({"pkg.core"})
    assert "pkg.core" not in r and "pkg.api" in r


# --- impact ------------------------------------------- #
def test_impact_leaf_change_is_narrow(repo: Path) -> None:
    idx = RepoIndex.build(repo)
    g = ModuleGraph.from_index(idx)
    rep = analyze(idx, g, changed_paths=["pkg/cli.py"])
    assert rep.changed_modules == ["pkg.cli"]
    assert rep.dependent_modules == []          # nothing imports cli
    assert "wide-change" not in rep.risk_flags


def test_impact_widely_imported_change_flags_and_selects_tests(repo: Path) -> None:
    (repo / "pkg" / "svc.py").write_text("from pkg.core import helper\n", newline="\n")
    (repo / "pkg" / "svc2.py").write_text("from pkg.core import Engine\n", newline="\n")
    idx = RepoIndex.build(repo)
    g = ModuleGraph.from_index(idx)
    rep = analyze(idx, g, changed_paths=["pkg/core.py"],
                  diff_text="-def helper():\n+def helper(x):\n")
    assert set(rep.changed_modules) == {"pkg.core"}
    assert {"pkg.api", "pkg.svc", "pkg.svc2"} <= set(rep.dependent_modules)
    assert "test_core.py" in rep.tests_affected
    assert "wide-change" in rep.risk_flags
    assert "public-api" in rep.risk_flags   # fan-in >= 3
    assert "signature-changed" in rep.risk_flags


def test_impact_risk_path_flag(repo: Path) -> None:
    (repo / "auth").mkdir()
    (repo / "auth" / "login.py").write_text("def check():\n    return True\n", newline="\n")
    idx = RepoIndex.build(repo)
    g = ModuleGraph.from_index(idx)
    rep = analyze(idx, g, changed_paths=["auth/login.py"],
                  risk_globs=["*/auth/*", "*auth*"])
    assert "risk-path" in rep.risk_flags


def test_impact_on_repo_without_source_is_empty_not_an_error(tmp_path: Path) -> None:
    idx = RepoIndex.build(tmp_path)
    g = ModuleGraph.from_index(idx)
    rep = analyze(idx, g, changed_paths=["whatever.txt"])
    assert rep.changed_modules == [] and rep.tests_affected == []


# --- breadth ----------------------------------------- #
def test_breadth_triggers(repo: Path) -> None:
    from app.schemas.contracts import ImpactReport

    local = ImpactReport(dependent_modules=["a", "b"], risk_flags=[])
    assert classify_breadth("code_edit_local", local).level == "local"
    assert classify_breadth("code_edit_broad", local).level == "broad"
    wide = ImpactReport(dependent_modules=["a", "b", "c", "d"], risk_flags=["wide-change"])
    assert classify_breadth("code_edit_local", wide).level == "broad"
    risky = ImpactReport(risk_flags=["risk-path"])
    adv = classify_breadth("code_edit_local", risky)
    assert adv.level == "broad" and adv.escalate_review


# --- capability tokens ------------------------------- #
def test_vcs_tokens_registered_and_write_is_side_effecting() -> None:
    assert spec_for("vcs.read") is not None
    assert spec_for("vcs.write") is not None
    assert is_side_effecting("vcs.commit") and is_side_effecting("vcs.branch")
    assert not is_side_effecting("vcs.read")
