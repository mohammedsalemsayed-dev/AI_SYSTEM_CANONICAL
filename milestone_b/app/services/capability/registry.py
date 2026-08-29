"""Capability registry — the fixed map from a capability token to the concrete
operations it authorises (MILESTONE_C_PLAN.md section 2).

A `PlanStep.required_capability` names a token here; the Orchestrator turns it
into a scoped `CapabilityGrant` (see `issue.py`). The Policy Engine then checks
each `ActionProposal.operation` against the grant.

Kept as plain data, not a DSL (D18) — expand only on demonstrated need.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Every operation the system knows how to propose. The Policy Engine denies any
# operation not in a grant, so this list is also the ceiling.
FILE_READ = "file.read"
DIR_LIST = "dir.list"
FILE_WRITE = "file.write"
FILE_CREATE = "file.create"
FILE_DELETE = "file.delete"
SHELL_RUN = "shell.run"
NET_FETCH = "net.fetch"
SECRET_USE = "secret.use"
VCS_READ = "vcs.read"      # git status / log / blame / diff (Milestone J)
VCS_BRANCH = "vcs.branch"  # create a local branch
VCS_COMMIT = "vcs.commit"  # local commit — no push, ever

# Operations that change state outside the process. DESIGN_TIGHTENING.md 14.3:
# a tainted argument on any of these -> DENY.
SIDE_EFFECTING_OPS: frozenset[str] = frozenset(
    {FILE_WRITE, FILE_CREATE, FILE_DELETE, SHELL_RUN, NET_FETCH, SECRET_USE,
     VCS_BRANCH, VCS_COMMIT}
)


@dataclass(frozen=True)
class CapabilitySpec:
    token: str
    operations: frozenset[str]
    needs_network: bool = False
    needs_secret: bool = False
    notes: str = ""


_REGISTRY: dict[str, CapabilitySpec] = {
    spec.token: spec
    for spec in [
        CapabilitySpec("fs.read", frozenset({FILE_READ, DIR_LIST})),
        CapabilitySpec(
            "fs.write",
            frozenset({FILE_READ, DIR_LIST, FILE_WRITE, FILE_CREATE}),
            notes="no delete; that is a separate token if ever needed",
        ),
        CapabilitySpec("fs.delete", frozenset({FILE_READ, DIR_LIST, FILE_DELETE})),
        CapabilitySpec("shell.run", frozenset({SHELL_RUN}), notes="sandboxed only"),
        CapabilitySpec("net.fetch", frozenset({NET_FETCH}), needs_network=True),
        CapabilitySpec("secret.use", frozenset({SECRET_USE}), needs_secret=True),
        CapabilitySpec("vcs.read", frozenset({VCS_READ}), notes="git status/log/blame/diff"),
        CapabilitySpec(
            "vcs.write",
            frozenset({VCS_READ, VCS_BRANCH, VCS_COMMIT}),
            notes="local branch + local commit only; no remote subcommand exists",
        ),
    ]
}


_PRIMARY_OP: dict[str, str] = {
    "fs.read": FILE_READ,
    "fs.write": FILE_WRITE,
    "fs.delete": FILE_DELETE,
    "shell.run": SHELL_RUN,
    "net.fetch": NET_FETCH,
    "secret.use": SECRET_USE,
    "vcs.read": VCS_READ,
    "vcs.write": VCS_COMMIT,
}


def spec_for(token: str) -> CapabilitySpec | None:
    return _REGISTRY.get(token)


# Small models sometimes name a capability that does not exist ("git.diff",
# "read_file", "python.run"). Rather than fail the whole task, map the token to
# the nearest real one by keyword. A genuinely unknown token still resolves to
# the most conservative useful default (fs.read) — never straight to a
# side-effecting capability.
_NORMALIZE_HINTS: tuple[tuple[frozenset[str], str], ...] = (
    (frozenset({"diff", "status", "log", "blame", "git", "vcs", "history"}), "vcs.read"),
    (frozenset({"branch", "commit", "checkout"}), "vcs.write"),
    (frozenset({"delete", "remove", "rm", "unlink"}), "fs.delete"),
    (frozenset({"write", "edit", "create", "modify", "patch", "apply", "save"}), "fs.write"),
    (frozenset({"shell", "run", "exec", "cmd", "command", "bash", "pytest", "test", "python"}), "shell.run"),
    (frozenset({"net", "http", "https", "fetch", "url", "web", "download", "request"}), "net.fetch"),
    (frozenset({"secret", "token", "credential", "key"}), "secret.use"),
    (frozenset({"read", "list", "inspect", "view", "cat", "open", "scan", "ls"}), "fs.read"),
)


def normalize_token(token: str) -> str:
    """Return `token` if known, else the closest known token by keyword."""
    if token in _REGISTRY:
        return token
    low = (token or "").lower().replace("-", ".").replace("_", ".")
    parts = set(low.split(".")) | {low}
    for keywords, target in _NORMALIZE_HINTS:
        if parts & keywords:
            return target
    return "fs.read"


def primary_operation(token: str) -> str:
    """The representative operation a coarse step proposes under `token`."""
    return _PRIMARY_OP.get(token, token)


def known_tokens() -> list[str]:
    return sorted(_REGISTRY)


def is_side_effecting(operation: str) -> bool:
    return operation in SIDE_EFFECTING_OPS
