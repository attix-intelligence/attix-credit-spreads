#!/usr/bin/env python3
"""V8A flush — FLIP-GUARD step (~09:40 ET). Thin wrapper over scripts/v8a_flush.py::cmd_flip_guard.

GO/HALT gate for the Champion->VRP cutover: requires flat + PR-E#78 merged + prod
healthy. Exit 0 = GO (chain the PR-E flip cmd next), exit 1 = HALT (do NOT flip; pages).
Does NOT itself apply dry_run:false — that toggle + V8A re-activation is PR-E's wiring.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from v8a_flush import cmd_flip_guard  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(cmd_flip_guard())
