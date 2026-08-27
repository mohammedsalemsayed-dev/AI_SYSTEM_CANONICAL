from pathlib import Path

class WorkspaceManager:
    def __init__(self, root:str):
        self.root=Path(root).resolve()

    def base(self, workspace_id:str)->Path:
        p=(self.root/workspace_id).resolve()
        p.mkdir(parents=True,exist_ok=True)
        if self.root not in p.parents and p != self.root:
            raise PermissionError("invalid workspace")
        return p

    def resolve(self, workspace_id:str, relative:str)->Path:
        base=self.base(workspace_id)
        target=(base/relative).resolve()
        if target != base and base not in target.parents:
            raise PermissionError("workspace escape denied")
        return target
