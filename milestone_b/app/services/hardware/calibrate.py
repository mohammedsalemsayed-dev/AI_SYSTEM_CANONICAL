"""Calibration CLI (MILESTONE_R_PLAN.md §2).

    python -m app.services.hardware.calibrate                 # print the profile
    python -m app.services.hardware.calibrate --persist p.db  # + save to a MemoryStore
"""

from __future__ import annotations

import argparse
import json
import sys

from app.services.hardware.calibration import calibrate, persist


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="calibrate")
    ap.add_argument("--persist", metavar="MEMORY_DB", default=None,
                    help="sqlite path of a MemoryStore to save the profile into")
    ap.add_argument("--disk-path", default=".")
    args = ap.parse_args(argv)

    profile = calibrate(args.disk_path)
    print(json.dumps(profile.model_dump(), indent=2, default=str))

    if args.persist:
        from app.services.memory.store import MemoryStore

        mem = MemoryStore(args.persist)
        persist(profile, mem)
        mem.close()
        print(f"\npersisted to {args.persist}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
