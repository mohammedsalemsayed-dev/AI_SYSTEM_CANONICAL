"""Acceptance (Unit): tool registry, capability-gated dispatch, adapters
(MILESTONE_S_PLAN.md §6)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.schemas.contracts import CapabilityGrant
from app.services.capability.registry import spec_for
from app.services.egress.broker import EgressBroker
from app.services.policy.engine import PolicyEngine
from app.services.repo.git_adapter import GitAdapter
from app.services.tools.adapters.egress_tool import EgressToolAdapter
from app.services.tools.adapters.engine_tool import EngineToolAdapter
from app.services.tools.adapters.fs_tool import FsToolAdapter
from app.services.tools.adapters.git_tool import GitToolAdapter
from app.services.tools.base import DispatchContext
from app.services.tools.dispatch import ToolDispatcher
from app.services.tools.registry import ToolRegistry


def _grant(token: str, root: str, *, net: list[str] | None = None) -> CapabilityGrant:
    return CapabilityGrant(task_id="t", step_id="s", token=token, scope_path=root,
                           operations=sorted(spec_for(token).operations),
                           network_allowlist=net or [])


@pytest.fixture
def repo(tmp_path: Path) -> str:
    d = tmp_path / "r"
    d.mkdir()
    (d / "a.py").write_text("x = 1\n", encoding="utf-8", newline="\n")
    for a in (["init", "-q"], ["add", "-A"],
              ["-c", "user.email=x@x", "-c", "user.name=x", "commit", "-q", "-m", "x"]):
        subprocess.run(["git", "-C", str(d), *a], check=True, capture_output=True)
    return str(d)


@pytest.fixture
def reg(repo: str) -> ToolRegistry:
    return (ToolRegistry()
            .register(GitToolAdapter(GitAdapter(repo)))
            .register(FsToolAdapter())
            .register(EngineToolAdapter())
            .register(EgressToolAdapter(EgressBroker(allowlist=["ok.example"],
                                                    opener=lambda u, t: b"hello"))))


# --- registry --------------------------------------------------- #
def test_registry_find_and_manifest_block(reg: ToolRegistry) -> None:
    assert reg.get("git") is not None
    found = reg.find("git.status")
    assert found and found[1].capability == "vcs.read"
    block = reg.manifest_block()
    for op in ("git.status", "fs.read", "fs.write", "engine.info", "net.fetch"):
        assert op in block
    assert "[vcs.read]" in block and "(side-effecting)" in block
    assert reg.find("git.nope") is None


# --- dispatch through the policy engine -------------------- #
def test_allowed_op_returns_manifest_trust(reg: ToolRegistry, repo: str) -> None:
    d = ToolDispatcher(reg, PolicyEngine())
    res, dec = d.run("git.status", {}, DispatchContext(task_id="t", grant=_grant("vcs.read", repo),
                                                       workspace=repo))
    assert res.ok and res.trust == "workspace" and dec.decision == "ALLOW"
    assert "branch" in res.output


def test_missing_grant_is_a_policy_decision_not_an_exception(reg: ToolRegistry, repo: str) -> None:
    d = ToolDispatcher(reg, PolicyEngine())
    # a vcs.read grant cannot authorise vcs.commit
    res, dec = d.run("git.commit", {"message": "x"},
                     DispatchContext(task_id="t", grant=_grant("vcs.read", repo), workspace=repo))
    assert not res.ok and dec.decision == "DENY" and "not" in res.error.lower()

    res2, dec2 = d.run("git.status", {}, DispatchContext(task_id="t", grant=None, workspace=repo))
    assert not res2.ok and dec2.decision == "DENY"


def test_tainted_arg_on_side_effecting_op_is_denied(reg: ToolRegistry, repo: str) -> None:
    d = ToolDispatcher(reg, PolicyEngine())
    ctx = DispatchContext(task_id="t", grant=_grant("net.fetch", repo, net=["ok.example"]), workspace=repo,
                          trust="retrieved_web", taint_sources=["ev1"])
    res, dec = d.run("net.fetch", {"url": "http://ok.example"}, ctx)
    assert not res.ok and dec.decision == "DENY" and "taint" in dec.rule


def test_unknown_op_and_adapter_error(reg: ToolRegistry, repo: str) -> None:
    d = ToolDispatcher(reg, PolicyEngine())
    res, dec = d.run("git.nope", {}, DispatchContext(task_id="t", grant=_grant("vcs.read", repo)))
    assert not res.ok and res.error == "unknown tool op" and dec is None
    # a bad ref inside invoke -> ToolResult(ok=False), not a raise
    res2, _ = d.run("git.diff", {"a": "no-such-ref"},
                    DispatchContext(task_id="t", grant=_grant("vcs.read", repo), workspace=repo))
    assert not res2.ok and res2.error


# --- adapters ------------------------------------------- #
def test_fs_adapter_scope_and_write(reg: ToolRegistry, repo: str) -> None:
    d = ToolDispatcher(reg, PolicyEngine())
    g = _grant("fs.write", repo)
    ctx = DispatchContext(task_id="t", grant=g, workspace=repo)
    assert d.run("fs.read", {"path": "a.py"}, ctx)[0].output == "x = 1\n"
    assert not d.run("fs.read", {"path": "../../../etc/hosts"}, ctx)[0].ok
    w = d.run("fs.write", {"path": "sub/new.txt", "text": "hi"}, ctx)[0]
    assert w.ok and (Path(repo) / "sub" / "new.txt").read_text() == "hi"


def test_egress_adapter_denied_url_surfaces_as_result(reg: ToolRegistry, repo: str) -> None:
    d = ToolDispatcher(reg, PolicyEngine())
    ctx = DispatchContext(task_id="t", grant=_grant("net.fetch", repo, net=["ok.example"]), workspace=repo)
    ok = d.run("net.fetch", {"url": "http://ok.example"}, ctx)[0]
    assert ok.ok and ok.trust == "retrieved_web" and ok.output["text"] == "hello"

    # policy blocks an off-grant host before the broker
    pol = d.run("net.fetch", {"url": "http://evil.example"}, ctx)[0]
    assert not pol.ok and "egress-not-allowed" in pol.error

    # grant allows the host but the BROKER does not -> the broker's EgressDenied
    # surfaces as a ToolResult(ok=False), not an exception
    wide = DispatchContext(task_id="t", workspace=repo,
                           grant=_grant("net.fetch", repo, net=["evil.example", "ok.example"]))
    broker_denied = d.run("net.fetch", {"url": "http://evil.example"}, wide)[0]
    assert not broker_denied.ok and "denied" in broker_denied.error.lower()
