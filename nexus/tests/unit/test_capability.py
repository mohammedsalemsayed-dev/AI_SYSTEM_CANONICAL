"""Acceptance (Unit): capability registry, issuance, and grant scope math
(MILESTONE_C_PLAN.md section 7)."""

from __future__ import annotations

import time

import pytest

from app.schemas.contracts import CapabilityGrant, PlanStep
from app.services.capability.issue import CapabilityError, issue_grant
from app.services.capability.registry import (
    FILE_WRITE,
    SHELL_RUN,
    is_side_effecting,
    primary_operation,
    spec_for,
)


def _step(cap: str) -> PlanStep:
    return PlanStep(intent="x", expected_artifact_delta="y", required_capability=cap)


# --- registry ---------------------------------------------------------- #
def test_fs_write_grants_read_and_write_not_delete() -> None:
    ops = spec_for("fs.write").operations
    assert {"file.read", "file.write", "file.create", "dir.list"} <= ops
    assert "file.delete" not in ops


def test_unknown_token_has_no_spec() -> None:
    assert spec_for("fs.superuser") is None


def test_primary_operation_maps_tokens() -> None:
    assert primary_operation("fs.write") == FILE_WRITE
    assert primary_operation("shell.run") == SHELL_RUN
    assert primary_operation("mystery") == "mystery"


def test_side_effecting_set() -> None:
    assert is_side_effecting("file.write")
    assert is_side_effecting("net.fetch")
    assert not is_side_effecting("file.read")
    assert not is_side_effecting("dir.list")


# --- issuance -------------------------------------------------------- #
def test_issue_grant_from_known_token(tmp_path) -> None:
    grant = issue_grant("task_1", _step("fs.write"), workspace_root=str(tmp_path))
    assert grant.token == "fs.write"
    assert grant.scope_path == str(tmp_path)
    assert "file.write" in grant.operations
    assert grant.network_allowlist == []


def test_issue_grant_unknown_token_raises(tmp_path) -> None:
    with pytest.raises(CapabilityError):
        issue_grant("task_1", _step("fs.root"), workspace_root=str(tmp_path))


def test_net_fetch_grant_carries_allowlist(tmp_path) -> None:
    grant = issue_grant(
        "task_1",
        _step("net.fetch"),
        workspace_root=str(tmp_path),
        network_allowlist=["pypi.org"],
    )
    assert grant.allows_host("pypi.org")
    assert grant.allows_host("files.pypi.org")
    assert not grant.allows_host("evil.com")


# --- grant scope math --------------------------------------------- #
def test_covers_path_inside_scope(tmp_path) -> None:
    grant = CapabilityGrant(task_id="t", scope_path=str(tmp_path), operations=["file.write"])
    assert grant.covers_path(str(tmp_path / "src" / "a.py"))
    assert grant.covers_path("src/a.py")  # relative -> resolved under scope
    assert grant.covers_path(str(tmp_path))  # the root itself


def test_covers_path_rejects_traversal_and_siblings(tmp_path) -> None:
    scope = tmp_path / "repo"
    scope.mkdir()
    grant = CapabilityGrant(task_id="t", scope_path=str(scope), operations=["file.write"])
    assert not grant.covers_path("../escape.py")
    assert not grant.covers_path(str(tmp_path / "repo_evil" / "x.py"))
    assert not grant.covers_path(str(tmp_path / "other" / "x.py"))
    assert not grant.covers_path("C:/Windows/System32/drivers/etc/hosts")


def test_grant_expiry() -> None:
    grant = CapabilityGrant(
        task_id="t", scope_path="/w", operations=["file.read"], ttl_s=0.0
    )
    time.sleep(0.01)
    assert grant.is_expired()
    fresh = CapabilityGrant(
        task_id="t", scope_path="/w", operations=["file.read"], ttl_s=3600
    )
    assert not fresh.is_expired()


def test_allows_operation() -> None:
    grant = CapabilityGrant(
        task_id="t", scope_path="/w", operations=["file.read", "dir.list"]
    )
    assert grant.allows_operation("file.read")
    assert not grant.allows_operation("file.write")
