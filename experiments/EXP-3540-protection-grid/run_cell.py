#!/usr/bin/env python3
"""EXP-3540 — protection-grid cell runner (one ticker x one cell per process).

Re-scoped per EXP-3510/3520: June 2026 was a routine -4% dip amplified by
leverage (VIX max 22.2), so the grid prioritizes equity-DD de-risking, event
gates, and sizing — the VIX-exit axis is demoted to one reference cell.

Base strategy = live VRP stream params as in EXP-3520 (0.20-delta short, $5
width, ~30 DTE, bull_put only, vix_max_entry 40), exits = hold-to-expiry
(EXP-3520 showed PR-H PT/SL exits hurt), real VIX from the EXP-3510 backfill,
offline real Polygon marks.

Axes (cell id = S{risk}_D{tiers}_E{gate}[_V{vix}]):
  S — flat risk % of CURRENT equity per trade (compound):
        s215 = 21.5 (live-like: Alpaca 0.86x aggregate / 4 streams)
        s100 = 10.0 (halved)
  D — equity-DD tiers w/ TRUE flatten (per-ticker equity proxy for the book):
        doff  = no tiers
        d81012 = deployed EXP-800 tiers: halve @-8%, floor(min 2%) @-10%,
                 FLATTEN open + halt 30 trading days @-12%
        d479   = tight EXP-305-study tiers: halve @-4%, floor @-7%, flatten @-9%
  E — event entry gate (block entries the trading day BEFORE the event,
      same rule as EXP-3311 / shared/entry_gate.py):
        eoff / enfp (NFP via compass.events._nfp_release_date)
        enf (NFP + FOMC via compass.events.ALL_FOMC_DATES)
  V — demoted VIX reference: v30 = vix_close_all 30 (one cell only)

Tier semantics (documented interpretation of paper_exp800.yaml:97-104):
  - tiers evaluated daily vs rolling HWM of (capital + open MTM), causal
    (yesterday's marks);
  - flatten closes every open position at today's real marks (engine exit
    slippage applied); if no marks exist that day the carried mark is used;
  - after a flatten, entries halt for 30 trading days; on resume, sizing
    floor (min_fraction 2%) applies while DD remains below tier2; a further
    flatten triggers only on a NEW DD low (>=1pp below the last flatten) —
    without this, a realized tier-3 loss keeps DD pinned below the threshold
    forever and every re-entry is flattened the next day (thrash observed in
    the first smoke run: 47 flatten cycles). Live EXP-800 never faced this
    because it never actually flattened;
  - HWM is never reset (honest peak-to-trough accounting).

Usage: run_cell.py <ticker> <cell_id>   e.g. run_cell.py SPY s215_d81012_enfp
"""
from __future__ import annotations

import copy
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
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
from compass.events import ALL_FOMC_DATES, _nfp_release_date  # noqa: E402

CONFIG_PATH = str(ROOT / "configs" / "paper_expv8a.yaml")
ENV_FILE = str(ROOT / ".env.expv8a")
START = datetime(2020, 1, 2)
END = datetime(2026, 4, 1)
NEVER = 1_000_000.0
MIN_FRACTION_PCT = 2.0        # tier-2 sizing floor, % of equity (paper_exp800.yaml)
HALT_TRADING_DAYS = 30        # tier-3 halt (30 trade slots ~= 30 trading days here)

SIZINGS = {"s215": 21.5, "s100": 10.0}
TIERS = {
    "doff": None,
    "d81012": {"t1": -0.08, "t2": -0.10, "t3": -0.12},
    "d479":  {"t1": -0.04, "t2": -0.07, "t3": -0.09},
}
GATES = {"eoff": set(), "enfp": {"nfp"}, "enf": {"nfp", "fomc"}}

