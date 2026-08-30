from pathlib import Path
def reconcile(checkpoint:dict)->dict:
    artifacts=[]
    for raw in checkpoint.get("artifacts",[]):
        p=Path(raw)
        artifacts.append({"path":raw,"exists":p.exists(),"size":p.stat().st_size if p.exists() else 0})
    uncertain=checkpoint.get("uncertain_external_actions",[])
    if uncertain: return {"decision":"REVIEW","artifacts":artifacts}
    if any(not x["exists"] for x in artifacts): return {"decision":"REPAIR","artifacts":artifacts}
    return {"decision":"VERIFY","artifacts":artifacts}
