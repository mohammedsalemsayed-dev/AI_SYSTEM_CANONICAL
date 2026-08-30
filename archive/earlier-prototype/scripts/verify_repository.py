from pathlib import Path
required=[
"README.md","docs/00_MASTER_SPEC.md","docs/architecture/END_TO_END_ARCHITECTURE.md",
"docs/contracts/CORE_CONTRACTS.md","docs/decision_history/ACTIVE_DECISIONS.md",
"docs/implementation/IMPLEMENTATION_PLAN.md","docs/testing/ACCEPTANCE.md",
"apps/backend/app/core/state.py","apps/backend/app/schemas/contracts.py",
"apps/backend/app/services/orchestration/orchestrator.py","apps/desktop/src/App.tsx"
]
missing=[x for x in required if not Path(x).exists()]
print("OK" if not missing else "MISSING: "+", ".join(missing))
raise SystemExit(bool(missing))
