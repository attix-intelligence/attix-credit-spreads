#!/usr/bin/env python3
"""V8A flush — CLOSE step (~09:33 ET). Thin wrapper over scripts/v8a_flush.py::cmd_close.

Cancels working orders, then closes EVERY open option vertical via an atomic
close_spread() at a marketable limit. DRY-RUN unless FLUSH_LIVE=1. Idempotent.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from v8a_flush import cmd_close  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(cmd_close())
