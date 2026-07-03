#!/usr/bin/env python3
"""EXP-3570 step 2 — replay the real EXP-800 live months (Apr-Jun 2026).

Drives the EXP-800-BT harness (experiments/EXP-800-BT-safe-kelly/run.py)
unmodified, but on the live-paper window: SPY 2026-04-01 -> 2026-07-03,
fresh $100k starting capital and fresh HWM — mirroring the live paper
account that (re)started end-March 2026. Uses the post-8f1bc8c production
indices path (real VIX through 2026-07-02) and the EXP-3570-backfilled
option marks. Offline engine; SPY stock bars via Polygon stocks key
(canonical EXP-3310 methodology).

Variants: haltonly (as-deployed live twin — headline), flatten, notiers.

Usage: run_livewindow.py <haltonly|flatten|notiers>
"""
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
HARNESS = ROOT / "experiments" / "EXP-800-BT-safe-kelly" / "run.py"
BASE_CFG = ROOT / "configs" / "backtest_exp800.json"
LOCAL_CFG = HERE / "backtest_exp800_livewindow.json"
WINDOW = {"start": "2026-04-01", "end": "2026-07-03"}


def main() -> None:
    variant = sys.argv[1] if len(sys.argv) > 1 else "haltonly"

    cfg = json.loads(BASE_CFG.read_text())
    assert cfg["backtest"]["starting_capital"] == 100000, "expected fresh $100k base"
    cfg["window"] = dict(WINDOW)
    cfg.setdefault("fidelity_notes", {})["exp3570"] = (
        "EXP-3570 live-months window override; everything else identical to "
        "configs/backtest_exp800.json (EXP-800-BT G21-parity config)."
    )
    LOCAL_CFG.write_text(json.dumps(cfg, indent=2))

    spec = importlib.util.spec_from_file_location("exp800bt_run", HARNESS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.CONFIG_PATH = LOCAL_CFG          # harness reads this in main()
    mod.OUT = HERE / "results"           # write result JSONs here

    sys.argv = [str(HARNESS), variant]
    mod.main()

    # month-by-month vs live paper track
    res = json.loads((HERE / "results" / f"SPY_{variant}.json").read_text())
    monthly = mod._monthly_returns(
        [(d, v) for d, v in res["equity_curve"]], ["2026-04", "2026-05", "2026-06", "2026-07"])
    res["live_months_monthly_pct"] = monthly
    res["live_paper_track_pct"] = {"2026-04": 21.2, "2026-05": 3.4, "2026-06": 11.3}
    (HERE / "results" / f"SPY_{variant}.json").write_text(json.dumps(res, indent=2, default=str))
    print(f"monthly backtest: {monthly}")
    print(f"monthly live    : {res['live_paper_track_pct']}")


if __name__ == "__main__":
    main()
