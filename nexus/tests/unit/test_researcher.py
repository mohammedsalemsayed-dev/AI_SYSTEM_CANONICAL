"""Acceptance (Unit): Researcher — query plan -> egress fetch -> claims with
source refs; output is retrieved_web trust (MILESTONE_E_PLAN.md §7, §12)."""

from __future__ import annotations

import json

from app.llm.fake import ScriptedLLM
from app.services.agents.researcher import Researcher
from app.services.egress.broker import EgressBroker


def _broker(allow: list[str], calls: list[str]):
    def opener(url, timeout):
        calls.append(url)
        return b"The recommended fix is to guard against negative n."

    return EgressBroker(allowlist=allow, opener=opener)


def test_research_produces_evidence_and_claims_with_source_refs() -> None:
    calls: list[str] = []
    llm = ScriptedLLM([
        json.dumps({"urls": ["https://docs.example/guide"]}),
        json.dumps({"claims": [{"text": "guard against negative n", "supported": True},
                               {"text": "unrelated musing", "supported": False}]}),
    ])
    r = Researcher(llm, _broker(["docs.example"], calls))
    evidence, claims, run = r.research("t", "how to fix negative n")

    assert calls == ["https://docs.example/guide"]
    assert len(evidence) == 1 and evidence[0].trust_level == "retrieved_web"
    assert len(claims) == 1  # unsupported claim dropped
    assert claims[0].text == "guard against negative n"
    assert claims[0].source_refs == [evidence[0].id]
    assert claims[0].trust_level == "retrieved_web"
    assert run.role == "researcher"


def test_denied_egress_yields_no_evidence() -> None:
    calls: list[str] = []
    llm = ScriptedLLM([json.dumps({"urls": ["https://evil.example/x"]})])
    r = Researcher(llm, _broker(["docs.example"], calls))  # evil.example not allowed
    evidence, claims, run = r.research("t", "q")

    assert evidence == [] and claims == []
    assert calls == []  # broker never opened it
    assert run.failure_mode == "no_evidence"


def test_no_urls_planned_is_graceful() -> None:
    r = Researcher(ScriptedLLM([json.dumps({"urls": []})]), _broker(["x"], []))
    evidence, claims, _ = r.research("t", "q")
    assert evidence == [] and claims == []
