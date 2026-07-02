#!/usr/bin/env python3
"""
EXP-3310 — Leg-collision guard re-backtest runner.

Runs the canonical V8A backtest (SPY, 2020-01-02 → 2025-12-31, config
configs/paper_expv8a.yaml) fully OFFLINE from data/options_cache.db, exactly as
the champion validation scripts do (direct Backtester + HistoricalOptionsData
with offline_mode=True). Captures the trade log and counts position_conflict
skips emitted by the leg-collision guard.

Usage:
    python scripts/exp3310_collision_rebacktest.py <label> <out_json>

  <label>   free-form tag written into the output ("new" / "old")
  <out_json> path to write results (metrics + trades + conflict counts)

The guard logs at DEBUG ("position_conflict — skipping <type> <key>"); we attach
a counting handler to the backtest.backtester logger to tally them by type.
"""
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from utils import load_config  # noqa: E402
from backtest.backtester import Backtester  # noqa: E402
from backtest.historical_data import HistoricalOptionsData  # noqa: E402

CONFIG_PATH = str(ROOT / "configs" / "paper_expv8a.yaml")
ENV_FILE = str(ROOT / ".env.expv8a")
TICKER = "SPY"
START = datetime(2020, 1, 2)
END = datetime(2025, 12, 31)


class ConflictCounter(logging.Handler):
    """Count position_conflict skips emitted by the leg-collision guard."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.total = 0
        self.by_type = {"bull_put": 0, "bear_call": 0, "IC": 0}

    def emit(self, record):
        try:
            msg = record.getMessage()
        except Exception:
            return
        if "position_conflict" in msg:
            self.total += 1
            if "bull_put" in msg:
                self.by_type["bull_put"] += 1
            elif "bear_call" in msg:
                self.by_type["bear_call"] += 1
            elif " IC " in msg or msg.rstrip().endswith("IC") or "skipping IC" in msg:
                self.by_type["IC"] += 1


def main():
    label = sys.argv[1] if len(sys.argv) > 1 else "run"
    out_json = sys.argv[2] if len(sys.argv) > 2 else str(ROOT / "output" / f"exp3310_{label}.json")

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    bt_logger = logging.getLogger("backtest.backtester")
    bt_logger.setLevel(logging.DEBUG)
    # Only our counter should see the (very verbose) DEBUG stream — don't flood stdout.
    bt_logger.propagate = False
    counter = ConflictCounter()
    bt_logger.addHandler(counter)

    # OLD (pre-fix) reproduction: neutralize the guard so the new `if _leg_collision`
    # branch is never taken and control falls through to the identical `elif` that WAS
    # the pre-fix code path. Provably equivalent to commit 2ad75fd^ for the scan loop,
    # while keeping the run otherwise byte-identical (same data, same enriched log).
    if os.environ.get("EXP3310_DISABLE_GUARD") == "1":
        import backtest.backtester as _btmod
        _btmod.position_leg_collision = lambda candidate, occupied_legs: False
        print("[guard] DISABLED (pre-fix reproduction)")

    config = load_config(CONFIG_PATH, env_file=ENV_FILE)

    # The backtester reads config['backtest'] directly; ensure the canonical
    # backtest block exists (paper_expv8a.yaml provides it).
    bt_cfg = config["backtest"]
    strat = config["strategy"]

    polygon_key = os.environ.get("POLYGON_API_KEY", "dummy")
    hist = HistoricalOptionsData(polygon_key, offline_mode=True)

    otm_pct = float(strat.get("otm_pct", 0.02))
    bt = Backtester(config=config, historical_data=hist, otm_pct=otm_pct)
    results = bt.run_backtest(ticker=TICKER, start_date=START, end_date=END)
    hist.close()

    if not results:
        print("ERROR: empty results", file=sys.stderr)
        sys.exit(1)

    summary = {
        "label": label,
        "config": CONFIG_PATH,
        "ticker": TICKER,
        "start": START.date().isoformat(),
        "end": END.date().isoformat(),
        "total_trades": results.get("total_trades"),
        "return_pct": results.get("return_pct"),
        "sharpe_ratio": results.get("sharpe_ratio"),
        "max_drawdown": results.get("max_drawdown"),
        "win_rate": results.get("win_rate"),
        "total_pnl": results.get("total_pnl"),
        "ending_capital": results.get("ending_capital"),
        "bull_put_trades": results.get("bull_put_trades"),
        "bear_call_trades": results.get("bear_call_trades"),
        "iron_condor_trades": results.get("iron_condor_trades"),
        "position_conflict_skips_total": counter.total,
        "position_conflict_skips_by_type": counter.by_type,
        "trades": results.get("trades", []),
    }

    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"[{label}] trades={summary['total_trades']} "
          f"return_pct={summary['return_pct']} sharpe={summary['sharpe_ratio']} "
          f"maxDD={summary['max_drawdown']} conflicts={counter.total} "
          f"({counter.by_type})")
    print(f"[{label}] wrote {out_json}")


if __name__ == "__main__":
    main()
