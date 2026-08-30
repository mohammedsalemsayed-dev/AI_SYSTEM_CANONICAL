from dataclasses import dataclass,field
from datetime import datetime,timezone

def now(): return datetime.now(timezone.utc)

@dataclass
class ProgressTracker:
    sequence:int=0
    last_progress_at:datetime=field(default_factory=now)
    events:list[dict]=field(default_factory=list)

    def advance(self, evidence:dict):
        meaningful=any([
            evidence.get("artifact_delta"), evidence.get("test_delta"),
            evidence.get("objective_delta"), evidence.get("new_evidence"),
            evidence.get("strategy_change"), evidence.get("blocker_removed")
        ])
        if not meaningful:
            return False
        self.sequence+=1
        self.last_progress_at=now()
        self.events.append(evidence)
        return True

    def repeated_failure_risk(self, signatures:list[str])->bool:
        return len(signatures)>=3 and len(set(signatures[-3:]))==1
