#!/usr/bin/env python3
"""EXP-3550 — continuous vol-target sizing cell runner (one ticker x cell).

Follow-up to EXP-3540, whose discrete DD tiers failed the rank-stability leg
(train/test top-5 disjoint: protection paid in 2020-2023 crashes, cost carry
in benign 2024-2026). Hypothesis: CONTINUOUS vol-targeted sizing adapts in
both regimes instead of binding only in one.

Sizing rule (causal, live-implementable):
  eff_risk_pct(t) = clamp( BASE_RISK * sigma_target / sigma(t-1), lo, hi )
  - BASE_RISK = 21.5% max-loss/NAV (live-like: Alpaca 0.86x / 4 streams),
    so at sigma == sigma_target the cell sizes exactly like live;
  - sigma = engine's _build_realized_vol_series: 20d ATR / close * sqrt(252),
    clipped [0.10, 1.00], read via _prev_trading_val (yesterday's close — no
    lookahead; engine fallback 0.25 during the ~20d warmup);
  - implemented via bt._current_seasonal_mult (multiplies trade_dollar_risk
    at both entry sizing paths; _seasonal_sizing is off so nothing overwrites).

Axes (cell id = vt{target}_{bounds}):
  target: annualized vol target 8 / 12 / 16 (%)
  bounds on eff_risk_pct:
    foff = safety-only [1%, 43%]  (43% = 2x live-like)
    fon  = [5%, 21.5%]            (never exceed live-like sizing)

Base strategy identical to EXP-3540: live VRP stream params (0.20-delta short
put, $5 width, ~30 DTE, bull_put, vix_max_entry 40), hold-to-expiry, real VIX
from EXP-3510 backfill, offline real Polygon marks, compounding flat sizing.
No DD tiers, no event gates (EXP-3540 showed gates are a no-op).

Usage: run_cell.py <ticker> <cell_id>   e.g. run_cell.py SPY vt12_fon
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

import backtest.market_history as mh  # noqa: E402
mh._POLYGON_INDICES_START = date(2027, 1, 1)   # real VIX from EXP-3510 sqlite backfill
mh._cached_load.cache_clear()

from utils import load_config  # noqa: E402
from backtest.backtester import Backtester  # noqa: E402
from backtest.historical_data import HistoricalOptionsData  # noqa: E402

CONFIG_PATH = str(ROOT / "configs" / "paper_expv8a.yaml")
ENV_FILE = str(ROOT / ".env.expv8a")
START = datetime(2020, 1, 2)
END = datetime(2026, 4, 1)
NEVER = 1_000_000.0
BASE_RISK = 21.5                    # live-like max-loss/NAV %, scaled by vol mult

TARGETS = {"vt08": 0.08, "vt12": 0.12, "vt16": 0.16}
BOUNDS = {"foff": (1.0, 43.0), "fon": (5.0, 21.5)}   # eff risk % bounds

COMMON_STRATEGY = dict(
    direction="bull_put", use_delta_selection=True, target_delta=0.20,
    spread_width=5, spread_width_high_iv=5, spread_width_low_iv=5,
    target_dte=30, min_dte=25, max_dte=50,
    regime_mode="off", momentum_filter_pct=None, min_credit_pct=0.1,
    vix_max_entry=40.0,
)


class VolTargetSizer:
    """Sets bt._current_seasonal_mult from the engine's causal realized-vol
    series before each entry search. eff_risk = BASE_RISK * target/sigma,
    clamped to [lo, hi]; mult = eff_risk / BASE_RISK."""

    def __init__(self, bt: Backtester, target: float, lo: float, hi: float):
        self.bt = bt
        self.target = target
        self.lo, self.hi = lo, hi
        self.daily = []               # (date, sigma, eff_risk_pct) audit trail
        self._last_key = None
        self._orig = bt._find_backtest_opportunity
        bt._find_backtest_opportunity = self._wrapped

    def _wrapped(self, ticker, date_, price, price_data, *a, **kw):
        sigma = float(self.bt._current_realized_vol or 0.25)
        eff = BASE_RISK * self.target / max(sigma, 1e-6)
        eff = min(max(eff, self.lo), self.hi)
        self.bt._current_seasonal_mult = eff / BASE_RISK
        key = date_.date().isoformat()
        if key != self._last_key:
            self.daily.append((key, round(sigma, 4), round(eff, 3)))
            self._last_key = key
        return self._orig(ticker, date_, price, price_data, *a, **kw)


def main() -> None:
    ticker, cell = sys.argv[1], sys.argv[2]
    t_key, b_key = cell.split("_")
    target, (lo, hi) = TARGETS[t_key], BOUNDS[b_key]

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    logging.getLogger("backtest.backtester").setLevel(logging.INFO)
    logging.getLogger("backtest.backtester").propagate = False

    config = copy.deepcopy(load_config(CONFIG_PATH, env_file=ENV_FILE))
    strat = config["strategy"]
    strat.update(COMMON_STRATEGY)
    strat["vix_close_all"] = 0
    strat.setdefault("iron_condor", {})["enabled"] = False
    strat.setdefault("technical", {})["use_trend_filter"] = False

    risk = config["risk"]
    risk["profit_target"] = NEVER                 # hold-to-expiry base (EXP-3520)
    risk["stop_loss_multiplier"] = NEVER
    risk.pop("stop_loss_pct_of_width", None)
    risk["max_positions"] = 1
    risk["vix_max_entry"] = 40.0
    risk["max_risk_per_trade"] = BASE_RISK
    risk["max_contracts"] = 300                   # live vrp cap (ibkr config)

    config["backtest"]["sizing_mode"] = "flat"
    config["backtest"]["compound"] = True         # live sizes off current NAV

    hist = HistoricalOptionsData(os.environ.get("POLYGON_API_KEY", "dummy"), offline_mode=True)
    bt = Backtester(config=config, historical_data=hist, otm_pct=float(strat.get("otm_pct", 0.02)))
    bt._compute_trend_ma = lambda closes: 0.0     # live VRP has no trend gate
    bt._seasonal_sizing = None                    # ensure nothing overwrites the mult

    sizer = VolTargetSizer(bt, target, lo, hi)

    results = bt.run_backtest(ticker=ticker, start_date=START, end_date=END)
    hist.close()
    if not results:
        print(f"ERROR: empty results {ticker}/{cell}", file=sys.stderr)
        sys.exit(1)

    equity = [(d.isoformat() if hasattr(d, "isoformat") else str(d), float(v))
              for d, v in bt.equity_curve]
    exit_reasons = {}
    for t in results.get("trades", []):
        r = str(t.get("exit_reason", "?"))
        exit_reasons[r] = exit_reasons.get(r, 0) + 1
    effs = [e for _, _, e in sizer.daily]

    summary = {
        "experiment": "EXP-3550", "ticker": ticker, "cell": cell,
        "generated": datetime.utcnow().isoformat(),
        "window": [START.date().isoformat(), END.date().isoformat()],
        "params": {"base_risk_pct": BASE_RISK, "vol_target": target,
                    "eff_risk_bounds_pct": [lo, hi], "vol_source": "engine ATR20 annualized, prev-day"},
        "metrics": {k: results.get(k) for k in
                    ("total_trades", "return_pct", "sharpe_ratio", "max_drawdown",
                     "win_rate", "total_pnl", "ending_capital")},
        "exit_reasons": exit_reasons,
        "eff_risk_pct_stats": {"min": min(effs), "max": max(effs),
                                "mean": round(sum(effs) / len(effs), 3)} if effs else None,
        "sizing_daily": sizer.daily,
        "ruin_triggered": bool(getattr(bt, "_ruin_triggered", False)),
        "equity_curve": equity,
    }
    out = OUT / f"{ticker}_{cell}.json"
    with open(out, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    m = summary["metrics"]
    print(f"[{ticker}/{cell}] trades={m['total_trades']} return={m['return_pct']}% "
          f"maxDD={m['max_drawdown']}% eff_risk={summary['eff_risk_pct_stats']} exits={exit_reasons}")


if __name__ == "__main__":
    main()
