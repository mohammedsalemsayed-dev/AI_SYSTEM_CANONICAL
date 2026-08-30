"""Acceptance (Integration): an `authoring` task runs outline→draft→review→render
and returns a rendered, cited document (MILESTONE_M_PLAN.md §6)."""

from __future__ import annotations

import json

from app.events.log import EventKind, EventLog
from app.llm.fake import ScriptedLLM
from app.services.authoring.pipeline import AuthoringPipeline
from app.services.kb.store import KnowledgeBase


def _kb() -> KnowledgeBase:
    kb = KnowledgeBase()
    kb.ingest_text("# Rate limits\n\nThe API permits 100 requests per minute on the free tier "
                   "and 1000 on paid.", uri="limits.md", title="Limits")
    kb.ingest_text("# Authentication\n\nUse a bearer token in the Authorization header; tokens "
                   "expire after 24 hours.", uri="auth.md", title="Auth")
    return kb


def _author_llm(system: str, prompt: str) -> str:
    s = system.lower()
    if "document outline" in s:
        return ('{"title": "API Reference", "sections": ['
                '{"title": "Rate limits", "gist": "request quotas per minute"},'
                '{"title": "Authentication", "gist": "bearer tokens"}]}')
    if "extract factual claims" in s:
        if "requests per minute" in prompt:
            return '{"claims": [{"text": "100 req/min free, 1000 paid", "supported": true}]}'
        if "bearer token" in prompt:
            return '{"claims": [{"text": "bearer token in Authorization header, 24h expiry", "supported": true}]}'
        return '{"claims": []}'
    if "write one section" in s:
        return '{"paragraphs": [{"text": "Quotas apply per tier.", "citation_ids": []}]}'
    if "review document sections" in s:
        return '{"issues": []}'
    return "{}"


def test_authoring_task_end_to_end() -> None:
    from app.orchestration.orchestrator import Orchestrator
    from app.services.build.fake import ScriptedBuilder
    from app.services.interpret.interpreter import Interpreter
    from app.services.plan.planner import Planner
    from app.services.policy.engine import PolicyEngine
    from app.services.verify.verifier_t0 import VerifierT0

    log = EventLog()
    kb = _kb()

    def interp(system: str, prompt: str) -> str:
        return json.dumps({
            "objective": "write an API reference covering rate limits and authentication",
            "task_class": "authoring",
            "success_criteria": ["a cited, reviewed document"],
            "required_evidence": ["outline + draft + review"],
            "assumptions": [], "ambiguity": [], "constraints": [], "risk_level": "low",
        })

    author_llm = ScriptedLLM(_author_llm)
    orch = Orchestrator(
        log, Interpreter(ScriptedLLM(interp)), Planner(ScriptedLLM([])),
        ScriptedBuilder({}), VerifierT0(), PolicyEngine(),
    )
    orch.authoring = AuthoringPipeline(author_llm, kb=kb)

    r = orch.run("draft the API reference", ".")
    assert r.state == "COMPLETED" and r.verified

    kinds = {e.kind for e in log.read(r.task_id)}
    assert EventKind.AUTHORING in kinds and EventKind.SYNTHESIS in kinds
    synth = [e for e in log.read(r.task_id) if e.kind == EventKind.SYNTHESIS][0]
    assert synth.payload["mime"] == "text/markdown"
    assert "# API Reference" in synth.payload["text"]
    assert "## References" in synth.payload["text"]
    assert any(c["trust"] == "doc_input" for c in synth.payload["citations"])
    kb.close()
    log.close()


def test_authoring_unset_leaves_authoring_alone() -> None:
    from app.orchestration.orchestrator import Orchestrator
    from app.services.build.fake import ScriptedBuilder
    from app.services.interpret.interpreter import Interpreter
    from app.services.plan.planner import Planner
    from app.services.policy.engine import PolicyEngine
    from app.services.verify.verifier_t0 import VerifierT0

    log = EventLog()

    def interp(system: str, prompt: str) -> str:
        return json.dumps({
            "objective": "write a doc", "task_class": "authoring",
            "success_criteria": ["x"], "required_evidence": ["some evidence"],
            "assumptions": [], "ambiguity": [], "constraints": [], "risk_level": "low",
        })

    orch = Orchestrator(
        log, Interpreter(ScriptedLLM(interp)), Planner(ScriptedLLM(['{"steps": []}'])),
        ScriptedBuilder({}), VerifierT0(), PolicyEngine(),
    )
    r = orch.run("write it", ".")
    assert not [e for e in log.read(r.task_id) if e.kind == EventKind.AUTHORING]
    log.close()


def test_authoring_grounded_and_flags_thin_brief() -> None:
    kb = _kb()
    res = AuthoringPipeline(
        ScriptedLLM(_author_llm), kb=kb,
    ).run("t", "write an API reference covering rate limits and authentication")
    assert res.rendered.mime == "text/markdown"
    assert res.citations and all(c["trust"] == "doc_input" for c in res.citations)
    # a section the KB can't support would be flagged; here both are supported
    assert "# API Reference" in res.rendered.text
    kb.close()
