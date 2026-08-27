"""Build premise repos from REAL open-source bug-fix history (more-itertools).

For each chosen fix commit: check out the tree at that commit (so the test the
fix added is present), revert ONLY the source-file change (keep the test), and
confirm the target test now fails. The task request is the commit's own subject.

    git clone --depth 250 https://github.com/more-itertools/more-itertools <SRC>
    python -m tests.premise.make_real_repos <SRC>

Writes premise_repos_real/ (git-ignored) + tasks.real.json.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_OUT = Path("premise_repos_real")
_TASKS = Path("tests/premise/tasks.real.json")


@dataclass
class Fix:
    id: str
    commit: str
    subject: str
    target: str  # pytest node id(s), space-separated, relative to repo root


FIXES = [
    Fix("mit-01-chunked-negative", "0e6acdf",
        "Raise a clear ValueError for negative n in chunked()",
        "tests/test_more.py::ChunkedTests::test_negative"),
    Fix("mit-02-interleave-evenly-empty", "f51a53b",
        "handle empty interleave_evenly input",
        "tests/test_more.py::InterleaveEvenlyTests::test_no_iterables"),
    Fix("mit-03-numeric-range-reversed-empty", "edb3346",
        "Fix empty ranges in numeric_range.__reversed__",
        "tests/test_more.py::NumericRangeTests::test_empty_reversed"),
    Fix("mit-04-product-index-iterator", "cf186b5",
        "Fix product_index() with iterator input",
        "tests/test_more.py::ProductIndexTests::test_iterator_input"),
    Fix("mit-05-running-min-max-stability", "d992be0",
        "Fix stability in running_min and running_max",
        "tests/test_more.py::TestRunningMin::test_stability "
        "tests/test_more.py::TestRunningMax::test_stability"),
]


def _force_rmtree(path: Path) -> None:
    def _on_error(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)

    shutil.rmtree(path, onexc=_on_error)


def _git(cwd: str | Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.email=real@local", "-c", "user.name=real",
         "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=str(cwd), capture_output=True, text=True, check=check,
    )


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    if not argv:
        print(__doc__)
        return 2
    src = Path(argv[0]).resolve()
    if not (src / ".git").exists():
        print(f"{src} is not a git clone of more-itertools", file=sys.stderr)
        return 2

    _OUT.mkdir(exist_ok=True)
    tasks = []
    for fix in FIXES:
        repo = _OUT / fix.id
        if repo.exists():
            _force_rmtree(repo)
        repo.mkdir(parents=True)

        # tree at the fix commit (test present)
        _git(src, "reset", "-q", "--hard", check=False)
        _git(src, "clean", "-qfdx", check=False)
        _git(src, "checkout", "-q", "-f", fix.commit)
        for item in src.iterdir():
            if item.name == ".git":
                continue
            dst = repo / item.name
            if item.is_dir():
                shutil.copytree(item, dst)
            else:
                shutil.copy2(item, dst)

        # revert ONLY the source change; keep the test
        src_patch = _git(src, "show", fix.commit, "--", "more_itertools/").stdout
        (repo / ".src.patch").write_bytes(src_patch.encode("utf-8"))
        _git(repo, "init", "-q")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "tree at fix commit")
        rev = _git(repo, "apply", "-R", "--whitespace=nowarn", ".src.patch", check=False)
        if rev.returncode != 0:
            print(f"[{fix.id}] could not revert source patch: {rev.stderr[:300]}",
                  file=sys.stderr)
            continue
        (repo / ".src.patch").unlink()
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "revert fix (bug reintroduced)")

        # confirm RED
        red = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *fix.target.split()],
            cwd=str(repo), capture_output=True, text=True,
        )
        status = "RED (good)" if red.returncode != 0 else "GREEN (!! not a valid case)"
        print(f"[{fix.id}] {status}")
        if red.returncode == 0:
            continue

        tasks.append({
            "id": fix.id,
            "request": f"{fix.subject}. The failing test is {fix.target}.",
            "workspace": str(repo.resolve()).replace("\\", "/"),
        })

    _git(src, "checkout", "-q", "-")
    _TASKS.write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {len(tasks)} real-bug repos under {_OUT}/ and {_TASKS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
