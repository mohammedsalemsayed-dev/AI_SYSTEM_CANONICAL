"""wire_full_stack must attach every optional roster member, including the ones
that were built earlier but left unconnected: the engine registry (N), the
bounded tool-use loop (T), the fitted model-selection controller (O) and the
persistent knowledge base (L)."""

from __future__ import annotations

from pathlib import Path

from app.cli.full_stack import wire_full_stack
from app.events.log import EventLog
from tests.integration.conftest import build_orchestrator


def _orch():
    return build_orchestrator(EventLog(), [], [])


def test_wire_full_stack_connects_engines_tool_loop_selection_kb(tmp_path: Path) -> None:
    orch = _orch()
    db = str(tmp_path / "ev.db")
    wired = wire_full_stack(orch, db_path=db, workspace=str(tmp_path), verbose=False)

    from app.services.engines.registry import EngineRegistry
    from app.services.kb.store import KnowledgeBase
    from app.services.routing.selection import ModelSelectionController
    from app.services.tools.loop import ToolLoop

    assert isinstance(orch.engines, EngineRegistry)
    assert isinstance(orch.tool_loop, ToolLoop)
    assert isinstance(orch.selection, ModelSelectionController)
    assert isinstance(orch.kb, KnowledgeBase)

    for tag in ("engines", "tool_loop", "selection", "kb"):
        assert any(w.startswith(tag) for w in wired), f"{tag} not reported wired"


def test_tool_loop_shares_the_tool_registry(tmp_path: Path) -> None:
    orch = _orch()
    wire_full_stack(orch, db_path=str(tmp_path / "ev.db"),
                    workspace=str(tmp_path), verbose=False)
    # the loop dispatches through the same registry the planner enumerates
    assert orch.tool_loop.dispatcher.registry is orch.tools
