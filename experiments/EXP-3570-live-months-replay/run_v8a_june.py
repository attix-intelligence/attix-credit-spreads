#!/usr/bin/env python3
"""EXP-3570 step 3 — V8A June-2026 counterfactual on real marks.

Canonical V8A (configs/paper_expv8a.yaml, real engine, offline options DB,
leg-collision guard ON, post-8f1bc8c real-VIX production path) replayed on
2026-06-01 -> 2026-07-03 with fresh $100k, using the EXP-3570-backfilled
marks. Direct comparison target: live V8A paper lost heavily in June 2026
(the episode that triggered EXP-3310..3550).

Usage: run_v8a_june.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)

from utils import load_config  # noqa: E402
from backtest.backtester import Backtester  # noqa: E402
from backtest.historical_data import HistoricalOptionsData  # noqa: E402

CONFIG_PATH = str(ROOT / "configs" / "paper_expv8a.yaml")
ENV_FILE = str(ROOT / ".env.expv8a")
START = datetime(2026, 6, 1)
END = datetime(2026, 7, 3)


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    logging.getLogger("backtest.backtester").propagate = False

    config = load_config(CONFIG_PATH, env_file=ENV_FILE)
    hist = HistoricalOptionsData(os.environ.get("POLYGON_API_KEY", "dummy"), offline_mode=True)
    bt = Backtester(config=config, historical_data=hist,
                    otm_pct=float(config["strategy"].get("otm_pct", 0.02)))
    results = bt.run_backtest(ticker="SPY", start_date=START, end_date=END)
    hist.close()
    if not results:
        print("ERROR: empty results", file=sys.stderr)
        sys.exit(1)

    vix_keys = sorted(bt._vix_by_date.keys())
    summary = {
        "experiment": "EXP-3570", "leg": "v8a_june",
        "generated": datetime.utcnow().isoformat(),
        "window": [START.date().isoformat(), END.date().isoformat()],
        "metrics": {k: results.get(k) for k in
                    ("total_trades", "return_pct", "sharpe_ratio", "max_drawdown",
                     "win_rate", "total_pnl", "ending_capital",
                     "bull_put_trades", "bear_call_trades", "iron_condor_trades")},
        "vix_series_end": str(vix_keys[-1].date()) if vix_keys else None,
        "exit_reasons": {},
        "equity_curve": [(d.isoformat() if hasattr(d, "isoformat") else str(d), float(v))
                          for d, v in bt.equity_curve],
        "trades": results.get("trades", []),
    }
    for t in results.get("trades", []):
        r = str(t.get("exit_reason", "?"))
        summary["exit_reasons"][r] = summary["exit_reasons"].get(r, 0) + 1

    out = OUT / "v8a_june.json"
    out.write_text(json.dumps(summary, indent=2, default=str))
    m = summary["metrics"]
    print(f"[v8a_june] trades={m['total_trades']} return={m['return_pct']}% "
          f"maxDD={m['max_drawdown']}% exits={summary['exit_reasons']}")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
