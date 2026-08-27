from enum import StrEnum
class HardwareMode(StrEnum):
    NORMAL="NORMAL"; EFFICIENT="EFFICIENT"; CONSERVATION="CONSERVATION"
    PROTECTIVE="PROTECTIVE"; EMERGENCY="EMERGENCY"

def decide(snapshot:dict, progress_good:bool)->HardwareMode:
    temp=snapshot.get("gpu_temp_c")
    ram=snapshot.get("ram_percent",0)
    gpu=snapshot.get("gpu_percent",0)
    if temp is not None and temp>=90: return HardwareMode.EMERGENCY
    if temp is not None and temp>=85: return HardwareMode.PROTECTIVE
    if (temp is not None and temp>=80) or ram>=92 or (gpu>=95 and not progress_good):
        return HardwareMode.CONSERVATION
    if gpu>=75 or ram>=80: return HardwareMode.EFFICIENT
    return HardwareMode.NORMAL
