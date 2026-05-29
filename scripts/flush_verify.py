#!/usr/bin/env python3
"""V8A flush — VERIFY step (~09:35 ET). Thin wrapper over scripts/v8a_flush.py::cmd_verify.

Asserts the account is FLAT (0 positions, 0 working orders). Exit 1 + page if not.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from v8a_flush import cmd_verify  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(cmd_verify())
