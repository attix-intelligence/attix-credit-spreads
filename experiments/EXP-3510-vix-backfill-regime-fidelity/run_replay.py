#!/usr/bin/env python3
"""EXP-3510 step 2 — canonical V8A replay with real VIX vs the silent fallback.

Two arms, run as SEPARATE processes (market_history caches frames per-process):

  fallback  — HEAD behavior as-is. The ^VIX hybrid load raises (no Polygon
              indices key), _build_iv_rank_series() swallows it, and the whole
              run trades on vix=20 / iv_rank=25 defaults. This reproduces the
              EXP-3310 NEW run conditions.
  realvix   — backtest.market_history._POLYGON_INDICES_START is monkeypatched
              past the backtest end, so ^VIX/^VIX3M/^GSPC are served entirely
              from data/historical_indices.sqlite, which EXP-3510 step 1
              backfilled with real Yahoo daily bars through 2026-07-01.
              No index network calls; SPY stock bars still come from Polygon
              (stocks key), identical to the canonical EXP-3310 methodology.

Everything else is byte-identical to scripts/exp3310_collision_rebacktest.py:
same config (configs/paper_expv8a.yaml), same ticker/range (SPY 2020-01-02 →
2025-12-31), offline options data, leg-collision guard ON.

Usage:
    .venv/bin/python experiments/EXP-3510-vix-backfill-regime-fidelity/run_replay.py fallback
    .venv/bin/python experiments/EXP-3510-vix-backfill-regime-fidelity/run_replay.py realvix
"""
from __future__ import annotations

import json
import logging
import os
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)

from utils import load_config  # noqa: E402

CONFIG_PATH = str(ROOT / "configs" / "paper_expv8a.yaml")
ENV_FILE = str(ROOT / ".env.expv8a")
TICKER = "SPY"
START = datetime(2020, 1, 2)
END = datetime(2025, 12, 31)
STALE_DAYS = 7  # a VIX print older than this feeding _prev_trading_val = stale fallback


class WarnCatcher(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.vix_warnings = []

    def emit(self, record):
        try:
            msg = record.getMessage()
        except Exception:
            return
        if "VIX" in msg or "IV rank" in msg or "iv_rank" in msg:
            self.vix_warnings.append(f"{record.levelname}: {msg}")


def main() -> None:
    label = sys.argv[1]
    assert label in ("fallback", "realvix"), "label must be fallback|realvix"

    if label == "realvix":
        import backtest.market_history as mh
        mh._POLYGON_INDICES_START = date(2027, 1, 1)
        mh._cached_load.cache_clear()
        print("[patch] indices boundary -> 2027-01-01 (sqlite-only, backfilled real data)")

    from backtest.backtester import Backtester  # noqa: E402  (import after patch is fine either way)
    from backtest.historical_data import HistoricalOptionsData  # noqa: E402

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    bt_logger = logging.getLogger("backtest.backtester")
    bt_logger.setLevel(logging.DEBUG)
    bt_logger.propagate = False
    catcher = WarnCatcher()
    bt_logger.addHandler(catcher)

    config = load_config(CONFIG_PATH, env_file=ENV_FILE)
    hist = HistoricalOptionsData(os.environ.get("POLYGON_API_KEY", "dummy"), offline_mode=True)
    bt = Backtester(config=config, historical_data=hist,
                    otm_pct=float(config["strategy"].get("otm_pct", 0.02)))
    results = bt.run_backtest(ticker=TICKER, start_date=START, end_date=END)
    hist.close()
    if not results:
        print("ERROR: empty results", file=sys.stderr)
        sys.exit(1)

    # ── Fidelity instrumentation: what VIX did the run actually see? ──────────
    import pandas as pd
    vix = bt._vix_by_date
    vix3m = bt._vix3m_by_date
    ivr = bt._iv_rank_by_date
    regime = getattr(bt, "_regime_by_date", {})

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
            v = vix[k]
            seen_vix.append(v)
            if (d - k).days > STALE_DAYS:
                stale += 1
            else:
                covered += 1

    regime_counts = Counter(str(v) for v in regime.values()) if regime else {}
    trades = results.get("trades", [])
    trade_types = Counter(t.get("type", "?") for t in trades)

    summary = {
        "experiment": "EXP-3510",
        "label": label,
        "generated": datetime.utcnow().isoformat(),
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
            "vix3m_series_len": len(vix3m),
            "iv_rank_series_len": len(ivr),
        },
        "regime_distribution": dict(regime_counts),
        "trade_type_distribution": dict(trade_types),
        "vix_log_lines": catcher.vix_warnings[:20],
        "trades": trades,
    }
    out = OUT / f"replay_{label}.json"
    with open(out, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    m = summary["metrics"]; vf = summary["vix_fidelity"]
    print(f"[{label}] trades={m['total_trades']} return={m['return_pct']}% "
          f"sharpe={m['sharpe_ratio']} maxDD={m['max_drawdown']}% | "
          f"fallback_days={vf['fallback_days_total']}/{vf['trading_days_in_window']} "
          f"vix_seen[{vf['vix_seen_min']:.1f}..{vf['vix_seen_max']:.1f}]")
    print(f"[{label}] wrote {out}")


if __name__ == "__main__":
    main()
