"""Fault suite: an egress failure during research does not crash the pipeline and
the research task still ends safely with an explicit uncertainty
(MILESTONE_Q_PLAN.md §6)."""

from __future__ import annotations

import json

from app.events.log import EventKind, EventLog
from app.llm.fake import ScriptedLLM
from app.services.agents.researcher import Researcher
from app.services.egress.broker import EgressBroker
from app.services.faults.model import Fault, FaultPlan
from app.services.faults.wrappers import flaky_opener
from app.services.research.pipeline import ResearchPipeline
from tests.fault.conftest import assert_safe, workspace_hash


_PAGES = {"https://docs.example/x": "The limit is 100 requests per minute."}


def _router(system: str, prompt: str) -> str:
    s = system.lower()
    if "sub-question" in s:
        return '{"sub_questions": ["what is the limit"]}'
    if "query planner" in s:
        return '{"urls": ["https://docs.example/x"]}'
    if "extract claims" in s:
        return '{"claims": [{"text": "limit is 100/min", "supported": true}]}'
    if "directly contradict" in s:
        return '{"contradictions": []}'
    if "synthesize a research answer" in s:
        return '{"sections": [], "uncertainty": "thin."}'
    return "{}"


def test_egress_flap_is_survived_by_the_pipeline() -> None:
    llm = ScriptedLLM(_router)
    opener = flaky_opener(lambda u, t: _PAGES.get(u, "").encode(),
                          FaultPlan.of(Fault("egress_flap", on_call=1, sticky=True)))
    broker = EgressBroker(allowlist=["docs.example"], opener=opener)
    pipe = ResearchPipeline(Researcher(llm, broker), llm)

    res = pipe.run("t", "what is the limit")   # every fetch raises URLError inside the broker
    assert res.answer.sections == [] or res.answer.citations == []
    assert "no sources" in res.answer.uncertainty or res.answer.uncertainty


def test_egress_flap_through_the_orchestrator_research_path(tmp_path) -> None:
    from app.orchestration.orchestrator import Orchestrator
    from app.services.build.fake import ScriptedBuilder
    from app.services.interpret.interpreter import Interpreter
    from app.services.plan.planner import Planner
    from app.services.policy.engine import PolicyEngine
    from app.services.verify.verifier_t0 import VerifierT0

    ws = str(tmp_path)
    before = workspace_hash(ws)
    log = EventLog()

    def interp(system: str, prompt: str) -> str:
        return json.dumps({
            "objective": "what is the limit", "task_class": "research_web",
            "success_criteria": ["cited synthesis"], "required_evidence": ["cross-check"],
            "assumptions": [], "ambiguity": [], "constraints": [], "risk_level": "low",
        })

    llm = ScriptedLLM(_router)
    opener = flaky_opener(lambda u, t: _PAGES.get(u, "").encode(),
                          FaultPlan.of(Fault("egress_flap", on_call=1, sticky=True)))
    broker = EgressBroker(allowlist=["docs.example"], opener=opener)

    orch = Orchestrator(
        log, Interpreter(ScriptedLLM(interp)), Planner(ScriptedLLM([])),
        ScriptedBuilder({}), VerifierT0(), PolicyEngine(),
    )
    orch.research = ResearchPipeline(Researcher(llm, broker), llm)

    result = orch.run("research the limit", ws)
    assert_safe(result, log, before, ws)
    # research verification is the cross-check + uncertainty statement -> still COMPLETED,
    # but with an explicit uncertainty and no side effect
    synth = [e for e in log.read(result.task_id) if e.kind == EventKind.SYNTHESIS]
    assert synth and synth[0].payload["uncertainty"]
    log.close()
