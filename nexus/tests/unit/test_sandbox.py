"""Acceptance (Unit): sandbox backend selection and the Docker CLI arg build
(MILESTONE_C_PLAN.md section 7). No Docker required — an injected command runner
verifies the flags."""

from __future__ import annotations

import pytest

from app.services.sandbox import SandboxUnavailable, select_runner
from app.services.sandbox.docker_backend import DockerSandbox, _Cmd
from app.services.sandbox.runner import SandboxRefused, SandboxSpec
from app.services.sandbox.subprocess_backend import SubprocessSandbox


def _fake_runner(exit_code=0, stdout="", stderr=""):
    calls: list[list[str]] = []

    def run(argv, timeout_s):
        calls.append(argv)
        return _Cmd(exit_code, stdout, stderr)

    run.calls = calls  # type: ignore[attr-defined]
    return run


# --- Docker arg construction ---------------------------------------- #
def test_build_args_has_isolation_flags() -> None:
    box = DockerSandbox(image="slice-sandbox:pytest", cmd_runner=_fake_runner())
    argv = box.build_args(
        SandboxSpec(workdir="/tmp/ws", command=["python", "-m", "pytest", "-q"])
    )
    joined = " ".join(argv)
    assert "--network none" in joined
    assert "--read-only" in joined
    assert "--tmpfs /tmp:rw,size=256m" in joined
    assert "--cap-drop ALL" in joined
    assert "--security-opt no-new-privileges" in joined
    assert "--pids-limit 512" in joined
    assert "--memory 2048m" in joined
    assert "dst=/work" in joined
    assert argv[-4:] == ["slice-sandbox:pytest", "python", "-m", "pytest"] or argv[-1] == "-q"


def test_build_args_network_toggle() -> None:
    box = DockerSandbox(cmd_runner=_fake_runner())
    argv = box.build_args(SandboxSpec(workdir="/w", command=["python"], network=True))
    assert "--network bridge" in " ".join(argv)


def test_build_args_passes_env() -> None:
    box = DockerSandbox(cmd_runner=_fake_runner())
    argv = box.build_args(
        SandboxSpec(workdir="/w", command=["python"], env={"FOO": "bar"})
    )
    assert "--env FOO=bar" in " ".join(argv)


def test_available_false_when_docker_missing() -> None:
    box = DockerSandbox(cmd_runner=_fake_runner(exit_code=127, stderr="not found"))
    assert box.available() is False


def test_available_true_when_docker_responds() -> None:
    box = DockerSandbox(cmd_runner=_fake_runner(exit_code=0, stdout="27.0.0"))
    assert box.available() is True


def test_run_maps_result() -> None:
    box = DockerSandbox(cmd_runner=_fake_runner(exit_code=1, stdout="F", stderr="e"))
    res = box.run(SandboxSpec(workdir="/w", command=["python", "-m", "pytest"]))
    assert res.exit_code == 1 and res.stdout == "F" and res.backend == "docker"
    assert not res.ok


# --- subprocess fallback ------------------------------------------ #
def test_subprocess_runs_python() -> None:
    box = SubprocessSandbox()
    res = box.run(SandboxSpec(workdir=".", command=["python", "-c", "print(2 + 2)"]))
    assert res.exit_code == 0 and res.stdout.strip() == "4"
    assert res.backend == "subprocess-fallback"


def test_subprocess_refuses_non_isolated_when_forbidden() -> None:
    box = SubprocessSandbox()
    with pytest.raises(SandboxRefused):
        box.run(
            SandboxSpec(
                workdir=".", command=["python", "-c", "pass"], allow_non_isolated=False
            )
        )


# --- selection --------------------------------------------------- #
def test_select_requires_isolation_raises_without_docker(monkeypatch) -> None:
    monkeypatch.setattr(DockerSandbox, "available", lambda self: False)
    with pytest.raises(SandboxUnavailable):
        select_runner(require_isolation=True)


def test_select_falls_back_when_isolation_not_required(monkeypatch) -> None:
    monkeypatch.setattr(DockerSandbox, "available", lambda self: False)
    runner = select_runner(require_isolation=False)
    assert runner.name == "subprocess-fallback"


def test_select_prefers_docker_when_available(monkeypatch) -> None:
    monkeypatch.setattr(DockerSandbox, "available", lambda self: True)
    runner = select_runner(require_isolation=True)
    assert runner.name == "docker"
