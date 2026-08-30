from app.core.state import State,ALLOWED

class Orchestrator:
    def __init__(self, interpreter, planner, builder, verifier, policy, events):
        self.interpreter=interpreter; self.planner=planner; self.builder=builder
        self.verifier=verifier; self.policy=policy; self.events=events

    async def transition(self, task, target):
        current=State(task["state"])
        if target not in ALLOWED[current]: raise ValueError(f"invalid {current}->{target}")
        task["state"]=target.value
        await self.events.emit(task["id"],"STATE",{"state":target.value})

    async def run(self, task):
        await self.transition(task,State.INTERPRETING)
        contract=await self.interpreter.compile(task["request"])
        if contract.ambiguity:
            await self.transition(task,State.WAITING_FOR_USER)
            return {"state":task["state"],"questions":contract.ambiguity}
        await self.transition(task,State.PLANNING)
        plan=await self.planner.plan(contract)
        await self.transition(task,State.EXECUTING)
        result=await self.builder.execute(plan,contract)
        await self.transition(task,State.VERIFYING)
        verified=await self.verifier.verify(contract,result)
        await self.transition(task,State.COMPLETED if verified else State.FAILED)
        return {"state":task["state"],"result":result,"verified":verified}
