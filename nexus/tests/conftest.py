"""Shared fixtures for the slice tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_BUGGY_CALC = "def add(a, b):\n    return a - b\n"
_FIXED_CALC = "def add(a, b):\n    return a + b\n"
_TEST_CALC = (
    "from calc import add\n"
    "\n"
    "\n"
    "def test_add():\n"
    "    assert add(2, 3) == 5\n"
    "\n"
    "\n"
    "def test_add_zero():\n"
    "    assert add(0, 0) == 0\n"
)

FIXED_CALC = _FIXED_CALC
WRONG_CALC = "def add(a, b):\n    return a * b\n"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=slice@local",
            "-c",
            "user.name=slice",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.autocrlf=false",
            *args,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def sample_repo(tmp_path: Path) -> str:
    """A tiny git repo: `calc.py` with a bug (`a - b`) and `test_calc.py` whose
    `test_add` fails until `add` is fixed to `a + b`."""
    repo = tmp_path / "sample_repo"
    repo.mkdir()
    (repo / "calc.py").write_text(_BUGGY_CALC, encoding="utf-8", newline="\n")
    (repo / "test_calc.py").write_text(_TEST_CALC, encoding="utf-8", newline="\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "initial (buggy)")
    return str(repo)
