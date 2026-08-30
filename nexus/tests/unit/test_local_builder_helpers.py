"""Deterministic helpers in the local Builder loop: which repo files get
pre-loaded into the first prompt (so the model doesn't burn turns rediscovering
what it must satisfy)."""

from __future__ import annotations

from pathlib import Path

from app.schemas.contracts import TaskContract
from app.services.build.local_builder import _preload_paths


def _c(obj: str, ev: list[str]) -> TaskContract:
    return TaskContract(task_id="t", original_request="x", objective=obj,
                        task_class="code_edit_local", success_criteria=["ok"],
                        required_evidence=ev)


def test_preloads_the_target_test_and_the_module_it_imports(tmp_path: Path) -> None:
    (tmp_path / "shop").mkdir()
    (tmp_path / "shop" / "__init__.py").write_text("")
    (tmp_path / "shop" / "tax.py").write_text("def rate(): return 8.25\n")
    (tmp_path / "test_tax.py").write_text(
        "from shop.tax import rate\n\ndef test_rate():\n    assert rate() == 8.25\n"
    )
    got = _preload_paths(tmp_path, "test_tax.py",
                         _c("fix shop/tax.py", ["T0: pytest test_tax.py::test_rate passes"]))
    assert "test_tax.py" in got
    assert "shop/tax.py" in got or "shop/__init__.py" in got


def test_preloads_the_module_named_in_the_objective(tmp_path: Path) -> None:
    (tmp_path / "calc.py").write_text("def add(a, b): return a - b\n")
    (tmp_path / "test_calc.py").write_text("from calc import add\n")
    got = _preload_paths(tmp_path, "test_calc.py",
                         _c("fix add() in calc.py", ["T0: pytest test_calc.py passes"]))
    assert got[0] == "test_calc.py" and "calc.py" in got


def test_missing_target_yields_nothing(tmp_path: Path) -> None:
    assert _preload_paths(tmp_path, "nope_test.py",
                          _c("create nope.py", ["T0: pytest nope_test.py passes"])) == []


def test_capped_at_three(tmp_path: Path) -> None:
    for n in range(6):
        (tmp_path / f"m{n}.py").write_text("x = 1\n")
    (tmp_path / "test_x.py").write_text("import m0\nimport m1\nimport m2\nimport m3\n")
    got = _preload_paths(tmp_path, "test_x.py",
                         _c("fix m0.py m1.py m2.py m3.py", ["T0: pytest test_x.py passes"]))
    assert len(got) <= 3
