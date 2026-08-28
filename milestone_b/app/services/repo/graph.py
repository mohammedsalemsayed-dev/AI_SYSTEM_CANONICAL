"""Module dependency graph (MILESTONE_J_PLAN.md §2).

Directed import edges between *internal* modules, derived from the symbol index.
`reachable_dependents(changed)` is the candidate blast radius for a change.
Cycle-safe.
"""

from __future__ import annotations

from collections import deque

from app.services.repo.index import RepoIndex


class ModuleGraph:
    def __init__(self) -> None:
        self._deps: dict[str, set[str]] = {}      # module -> modules it imports
        self._rev: dict[str, set[str]] = {}       # module -> modules that import it

    @classmethod
    def from_index(cls, index: RepoIndex) -> "ModuleGraph":
        g = cls()
        internal = set(index.modules())
        for rel, ff in index.files.items():
            src = ff.module
            g._deps.setdefault(src, set())
            g._rev.setdefault(src, set())
            for imp in ff.imports:
                target = cls._resolve(imp, internal)
                if target is None or target == src:
                    continue
                g._deps.setdefault(src, set()).add(target)
                g._rev.setdefault(target, set()).add(src)
                g._deps.setdefault(target, set())
                g._rev.setdefault(src, set())
        return g

    @staticmethod
    def _resolve(imported: str, internal: set[str]) -> str | None:
        """Longest internal-module prefix of `imported` (handles `pkg.mod.name`)."""
        parts = imported.split(".")
        for i in range(len(parts), 0, -1):
            cand = ".".join(parts[:i])
            if cand in internal:
                return cand
        return None

    # -- queries ------------------------------------------- #
    def modules(self) -> list[str]:
        return sorted(set(self._deps) | set(self._rev))

    def dependencies(self, module: str, *, transitive: bool = False) -> set[str]:
        return self._walk(module, self._deps) if transitive else set(self._deps.get(module, set()))

    def dependents(self, module: str, *, transitive: bool = False) -> set[str]:
        return self._walk(module, self._rev) if transitive else set(self._rev.get(module, set()))

    def reachable_dependents(self, changed: set[str]) -> set[str]:
        out: set[str] = set()
        for m in changed:
            out |= self._walk(m, self._rev)
        return out - set(changed)

    def fan_in(self, module: str) -> int:
        return len(self._rev.get(module, set()))

    def _walk(self, start: str, adj: dict[str, set[str]]) -> set[str]:
        seen: set[str] = set()
        q = deque(adj.get(start, set()))
        while q:
            m = q.popleft()
            if m in seen:
                continue
            seen.add(m)
            q.extend(adj.get(m, set()) - seen)
        return seen
