#!/usr/bin/env python3
"""EXP-3311b — validate the VIX-blind fix (commit 8f1bc8c) end-to-end.

Re-runs the canonical V8A replay through the FIXED PRODUCTION PATH with NO
monkeypatch: backtest/market_history._load_indices_hybrid should now fall
back to the SQLite indices DB (real VIX/VIX3M/SPX through 2026) when the
Polygon indices feed is unavailable (env has no key), instead of silently
returning {} and leaving the backtester on vix=20 / iv_rank=25 defaults.

Everything else is byte-identical to scripts/exp3310_collision_rebacktest.py
and EXP-3510's run_replay.py: configs/paper_expv8a.yaml, SPY 2020-01-02 →
2025-12-31, offline data/options_cache.db, leg-collision guard ON.

Validation target: EXP-3510 realvix arm (monkeypatched sqlite-only) —
~-8.9% total, Sharpe ~-0.06, MaxDD ~-31.8%, fallback days 0/1508,
VIX seen ~11.9-82.7. Match within rounding => fix validated.

Usage: .venv/bin/python experiments/EXP-3311b-vix-fix-validation/run_replay.py
"""
from __future__ import annotations

import json
import logging
import os
import sys
from collections import Counter
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
TICKER = "SPY"
START = datetime(2020, 1, 2)
END = datetime(2025, 12, 31)
STALE_DAYS = 7


class LogCatcher(logging.Handler):
    """Capture VIX-related backtester lines AND the new market_history
    'falling back to SQLite indices' warning that proves the fixed path ran."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.vix_warnings = []
        self.fallback_warnings = []

    def emit(self, record):
        try:
            msg = record.getMessage()
        except Exception:
            return
        if "falling back to SQLite indices" in msg:
            self.fallback_warnings.append(f"{record.levelname}: {msg}")
        elif "VIX" in msg or "IV rank" in msg or "iv_rank" in msg:
            self.vix_warnings.append(f"{record.levelname}: {msg}")


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    catcher = LogCatcher()
    bt_logger = logging.getLogger("backtest.backtester")
    bt_logger.setLevel(logging.DEBUG)
    bt_logger.propagate = False
    bt_logger.addHandler(catcher)
    mh_logger = logging.getLogger("backtest.market_history")
    mh_logger.setLevel(logging.DEBUG)
    mh_logger.addHandler(catcher)

    assert not os.environ.get("POLYGON_INDICES_API_KEY"), \
        "POLYGON_INDICES_API_KEY set — this validation requires the no-key path"

    config = load_config(CONFIG_PATH, env_file=ENV_FILE)
    hist = HistoricalOptionsData(os.environ.get("POLYGON_API_KEY", "dummy"), offline_mode=True)
    bt = Backtester(config=config, historical_data=hist,
                    otm_pct=float(config["strategy"].get("otm_pct", 0.02)))
    results = bt.run_backtest(ticker=TICKER, start_date=START, end_date=END)
    hist.close()
    if not results:
        print("ERROR: empty results", file=sys.stderr)
        sys.exit(1)

    # ── VIX fidelity: what did the run actually see? (same as EXP-3510) ──────
    import pandas as pd
    vix = bt._vix_by_date
    win_days = [d for d in bt._price_data.index
                if pd.Timestamp(START.date()) <= d <= pd.Timestamp(END.date())]
    vix_keys = sorted(vix.keys())

    covered = stale = default = 0
    seen_vix = []
    for d in win_days:
        prior = [k for k in vix_keys if k < d]
        if not prior:
            default += 1
            seen_vix.append(20.0)
        else:
            k = prior[-1]
            seen_vix.append(vix[k])
            if (d - k).days > STALE_DAYS:
                stale += 1
            else:
                covered += 1

    trades = results.get("trades", [])
    summary = {
        "experiment": "EXP-3311b",
        "label": "prodpath_nofix_patch",
        "generated": datetime.utcnow().isoformat(),
        "commit_under_test": "8f1bc8c",
        "config": CONFIG_PATH,
        "ticker": TICKER,
        "start": START.date().isoformat(),
        "end": END.date().isoformat(),
        "metrics": {k: results.get(k) for k in
                    ("total_trades", "return_pct", "sharpe_ratio", "max_drawdown",
                     "win_rate", "total_pnl", "ending_capital",
                     "bull_put_trades", "bear_call_trades", "iron_condor_trades")},
        "vix_fidelity": {
            "trading_days_in_window": len(win_days),
            "days_covered_fresh": covered,
            "days_stale_carryforward": stale,
            "days_default_20": default,
            "fallback_days_total": stale + default,
            "vix_series_len": len(vix_keys),
            "vix_series_range": [str(vix_keys[0].date()) if vix_keys else None,
                                  str(vix_keys[-1].date()) if vix_keys else None],
            "vix_seen_min": min(seen_vix), "vix_seen_max": max(seen_vix),
            "vix_seen_mean": sum(seen_vix) / len(seen_vix),
            "vix3m_series_len": len(bt._vix3m_by_date),
            "iv_rank_series_len": len(bt._iv_rank_by_date),
        },
        "sqlite_fallback_warnings": catcher.fallback_warnings,
        "trade_type_distribution": dict(Counter(t.get("type", "?") for t in trades)),
        "vix_log_lines": catcher.vix_warnings[:20],
        "trades": trades,
    }
    out = OUT / "replay_prodpath.json"
    with open(out, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    m = summary["metrics"]; vf = summary["vix_fidelity"]
    print(f"[prodpath] trades={m['total_trades']} return={m['return_pct']}% "
          f"sharpe={m['sharpe_ratio']} maxDD={m['max_drawdown']}% | "
          f"fallback_days={vf['fallback_days_total']}/{vf['trading_days_in_window']} "
          f"vix_seen[{vf['vix_seen_min']:.1f}..{vf['vix_seen_max']:.1f}] | "
          f"sqlite_fallback_warnings={len(catcher.fallback_warnings)}")
    print(f"[prodpath] wrote {out}")


if __name__ == "__main__":
    main()
