"""RepoIntelligence facade (MILESTONE_J_PLAN.md §2).

Bundles the Git adapter + symbol index + module graph. Builds the index lazily
and caches it by `HEAD` sha (rebuilt when HEAD moves — the index is derived, §11.3).
Provides the two things the orchestrator needs: a `REPO CONTEXT` block for the
Planner, and an `ImpactReport` for a diff.
"""

from __future__ import annotations

from pathlib import Path

from app.schemas.contracts import BreadthAdvice, ImpactReport
from app.services.policy.engine import DEFAULT_RISK_GLOBS
from app.services.repo.breadth import classify_breadth
from app.services.repo.git_adapter import GitAdapter, GitError
from app.services.repo.graph import ModuleGraph
from app.services.repo.impact import analyze
from app.services.repo.index import RepoIndex

_TOP_MODULES = 12


class RepoIntelligence:
    def __init__(self, root: str, *, write_allowed=None, risk_globs: list[str] | None = None) -> None:
        self.root = str(Path(root).resolve())
        self.git = GitAdapter(self.root, write_allowed=write_allowed)
        self.risk_globs = list(risk_globs) if risk_globs is not None else list(DEFAULT_RISK_GLOBS)
        self._cache_key: str | None = None
        self._index: RepoIndex | None = None
        self._graph: ModuleGraph | None = None

    # -- lazy build ------------------------------------------ #
    def _ensure(self) -> None:
        key = "no-git"
        files: list[str] | None = None
        if self.git.is_repo():
            try:
                key = self.git.head_sha()
                files = self.git.tracked_files()
            except GitError:
                key = "dirty"
        if self._index is not None and self._cache_key == key:
            return
        self._index = RepoIndex.build(self.root, files=files)
        self._graph = ModuleGraph.from_index(self._index)
        self._cache_key = key

    @property
    def index(self) -> RepoIndex:
        self._ensure()
        assert self._index is not None
        return self._index

    @property
    def graph(self) -> ModuleGraph:
        self._ensure()
        assert self._graph is not None
        return self._graph

    # -- planner context ---------------------------------- #
    def context_block(self, objective: str) -> str:
        self._ensure()
        idx, g = self._index, self._graph
        assert idx is not None and g is not None
        if not idx.files:
            return ""

        ranked = sorted(idx.modules(), key=lambda m: (-g.fan_in(m), m))[:_TOP_MODULES]
        lines = [
            "REPO CONTEXT",
            f"- {len(idx.files)} source files, {len(idx.modules())} modules"
            + (f", HEAD {self._cache_key[:10]}" if self._cache_key and len(self._cache_key) >= 10 else ""),
            "- most-depended-on modules: "
            + ", ".join(f"{m} (<-{g.fan_in(m)})" for m in ranked if g.fan_in(m)),
        ]

        obj = objective.lower()
        named = [
            rel for rel, ff in idx.files.items()
            if Path(rel).stem.lower() in obj or ff.module.split(".")[-1].lower() in obj
        ]
        for rel in named[:5]:
            ff = idx.facts_for(rel)
            mod = ff.module if ff else rel
            deps = sorted(g.dependencies(mod))[:6]
            rdeps = sorted(g.dependents(mod))[:6]
            lines.append(
                f"- {rel}: imports [{', '.join(deps)}]  imported-by [{', '.join(rdeps)}]"
            )
        return "\n".join(lines) + "\n"

    # -- impact ------------------------------------------ #
    def impact_for(self, changed_paths: list[str], diff_text: str = "") -> ImpactReport:
        self._ensure()
        assert self._index is not None and self._graph is not None
        return analyze(
            self._index, self._graph,
            changed_paths=changed_paths, diff_text=diff_text, risk_globs=self.risk_globs,
        )

    def breadth(self, interpreter_hint: str, impact: ImpactReport) -> BreadthAdvice:
        return classify_breadth(interpreter_hint, impact)
