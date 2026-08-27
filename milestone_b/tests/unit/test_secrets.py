"""Acceptance (Unit): SecretStore + env scrub (MILESTONE_C_PLAN.md section 7)."""

from __future__ import annotations

import pytest

from app.services.sandbox.docker_backend import DockerSandbox, _Cmd
from app.services.sandbox.runner import SandboxSpec
from app.services.sandbox.subprocess_backend import SubprocessSandbox
from app.services.secrets.store import SecretNotFound, SecretStore, scrub_env

_SRC = {
    "SLICE_SECRET_ANTHROPIC_API_KEY": "sk-live-abc123",
    "SLICE_SECRET_DB_PASSWORD": "hunter2",
    "PATH": "/usr/bin",
    "SLICE_LLM": "anthropic",
}


def test_store_reads_prefixed_vars_only() -> None:
    store = SecretStore(source=_SRC)
    assert store.names() == ["anthropic_api_key", "db_password"]
    assert store.has("DB_PASSWORD")
    assert store.get("anthropic_api_key") == "sk-live-abc123"
    assert store.values() == {"sk-live-abc123", "hunter2"}


def test_get_missing_raises() -> None:
    with pytest.raises(SecretNotFound):
        SecretStore(source=_SRC).get("nope")


def test_scrub_removes_secret_shaped_keys() -> None:
    store = SecretStore(source=_SRC)
    env = {"MY_API_KEY": "x", "AUTH_TOKEN": "y", "DB_PASSWORD": "z", "SAFE": "ok"}
    out = scrub_env(env, store)
    assert out == {"SAFE": "ok"}


def test_scrub_removes_entries_matching_a_stored_value() -> None:
    store = SecretStore(source=_SRC)
    env = {"INNOCENT_LOOKING": "hunter2", "OTHER": "fine"}
    out = scrub_env(env, store)
    assert out == {"OTHER": "fine"}


def test_docker_build_args_never_carry_a_secret() -> None:
    store = SecretStore(source=_SRC)
    box = DockerSandbox(
        cmd_runner=lambda a, t: _Cmd(0), secret_store=store
    )
    argv = box.build_args(
        SandboxSpec(
            workdir="/w",
            command=["python"],
            env={"TASK_TOKEN": "sk-live-abc123", "GREETING": "hi", "PW": "hunter2"},
        )
    )
    joined = " ".join(argv)
    assert "sk-live-abc123" not in joined
    assert "hunter2" not in joined
    assert "--env GREETING=hi" in joined


def test_subprocess_child_cannot_see_a_scrubbed_secret() -> None:
    store = SecretStore(source={"SLICE_SECRET_X": "topsecret"})
    box = SubprocessSandbox(secret_store=store)
    res = box.run(
        SandboxSpec(
            workdir=".",
            command=[
                "python",
                "-c",
                "import os;print(os.environ.get('CFG','MISSING'))",
            ],
            env={"CFG": "topsecret"},
        )
    )
    assert res.stdout.strip() == "MISSING"
