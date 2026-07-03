#!/usr/bin/env python3
"""EXP-3520 — As-deployed V8A exit-parity A/B (exits-off vs exits-on).

Question: how much of V8A's live-vs-backtest gap is explained by the missing
exit layer? Live V8A (2026-05-29 → June) ran with vrp_position_monitor
DISABLED in both deployments (configs/paper_expv8a.yaml:292,
configs/paper_expv8a_ibkr.yaml:259) — no profit target, no stop, no DTE roll,
no VIX-crisis exit. The backtests it was gated on assume managed exits.

Arms (identical entries, identical sizing, only the exit layer differs):
  exits_on  — PR-H as designed: PT 50% of credit, SL 2.0x credit,
              vix_close_all 45 (compass/live/vrp_position_monitor params).
              (roll_dte 7 is NOT reproducible — the backtester has no DTE-roll
              exit; documented limitation, exits at expiry instead.)
  exits_off — as deployed: hold to expiry. PT/SL set unreachably high,
              vix_close_all 0.

Strategy params = the ACTUAL live VRP stream params hardcoded in
compass/live/vrp_streams.py:143-150 (0.20-delta short via delta selection,
$5 width, target ~30 DTE in a [25,50] window, always bull_put,
vix_max_entry 40) — NOT the dead champion block in the YAML.

Approximations vs live (documented, identical across arms so the A/B holds):
  - flat 25%-of-capital risk per trade (engine cap), max_positions=1 per
    ticker run ≈ one spread per stream (live: LW risk-parity vol-target
    sizing, max_open_per_stream=1);
  - no 7-day re-entry cooldown (engine lacks it) → faster re-entry than live,
    mostly affecting exits_on (earlier closes → earlier re-entries);
  - no VIX-ladder soft sizing multiplier on entries (entry-side only anyway).

Real VIX is served from the EXP-3510-backfilled sqlite (boundary patch), so
vix_close_all / vix_max_entry / regime code see actual VIX. Options data:
offline data/options_cache.db real Polygon marks.

Usage: run_arms.py <ticker> <exits_on|exits_off>
  Tickers: SPY, XLF, XLI (daily bars → 2026-04-02); window 2020-01-02 → 2026-04-01.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)

# ── real VIX from backfilled sqlite (EXP-3510), no index network calls ───────
import backtest.market_history as mh  # noqa: E402
mh._POLYGON_INDICES_START = date(2027, 1, 1)
mh._cached_load.cache_clear()

from utils import load_config  # noqa: E402
from backtest.backtester import Backtester  # noqa: E402
from backtest.historical_data import HistoricalOptionsData  # noqa: E402

CONFIG_PATH = str(ROOT / "configs" / "paper_expv8a.yaml")
ENV_FILE = str(ROOT / ".env.expv8a")
START = datetime(2020, 1, 2)
END = datetime(2026, 4, 1)

NEVER = 1_000_000.0  # unreachable PT/SL → exit only at expiry

# Live VRP stream params (compass/live/vrp_streams.py:143-150) + PR-H exits
COMMON_STRATEGY = dict(
    direction="bull_put",            # all 4 live streams are bull_put
    use_delta_selection=True,
    target_delta=0.20,               # target_short_delta=0.20 (window 0.15-0.25)
    spread_width=5,                  # width=5.0
    spread_width_high_iv=5,
    spread_width_low_iv=5,
    target_dte=30,                   # target_dte=30 within dte_range [25,50]
    min_dte=25,
    max_dte=50,
    regime_mode="off",               # VRP streams have no regime direction logic
    momentum_filter_pct=None,        # no momentum filter live (None = gate off; 0 would block all red 10d windows)
    min_credit_pct=0.1,              # live has only the PR-#95 credit>0 check, no 15% floor
    vix_max_entry=40.0,              # hardcoded per-stream gate (vrp_streams.py:150)
)
ARMS = {
    "exits_on":  dict(profit_target=50, stop_loss_multiplier=2.0, vix_close_all=45.0),
    "exits_off": dict(profit_target=NEVER, stop_loss_multiplier=NEVER, vix_close_all=0),
}


def main() -> None:
    ticker, arm = sys.argv[1], sys.argv[2]
    assert arm in ARMS
    global START, END
    if len(sys.argv) > 4:  # optional smoke-test window override
        START = datetime.fromisoformat(sys.argv[3])
        END = datetime.fromisoformat(sys.argv[4])

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    logging.getLogger("backtest.backtester").setLevel(logging.INFO)
    logging.getLogger("backtest.backtester").propagate = False

    config = copy.deepcopy(load_config(CONFIG_PATH, env_file=ENV_FILE))
    strat = config["strategy"]
    strat.update(COMMON_STRATEGY)
    strat["vix_close_all"] = ARMS[arm]["vix_close_all"]
    strat.setdefault("iron_condor", {})["enabled"] = False   # live streams: spreads only
    strat.setdefault("technical", {})["use_trend_filter"] = False

    risk = config["risk"]
    risk["profit_target"] = ARMS[arm]["profit_target"]
    risk["stop_loss_multiplier"] = ARMS[arm]["stop_loss_multiplier"]
    risk.pop("stop_loss_pct_of_width", None)                 # PR-H has no width-stop
    risk["max_positions"] = 1                                # one spread per stream
    risk["vix_max_entry"] = 40.0
    risk["sizing_mode"] = "flat"
    risk["compound"] = False

    hist = HistoricalOptionsData(os.environ.get("POLYGON_API_KEY", "dummy"), offline_mode=True)
    bt = Backtester(config=config, historical_data=hist, otm_pct=float(strat.get("otm_pct", 0.02)))
    # Live VRP streams have NO trend gate (they emit bull puts whenever gates
    # pass). In non-combo mode the engine hard-blocks entries below the trend
    # MA (backtester.py: "price < trend_ma → return None"). Neutralize for
    # as-deployed parity — identical in both arms.
    bt._compute_trend_ma = lambda closes: 0.0
    results = bt.run_backtest(ticker=ticker, start_date=START, end_date=END)
    hist.close()
    if not results:
        print(f"ERROR: empty results for {ticker}/{arm}", file=sys.stderr)
        sys.exit(1)

    equity = [(d.isoformat() if hasattr(d, "isoformat") else str(d), float(v))
              for d, v in bt.equity_curve]
    exit_reasons = {}
    for t in results.get("trades", []):
        r = str(t.get("close_reason", t.get("exit_reason", "?")))
        exit_reasons[r] = exit_reasons.get(r, 0) + 1

    summary = {
        "experiment": "EXP-3520",
        "ticker": ticker,
        "arm": arm,
        "generated": datetime.utcnow().isoformat(),
        "window": [START.date().isoformat(), END.date().isoformat()],
        "arm_params": {**ARMS[arm]},
        "common_strategy_overrides": COMMON_STRATEGY,
        "metrics": {k: results.get(k) for k in
                    ("total_trades", "return_pct", "sharpe_ratio", "max_drawdown",
                     "win_rate", "total_pnl", "ending_capital")},
        "exit_reasons": exit_reasons,
        "equity_curve": equity,
        "trades": results.get("trades", []),
    }
    out = OUT / f"{ticker}_{arm}.json"
    with open(out, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    m = summary["metrics"]
    print(f"[{ticker}/{arm}] trades={m['total_trades']} return={m['return_pct']}% "
          f"sharpe={m['sharpe_ratio']} maxDD={m['max_drawdown']}% exits={exit_reasons}")


if __name__ == "__main__":
    main()