COMMON_STRATEGY = dict(
    direction="bull_put", use_delta_selection=True, target_delta=0.20,
    spread_width=5, spread_width_high_iv=5, spread_width_low_iv=5,
    target_dte=30, min_dte=25, max_dte=50,
    regime_mode="off", momentum_filter_pct=None, min_credit_pct=0.1,
    vix_max_entry=40.0,
)


def build_event_dates() -> dict:
    nfp = [_nfp_release_date(y, m) for y in range(2020, 2027) for m in range(1, 13)]
    return {"nfp": {d for d in nfp}, "fomc": set(ALL_FOMC_DATES)}


class DDTierOverlay:
    """EXP-800-style 3-tier equity-DD breaker with TRUE flatten, wrapped around
    Backtester._manage_positions. Also owns the entry-block flag."""

    def __init__(self, bt: Backtester, tiers: dict | None):
        self.bt = bt
        self.tiers = tiers
        self.hwm = bt.starting_capital
        self.halt_left = 0
        self.last_flatten_dd = None   # re-flatten only on a NEW low (anti-thrash)
        self.mult = 1.0
        self.block_entries = False
        self.events = []          # breaker action log
        self.flat_risk_pct = float(bt.risk_params.get("max_risk_per_trade", 2.0))
        self.min_mult = MIN_FRACTION_PCT / self.flat_risk_pct
        self._orig = bt._manage_positions
        bt._manage_positions = self._wrapped

    def _flatten(self, positions, current_date):
        date_str = current_date.strftime("%Y-%m-%d")
        for pos in list(positions):
            prices = None
            if pos.get("type") != "iron_condor":
                prices = self.bt.historical_data.get_spread_prices(
                    pos["ticker"], pos["expiration"],
                    pos["short_strike"], pos["long_strike"],
                    pos.get("option_type", "P"), date_str,
                )
            if prices is not None:
                exit_cost = prices["spread_value"] + self.bt._vix_scaled_exit_slippage()
                pnl = (pos["credit"] - exit_cost) * pos["contracts"] * 100 - pos["commission"]
                reason = "dd_flatten"
            else:
                slip = self.bt._vix_scaled_exit_slippage() * pos["contracts"] * 100
                pnl = pos.get("current_value", 0) - slip - pos["commission"]
                reason = "dd_flatten_marked"
            self.bt._record_close(pos, current_date, pnl, reason)
        return []

    def _wrapped(self, positions, current_date, current_price, ticker=""):
        equity = self.bt.capital + sum(p.get("current_value", 0) for p in positions)
        self.hwm = max(self.hwm, equity)
        dd = equity / self.hwm - 1.0

        if self.tiers is None:
            self.mult, self.block_entries = 1.0, False
        elif self.halt_left > 0:
            self.halt_left -= 1
            self.mult, self.block_entries = 0.0, True
        elif dd <= self.tiers["t3"]:
            new_low = self.last_flatten_dd is None or dd <= self.last_flatten_dd - 0.01
            if positions and new_low:
                self.events.append({"date": str(current_date.date()), "dd_pct": round(dd * 100, 2),
                                    "action": f"tier3_flatten_{len(positions)}pos_halt{HALT_TRADING_DAYS}"})
                positions = self._flatten(positions, current_date)
                self.halt_left = HALT_TRADING_DAYS
                self.last_flatten_dd = dd
                self.mult, self.block_entries = 0.0, True
            else:
                # realized loss keeps dd below t3; without a NEW low this is a
                # sizing-floor regime, not a re-flatten (anti-thrash — see docstring)
                self.mult, self.block_entries = self.min_mult, False
        elif dd <= self.tiers["t2"]:
            self.mult, self.block_entries = self.min_mult, False
        elif dd <= self.tiers["t1"]:
            self.mult, self.block_entries = 0.5, False
        else:
            self.mult, self.block_entries = 1.0, False

        self.bt._current_seasonal_mult = self.mult if self.mult > 0 else 1.0
        return self._orig(positions, current_date, current_price, ticker)


