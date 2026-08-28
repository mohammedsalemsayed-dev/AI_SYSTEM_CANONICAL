"""Blast-radius analysis — "what could this change break" (MILESTONE_J_PLAN.md §2).

Given the paths a diff touches (and, optionally, the diff text), compute the
transitive dependent modules, the tests that cover the neighbourhood, and a set
of risk flags. Import-graph reachability is a *superset heuristic* for the common
case, not a proof — T0 stays authoritative.
"""

from __future__ import annotations

import re

from app.schemas.contracts import ImpactReport
from app.services.repo.graph import ModuleGraph
from app.services.repo.index import RepoIndex

PUBLIC_FANIN = 3
BROAD_MODULES = 3
TESTS_AFFECTED_CAP = 50

_TEST_RE = re.compile(r"(^|/)(test_[^/]+\.py|[^/]+_test\.py|conftest\.py)$")
_DEF_REMOVED = re.compile(r"^-\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)", re.MULTILINE)
_DEF_ADDED = re.compile(r"^\+\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)", re.MULTILINE)
_SIG_LINE = re.compile(r"^[+-]\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(", re.MULTILINE)


def _is_test(path: str) -> bool:
    return bool(_TEST_RE.search(path.replace("\\", "/")))


def _match_glob(path: str, globs: list[str]) -> bool:
    from fnmatch import fnmatch

    p = path.replace("\\", "/")
    return any(fnmatch(p, g) or fnmatch("/" + p, g) for g in globs)


def analyze(
    index: RepoIndex,
    graph: ModuleGraph,
    *,
    changed_paths: list[str],
    diff_text: str = "",
    risk_globs: list[str] | None = None,
) -> ImpactReport:
    risk_globs = risk_globs or []
    changed_paths = [p.replace("\\", "/") for p in changed_paths]

    changed_modules = sorted(
        {m for p in changed_paths if (m := index.module_for_path(p))}
    )
    _all_dependents = graph.reachable_dependents(set(changed_modules))
    # tests are reported separately (tests_affected); "dependent_modules" and the
    # wide-change signal are about production code breadth
    dependent_modules = sorted(
        m for m in _all_dependents
        if (fp := index.file_for(m)) and not _is_test(fp)
    )

    touched_symbols: set[str] = set()
    for p in changed_paths:
        ff = index.facts_for(p)
        if ff:
            touched_symbols |= set(ff.defs)
    # narrow to symbols actually in the diff, if we have one
    if diff_text:
        in_diff = set(_DEF_REMOVED.findall(diff_text)) | set(_DEF_ADDED.findall(diff_text))
        if in_diff:
            touched_symbols &= in_diff | touched_symbols  # keep all; diff just informs flags

    # approximate reverse symbol references: any def name that textually appears
    # in a dependent module's file
    dependent_symbols: set[str] = set()
    dep_paths = {index.file_for(m) for m in dependent_modules} - {None}
    for dp in dep_paths:
        ff = index.facts_for(dp) if dp else None
        if not ff:
            continue
        for sym in touched_symbols:
            if sym in ff.defs or sym in ff.imports:
                dependent_symbols.add(sym)

    # tests: any test file importing a changed or dependent module
    affected_mods = set(changed_modules) | set(dependent_modules)
    tests: list[tuple[int, str]] = []
    for rel, ff in index.files.items():
        if not _is_test(rel):
            continue
        hit = affected_mods & set(_prefixes(ff.imports))
        if hit or rel in changed_paths:
            tests.append((max((graph.fan_in(m) for m in hit), default=0), rel))
    tests.sort(key=lambda t: (-t[0], t[1]))
    tests_affected = [rel for _, rel in tests[:TESTS_AFFECTED_CAP]]

    # risk flags
    flags: list[str] = []
    if any(_match_glob(p, risk_globs) for p in changed_paths):
        flags.append("risk-path")
    if any(graph.fan_in(m) >= PUBLIC_FANIN for m in changed_modules):
        flags.append("public-api")
    if len(dependent_modules) > BROAD_MODULES:
        flags.append("wide-change")
    if diff_text:
        removed = set(_DEF_REMOVED.findall(diff_text))
        added = set(_DEF_ADDED.findall(diff_text))
        if removed - added:
            flags.append("symbol-removed")
        sig_names = _SIG_LINE.findall(diff_text)
        if sig_names and any(sig_names.count(n) >= 2 for n in set(sig_names)):
            flags.append("signature-changed")

    approx = any(
        (ff := index.facts_for(p)) and ff.approximate for p in changed_paths
    ) or bool(dependent_symbols)

    return ImpactReport(
        changed_paths=changed_paths,
        changed_modules=changed_modules,
        dependent_modules=dependent_modules,
        touched_symbols=sorted(touched_symbols),
        dependent_symbols=sorted(dependent_symbols),
        tests_affected=tests_affected,
        risk_flags=sorted(set(flags)),
        approximate=approx,
    )


def _prefixes(modules: list[str]) -> set[str]:
    out: set[str] = set()
    for m in modules:
        parts = m.split(".")
        for i in range(len(parts)):
            out.add(".".join(parts[: i + 1]))
    return out
