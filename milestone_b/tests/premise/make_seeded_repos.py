"""Generate ~10 tiny git repos, each with one small real bug and a failing
pytest, for the Day 10 premise run (MILESTONE_B_PLAN.md section 7).

    python -m tests.premise.make_seeded_repos          # writes premise_repos/ + tasks.seeded.json

Each repo has one module + one test file, `git init`, one commit. The listed
`fixed` string is NOT written — it's only recorded here so a human scorer can
compare. `premise_repos/` is git-ignored.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path


def _force_rmtree(path: Path) -> None:
    def _on_error(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)  # git marks pack/object files read-only on Windows
        func(p)

    shutil.rmtree(path, onexc=_on_error)

_ROOT = Path("premise_repos")
_TASKS = Path("tests/premise/tasks.seeded.json")


@dataclass
class Seed:
    id: str
    request: str
    module_name: str
    buggy: str
    test: str
    target: str  # pytest node id, relative to repo root


SEEDS: list[Seed] = [
    Seed(
        "01-pagination-off-by-one",
        "paginate() includes one extra item on the last page. Fix it.",
        "paginate.py",
        "def paginate(items, page, size):\n"
        "    start = page * size\n"
        "    end = start + size + 1\n"
        "    return items[start:end]\n",
        "from paginate import paginate\n\n"
        "def test_full_page():\n"
        "    assert paginate(list(range(10)), 0, 3) == [0, 1, 2]\n\n"
        "def test_last_page():\n"
        "    assert paginate(list(range(7)), 2, 3) == [6]\n",
        "test_paginate.py",
    ),
    Seed(
        "02-boundary-operator",
        "is_adult() should treat exactly 18 as an adult but currently doesn't.",
        "age.py",
        "def is_adult(age):\n    return age > 18\n",
        "from age import is_adult\n\n"
        "def test_eighteen_is_adult():\n    assert is_adult(18) is True\n\n"
        "def test_seventeen_is_not():\n    assert is_adult(17) is False\n",
        "test_age.py",
    ),
    Seed(
        "03-missing-empty-guard",
        "average() raises ZeroDivisionError on an empty list; it should return 0.0.",
        "stats.py",
        "def average(xs):\n    return sum(xs) / len(xs)\n",
        "from stats import average\n\n"
        "def test_normal():\n    assert average([2, 4]) == 3.0\n\n"
        "def test_empty_returns_zero():\n    assert average([]) == 0.0\n",
        "test_stats.py",
    ),
    Seed(
        "04-int-vs-float-division",
        "midpoint() should return the true (float) midpoint, not a floored int.",
        "geom.py",
        "def midpoint(a, b):\n    return (a + b) // 2\n",
        "from geom import midpoint\n\n"
        "def test_even():\n    assert midpoint(0, 4) == 2.0\n\n"
        "def test_odd():\n    assert midpoint(0, 5) == 2.5\n",
        "test_geom.py",
    ),
    Seed(
        "05-mutable-default-arg",
        "add_tag() leaks tags between calls because of a mutable default argument.",
        "tags.py",
        "def add_tag(tag, tags=[]):\n    tags.append(tag)\n    return tags\n",
        "from tags import add_tag\n\n"
        "def test_first_call():\n    assert add_tag('a') == ['a']\n\n"
        "def test_second_call_is_independent():\n    add_tag('a')\n    assert add_tag('b') == ['b']\n",
        "test_tags.py",
    ),
    Seed(
        "06-wrong-dict-key",
        "user_city() reads the wrong key and returns None for the city.",
        "profile.py",
        "def user_city(user):\n    return user.get('town')\n",
        "from profile import user_city\n\n"
        "def test_city():\n    assert user_city({'name': 'Sam', 'city': 'Cairo'}) == 'Cairo'\n",
        "test_profile.py",
    ),
    Seed(
        "07-inverted-boolean",
        "can_publish() has its logic inverted — drafts can publish and finished posts can't.",
        "publish.py",
        "def can_publish(post):\n    return not post.get('ready', False)\n",
        "from publish import can_publish\n\n"
        "def test_ready_can_publish():\n    assert can_publish({'ready': True}) is True\n\n"
        "def test_draft_cannot():\n    assert can_publish({'ready': False}) is False\n",
        "test_publish.py",
    ),
    Seed(
        "08-missing-normalization",
        "lookup() misses entries when the query has surrounding whitespace or different case.",
        "directory.py",
        "PEOPLE = {'alice': 1, 'bob': 2}\n\n"
        "def lookup(name):\n    return PEOPLE.get(name)\n",
        "from directory import lookup\n\n"
        "def test_exact():\n    assert lookup('alice') == 1\n\n"
        "def test_messy():\n    assert lookup('  Bob ') == 2\n",
        "test_directory.py",
    ),
    Seed(
        "09-accumulator-init",
        "product() starts its accumulator at 0, so every result is 0.",
        "arith.py",
        "def product(xs):\n    total = 0\n    for x in xs:\n        total *= x\n    return total\n",
        "from arith import product\n\n"
        "def test_product():\n    assert product([2, 3, 4]) == 24\n\n"
        "def test_empty_is_one():\n    assert product([]) == 1\n",
        "test_arith.py",
    ),
    Seed(
        "10-returns-first-not-all",
        "find_even() returns only the first even number; it should return all of them.",
        "filters.py",
        "def find_even(xs):\n    for x in xs:\n        if x % 2 == 0:\n            return [x]\n    return []\n",
        "from filters import find_even\n\n"
        "def test_all_evens():\n    assert find_even([1, 2, 3, 4, 5, 6]) == [2, 4, 6]\n\n"
        "def test_none():\n    assert find_even([1, 3]) == []\n",
        "test_filters.py",
    ),
]


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.email=seed@local", "-c", "user.name=seed",
         "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    )


def _request_with_test(seed: Seed) -> str:
    return f"{seed.request} The failing test is {seed.target}."


def main() -> int:
    _ROOT.mkdir(exist_ok=True)
    tasks = []
    for seed in SEEDS:
        repo = _ROOT / seed.id
        if repo.exists():
            _force_rmtree(repo)
        repo.mkdir(parents=True)
        (repo / seed.module_name).write_text(seed.buggy, encoding="utf-8", newline="\n")
        test_file = seed.target.split("::")[0]
        (repo / test_file).write_text(seed.test, encoding="utf-8", newline="\n")
        _git(repo, "init", "-q")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "seed (buggy)")
        tasks.append(
            {
                "id": seed.id,
                "request": _request_with_test(seed),
                "workspace": str(repo.resolve()).replace("\\", "/"),
            }
        )
    _TASKS.write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(tasks)} repos under {_ROOT}/ and {_TASKS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
