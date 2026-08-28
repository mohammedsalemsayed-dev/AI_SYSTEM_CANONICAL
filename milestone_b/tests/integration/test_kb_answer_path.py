"""Acceptance (Integration): a `doc_analysis` task runs the KB answer path; a KB
augments the research pipeline with `doc_input` sources (MILESTONE_L_PLAN.md §6)."""

from __future__ import annotations

import json

from app.events.log import EventKind, EventLog
from app.llm.fake import ScriptedLLM
from app.services.kb.store import KnowledgeBase


def _seed_kb() -> KnowledgeBase:
    kb = KnowledgeBase()
    kb.ingest_text("# Rate limit\n\nThe service allows 100 requests per minute on the free tier "
                   "and 1000 on the paid tier.", uri="limits.md", title="Limits")
    kb.ingest_text("# Authentication\n\nClients authenticate with a bearer token in the "
                   "Authorization header. Tokens expire after 24 hours.", uri="auth.md", title="Auth")
    kb.ingest_text("# Deployment\n\nRun docker compose up to start. Health check on port 8080.",
                   uri="deploy.md", title="Deploy")
    return kb


def _kb_llm(system: str, prompt: str) -> str:
    s = system.lower()
    if "extract factual claims" in s:
        if "requests per minute" in prompt:
            return '{"claims": [{"text": "100 req/min free, 1000 paid", "supported": true}]}'
        if "bearer token" in prompt:
            return '{"claims": [{"text": "auth uses a bearer token that expires after 24h", "supported": true}]}'
        return '{"claims": []}'
    if "synthesize a research answer" in s:
        return ('{"sections": [{"statement": "Rate limit is 100/min free, 1000 paid.", "citation_ids": []}], '
                '"uncertainty": "from the local library."}')
    return "{}"


def test_doc_analysis_task_returns_cited_kb_answer() -> None:
    log = EventLog()
    kb = _seed_kb()

    def interp(system: str, prompt: str) -> str:
        return json.dumps({
            "objective": "what is the rate limit and how does auth work",
            "task_class": "doc_analysis",
            "success_criteria": ["a cited answer from the library"],
            "required_evidence": ["retrieval + claims-only synthesis"],
            "assumptions": [], "ambiguity": [], "constraints": [], "risk_level": "low",
        })

    from app.orchestration.orchestrator import Orchestrator
    from app.services.build.fake import ScriptedBuilder
    from app.services.interpret.interpreter import Interpreter
    from app.services.plan.planner import Planner
    from app.services.policy.engine import PolicyEngine
    from app.services.verify.verifier_t0 import VerifierT0

    orch = Orchestrator(
        log, Interpreter(ScriptedLLM(interp)), Planner(ScriptedLLM(_kb_llm)),
        ScriptedBuilder({}), VerifierT0(), PolicyEngine(),
    )
    orch.kb = kb

    r = orch.run("check the docs for the rate limit and auth", ".")
    assert r.state == "COMPLETED" and r.verified
    kinds = {e.kind for e in log.read(r.task_id)}
    assert EventKind.KB in kinds and EventKind.SYNTHESIS in kinds
    synth = [e for e in log.read(r.task_id) if e.kind == EventKind.SYNTHESIS][0]
    assert synth.payload["trust_level"] == "doc_input"
    uris = {c["uri"] for c in synth.payload["citations"]}
    assert "limits.md" in uris
    kb.close()
    log.close()


def test_kb_unset_leaves_doc_analysis_alone() -> None:
    log = EventLog()

    def interp(system: str, prompt: str) -> str:
        return json.dumps({
            "objective": "analyse the docs", "task_class": "doc_analysis",
            "success_criteria": ["x"], "required_evidence": ["some evidence"],
            "assumptions": [], "ambiguity": [], "constraints": [], "risk_level": "low",
        })

    from app.orchestration.orchestrator import Orchestrator
    from app.services.build.fake import ScriptedBuilder
    from app.services.interpret.interpreter import Interpreter
    from app.services.plan.planner import Planner
    from app.services.policy.engine import PolicyEngine
    from app.services.verify.verifier_t0 import VerifierT0

    orch = Orchestrator(
        log, Interpreter(ScriptedLLM(interp)), Planner(ScriptedLLM(['{"steps": []}'])),
        ScriptedBuilder({}), VerifierT0(), PolicyEngine(),
    )
    r = orch.run("analyse", ".")
    # no KB -> falls through to the normal path (which will stall on an empty plan)
    assert not [e for e in log.read(r.task_id) if e.kind == EventKind.KB]
    log.close()


def test_kb_augments_the_research_pipeline() -> None:
    from app.services.agents.researcher import Researcher
    from app.services.egress.broker import EgressBroker
    from app.services.research.pipeline import ResearchPipeline

    kb = _seed_kb()

    def router(system: str, prompt: str) -> str:
        s = system.lower()
        if "sub-question" in s:
            return '{"sub_questions": ["what is the rate limit"]}'
        if "query planner" in s:
            return '{"urls": []}'   # no web; KB only
        if "extract factual claims" in s:
            return '{"claims": [{"text": "100 req/min free, 1000 paid", "supported": true}]}'
        if "directly contradict" in s:
            return '{"contradictions": []}'
        if "synthesize a research answer" in s:
            return '{"sections": [{"statement": "Rate limit: 100/min free.", "citation_ids": []}], "uncertainty": "library only."}'
        return "{}"

    llm = ScriptedLLM(router)
    broker = EgressBroker(allowlist=[], opener=lambda u, t: b"")
    pipe = ResearchPipeline(Researcher(llm, broker), llm, kb=kb)
    res = pipe.run("t", "what is the rate limit")

    assert res.answer.citations, "the KB chunk should appear as a citation"
    assert any("limits.md" in c["source"] for c in res.answer.citations)
    kb.close()
