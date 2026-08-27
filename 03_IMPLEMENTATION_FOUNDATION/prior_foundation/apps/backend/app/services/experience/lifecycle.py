from enum import StrEnum
class ExperienceState(StrEnum):
    OBSERVED="OBSERVED"; CANDIDATE="CANDIDATE"; VALIDATED="VALIDATED"
    PROMOTED="PROMOTED"; MONITORED="MONITORED"; STALE="STALE"; QUARANTINED="QUARANTINED"

ALLOWED={
ExperienceState.OBSERVED:{ExperienceState.CANDIDATE,ExperienceState.QUARANTINED},
ExperienceState.CANDIDATE:{ExperienceState.VALIDATED,ExperienceState.QUARANTINED},
ExperienceState.VALIDATED:{ExperienceState.PROMOTED,ExperienceState.QUARANTINED},
ExperienceState.PROMOTED:{ExperienceState.MONITORED,ExperienceState.STALE,ExperienceState.QUARANTINED},
ExperienceState.MONITORED:{ExperienceState.STALE,ExperienceState.QUARANTINED},
ExperienceState.STALE:set(),ExperienceState.QUARANTINED:set()
}