def main() -> None:
    ticker, cell = sys.argv[1], sys.argv[2]
    parts = cell.split("_")
    s_key, d_key, e_key = parts[0], parts[1], parts[2]
    vix_close = 30.0 if (len(parts) > 3 and parts[3] == "v30") else 0

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    logging.getLogger("backtest.backtester").setLevel(logging.INFO)
    logging.getLogger("backtest.backtester").propagate = False

    config = copy.deepcopy(load_config(CONFIG_PATH, env_file=ENV_FILE))
    strat = config["strategy"]
    strat.update(COMMON_STRATEGY)
    strat["vix_close_all"] = vix_close
    strat.setdefault("iron_condor", {})["enabled"] = False
    strat.setdefault("technical", {})["use_trend_filter"] = False

    risk = config["risk"]
    risk["profit_target"] = NEVER                 # hold-to-expiry base (EXP-3520)
    risk["stop_loss_multiplier"] = NEVER
    risk.pop("stop_loss_pct_of_width", None)
    risk["max_positions"] = 1
    risk["vix_max_entry"] = 40.0
    risk["max_risk_per_trade"] = SIZINGS[s_key]   # flat % of current equity
    risk["max_contracts"] = 300                   # live vrp cap (ibkr config)

    config["backtest"]["sizing_mode"] = "flat"    # read from backtest block, not risk
    config["backtest"]["compound"] = True         # live sizes off current NAV

    hist = HistoricalOptionsData(os.environ.get("POLYGON_API_KEY", "dummy"), offline_mode=True)
    bt = Backtester(config=config, historical_data=hist, otm_pct=float(strat.get("otm_pct", 0.02)))
    bt._compute_trend_ma = lambda closes: 0.0     # live VRP has no trend gate

    overlay = DDTierOverlay(bt, TIERS[d_key])

    # Event entry gate: block entries the trading day BEFORE an event (EXP-3311 rule).
    ev = build_event_dates()
    active = set()
    for k in GATES[e_key]:
        active |= ev[k]
    orig_find = bt._find_backtest_opportunity

    def gated_find(ticker_, date_, price_, price_data_, *a, **kw):
        if overlay.block_entries:
            return None
        if active:
            nxt = date_.date() + timedelta(days=1)
            for _ in range(4):                    # skip weekend/holiday to next event-relevant day
                if nxt in active:
                    return None
                if nxt.weekday() < 5:
                    break
                nxt += timedelta(days=1)
        return orig_find(ticker_, date_, price_, price_data_, *a, **kw)

    bt._find_backtest_opportunity = gated_find

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

    summary = {
        "experiment": "EXP-3540", "ticker": ticker, "cell": cell,
        "generated": datetime.utcnow().isoformat(),
        "window": [START.date().isoformat(), END.date().isoformat()],
        "params": {"flat_risk_pct": SIZINGS[s_key], "tiers": TIERS[d_key],
                    "event_gate": sorted(GATES[e_key]), "vix_close_all": vix_close,
                    "min_fraction_pct": MIN_FRACTION_PCT, "halt_days": HALT_TRADING_DAYS},
        "metrics": {k: results.get(k) for k in
                    ("total_trades", "return_pct", "sharpe_ratio", "max_drawdown",
                     "win_rate", "total_pnl", "ending_capital")},
        "exit_reasons": exit_reasons,
        "breaker_events": overlay.events,
        "ruin_triggered": bool(getattr(bt, "_ruin_triggered", False)),
        "equity_curve": equity,
    }
    out = OUT / f"{ticker}_{cell}.json"
    with open(out, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    m = summary["metrics"]
    print(f"[{ticker}/{cell}] trades={m['total_trades']} return={m['return_pct']}% "
          f"maxDD={m['max_drawdown']}% breaker_events={len(overlay.events)} "
          f"ruin={summary['ruin_triggered']} exits={exit_reasons}")


if __name__ == "__main__":
    main()
