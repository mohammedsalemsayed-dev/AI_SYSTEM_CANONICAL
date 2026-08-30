import pytest
from app.services.security.workspace import WorkspaceManager
from app.services.progress.service import ProgressTracker
from app.services.experience.lifecycle import ExperienceState,ALLOWED

def test_workspace_escape_denied(tmp_path):
    w=WorkspaceManager(str(tmp_path))
    with pytest.raises(PermissionError): w.resolve("a","../../escape")

def test_progress_needs_objective_evidence():
    p=ProgressTracker()
    assert not p.advance({"message":"still working"})
    assert p.advance({"test_delta":"2 failures -> 1 failure"})

def test_promoted_experience_can_be_monitored():
    assert ExperienceState.MONITORED in ALLOWED[ExperienceState.PROMOTED]
