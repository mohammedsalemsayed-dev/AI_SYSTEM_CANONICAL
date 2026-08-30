"""Acceptance (Integration): the deliverable paths store versioned,
content-addressed artifacts with lineage and trust (MILESTONE_P_PLAN.md §6)."""

from __future__ import annotations

import json
import threading
import urllib.request

from app.events.log import EventKind, EventLog
from app.llm.fake import ScriptedLLM
from app.services.artifacts.store import ArtifactStore
from tests.conftest import FIXED_CALC, WRONG_CALC
from tests.integration.conftest import build_orchestrator, interpreter_reply, planner_reply


def test_code_task_stores_a_diff_artifact_and_result_resolves(sample_repo: str) -> None:
    log = EventLog()
    store = ArtifactStore()
    orch = build_orchestrator(
        log, llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    orch.artifacts = store

    r = orch.run("fix the add function", sample_repo)
    assert r.state == "COMPLETED"

    art_ev = [e for e in log.read(r.task_id)
              if e.kind == EventKind.ARTIFACT and e.payload.get("store_id")]
    assert art_ev
    store_id = art_ev[0].payload["store_id"]
    assert r.artifact_ref == store_id
    ref = store.get(store_id)
    assert ref and ref.kind == "diff" and ref.trust == "workspace"
    assert "def add" in store.text(store_id)
    store.close()
    log.close()


def test_rerun_supersedes_with_a_parent_link(sample_repo: str) -> None:
    log = EventLog()
    store = ArtifactStore()

    # run 1: a wrong fix (fails T0), run 2: the right fix — same objective
    orch = build_orchestrator(
        log,
        llm_replies=[interpreter_reply(), planner_reply(),
                     interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    orch.artifacts = store
    orch.run("make calc.add return a + b", sample_repo)
    orch.run("make calc.add return a + b", sample_repo)

    # both runs used the same objective -> one logical_key, two versions
    keys = {
        e.payload["logical_key"]
        for tid in log.task_ids()
        for e in log.read(tid)
        if e.kind == EventKind.ARTIFACT and e.payload.get("logical_key")
    }
    assert len(keys) == 1
    hist = store.history(next(iter(keys)))
    assert len(hist) == 2 and hist[0].parent_id == hist[1].id
    store.close()
    log.close()


def test_research_answer_artifact_keeps_its_trust() -> None:
    import sys
    sys.path.insert(0, "tests/integration")
    from test_research_pipeline import _pipeline  # reuse the K fixture pipeline

    from app.orchestration.orchestrator import Orchestrator
    from app.services.build.fake import ScriptedBuilder
    from app.services.interpret.interpreter import Interpreter
    from app.services.plan.planner import Planner
    from app.services.policy.engine import PolicyEngine
    from app.services.verify.verifier_t0 import VerifierT0

    log = EventLog()
    store = ArtifactStore()

    def interp(system: str, prompt: str) -> str:
        return json.dumps({
            "objective": "explain the API rate limit and auth", "task_class": "research_web",
            "success_criteria": ["cited synthesis"], "required_evidence": ["cross-check"],
            "assumptions": [], "ambiguity": [], "constraints": [], "risk_level": "low",
        })

    orch = Orchestrator(
        log, Interpreter(ScriptedLLM(interp)), Planner(ScriptedLLM([])),
        ScriptedBuilder({}), VerifierT0(), PolicyEngine(),
    )
    orch.research = _pipeline()
    orch.artifacts = store

    r = orch.run("research the rate limit and auth", ".")
    assert r.state == "COMPLETED"
    ref = store.get(r.artifact_ref)
    assert ref and ref.kind == "research_answer" and ref.trust == "retrieved_web"
    assert json.loads(store.text(r.artifact_ref))["trust_level"] == "retrieved_web"
    store.close()
    log.close()


def test_shell_serves_artifact_content(sample_repo: str, tmp_path) -> None:
    import urllib.error

    from app.ui.server import UIServer

    dbf = str(tmp_path / "ev.db")
    log = EventLog(dbf)
    store = ArtifactStore()
    orch = build_orchestrator(
        log, llm_replies=[interpreter_reply(), planner_reply()],
        builder_edits={"calc.py": FIXED_CALC},
    )
    orch.artifacts = store
    r = orch.run("fix the add function", sample_repo)
    log.close()

    srv = UIServer(("127.0.0.1", 0), db_path=dbf, artifacts=store)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with urllib.request.urlopen(base + f"/api/artifacts/{r.artifact_ref}", timeout=5) as resp:
            body = json.loads(resp.read())
        assert body["ref"]["kind"] == "diff" and "def add" in body["text"]
        try:
            urllib.request.urlopen(base + "/api/artifacts/nope", timeout=5)
            assert False, "expected 404"
        except urllib.error.HTTPError as e:
            assert e.code == 404
    finally:
        srv.shutdown()
        store.close()
