from pydantic import BaseModel,Field
from typing import Any,Literal

class TaskContract(BaseModel):
    task_id:str
    original_request:str
    objective:str
    deliverables:list[str]=[]
    constraints:list[str]=[]
    workspace_id:str
    risk_level:Literal["low","medium","high"]="low"
    assumptions:list[str]=[]
    ambiguity:list[str]=[]
    success_criteria:list[str]=[]
    required_evidence:list[str]=[]
    task_class:str="general"
    resource_sensitivity:str="normal"

class ActionProposal(BaseModel):
    action_id:str
    task_id:str
    operation:str
    arguments:dict[str,Any]=Field(default_factory=dict)
    required_capability:str
    workspace_scope:str
    expected_effect:str
    idempotency_key:str
    estimated_resource_cost:float=0
    rollback_or_recovery_hint:str|None=None

class AgentMessage(BaseModel):
    sender:str; role:str; task_id:str; intent:str
    claims:list[str]=[]; evidence_refs:list[str]=[]
    assumptions:list[str]=[]; requested_action:str|None=None
    confidence_summary:str|None=None
