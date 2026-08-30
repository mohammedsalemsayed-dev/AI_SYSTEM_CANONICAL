def choose_route(task, candidates, hardware):
    # candidates: [{name,local,quality,latency,cost,privacy_score,resource_cost,available}]
    viable=[c for c in candidates if c.get("available")]
    if not viable: raise RuntimeError("no model route available")
    def score(c):
        return (
            4*c.get("quality",0)
            + 2*c.get("privacy_score",0)
            - 1.5*c.get("latency",0)
            - 2*c.get("cost",0)
            - 2*c.get("resource_cost",0)
            + (1 if c.get("local") and hardware.get("mode") in {"CONSERVATION","PROTECTIVE"} else 0)
        )
    return max(viable,key=score)
