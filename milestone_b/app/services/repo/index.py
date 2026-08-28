"""Symbol index (MILESTONE_J_PLAN.md §2, §11.3).

Per tracked source file: its module path, top-level definitions, and the modules
it imports. Python is parsed with `ast`; other languages get a coarse regex
fallback flagged `approximate`. Derived and rebuildable — held per task, never a
source of truth.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

INDEX_MAX_FILES = 2000
INDEX_MAX_BYTES_PER_FILE = 512 * 1024

_PY_SUFFIXES = {".py", ".pyi"}
_SOURCE_SUFFIXES = _PY_SUFFIXES | {
    ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".rb", ".c", ".h", ".cpp", ".cc",
}
_GENERIC_DEF = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?(?:def|function|func|class|fn|type|interface|struct)\s+([A-Za-z_][\w]*)",
    re.MULTILINE,
)
_GENERIC_IMPORT = re.compile(
    r"""^\s*(?:import\s+['"]?([\w./@-]+)|from\s+['"]?([\w./-]+)|require\(\s*['"]([\w./@-]+))""",
    re.MULTILINE,
)


@dataclass
class FileFacts:
    path: str            # repo-relative, forward slashes
    module: str          # dotted module (Python) or the path stem otherwise
    lang: str
    defs: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)  # dotted / normalised module names
    loc: int = 0
    approximate: bool = False
    error: str | None = None


def _module_name(rel: str) -> str:
    p = rel.replace("\\", "/")
    if p.endswith((".py", ".pyi")):
        p = p[: p.rfind(".")]
        if p.endswith("/__init__"):
            p = p[: -len("/__init__")]
        return p.replace("/", ".")
    return p.rsplit(".", 1)[0].replace("/", ".")


def _py_facts(rel: str, text: str) -> FileFacts:
    ff = FileFacts(path=rel, module=_module_name(rel), lang="python",
                   loc=text.count("\n") + 1)
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:  # skip this file, keep the rest
        ff.error = f"syntax error: {exc}"
        ff.approximate = True
        return ff
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            ff.defs.append(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    ff.defs.append(t.id)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            ff.imports += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            ff.imports.append(node.module)
        elif isinstance(node, ast.ImportFrom) and node.level:
            # relative import: resolve against this module's package
            pkg = ff.module.rsplit(".", node.level)[0] if "." in ff.module else ""
            ff.imports.append(f"{pkg}.{node.module}" if node.module and pkg else (node.module or pkg))
    ff.imports = sorted({i for i in ff.imports if i})
    ff.defs = sorted(set(ff.defs))
    return ff


def _generic_facts(rel: str, text: str, lang: str) -> FileFacts:
    ff = FileFacts(path=rel, module=_module_name(rel), lang=lang,
                   loc=text.count("\n") + 1, approximate=True)
    ff.defs = sorted({m.group(1) for m in _GENERIC_DEF.finditer(text)})
    imps = set()
    for m in _GENERIC_IMPORT.finditer(text):
        imps.add(next(g for g in m.groups() if g))
    ff.imports = sorted(i.replace("/", ".").lstrip(".") for i in imps)
    return ff


class RepoIndex:
    def __init__(self) -> None:
        self.files: dict[str, FileFacts] = {}  # path -> facts
        self._by_module: dict[str, str] = {}   # module -> path

    @classmethod
    def build(cls, root: str | Path, files: list[str] | None = None) -> "RepoIndex":
        root = Path(root)
        idx = cls()
        candidates = files if files is not None else [
            str(p.relative_to(root)).replace("\\", "/")
            for p in root.rglob("*")
            if p.is_file() and ".git" not in p.parts
        ]
        n = 0
        for rel in sorted(candidates):
            suf = Path(rel).suffix
            if suf not in _SOURCE_SUFFIXES:
                continue
            fp = root / rel
            try:
                if not fp.is_file() or fp.stat().st_size > INDEX_MAX_BYTES_PER_FILE:
                    continue
                text = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            ff = _py_facts(rel, text) if suf in _PY_SUFFIXES else _generic_facts(rel, text, suf.lstrip("."))
            idx.files[rel] = ff
            idx._by_module.setdefault(ff.module, rel)
            n += 1
            if n >= INDEX_MAX_FILES:
                break
        return idx

    # -- queries ------------------------------------------- #
    def modules(self) -> list[str]:
        return sorted(self._by_module)

    def file_for(self, module: str) -> str | None:
        return self._by_module.get(module)

    def facts_for(self, path: str) -> FileFacts | None:
        return self.files.get(path.replace("\\", "/"))

    def module_for_path(self, path: str) -> str | None:
        ff = self.facts_for(path)
        return ff.module if ff else None

    def symbols(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for rel, ff in self.files.items():
            for d in ff.defs:
                out.setdefault(d, []).append(rel)
        return out

    def is_internal(self, module: str) -> bool:
        """True if `module` (or a prefix of it) is defined in this repo."""
        parts = module.split(".")
        return any(".".join(parts[: i + 1]) in self._by_module for i in range(len(parts)))
