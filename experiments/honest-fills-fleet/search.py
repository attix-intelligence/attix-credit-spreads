#!/usr/bin/env python3
"""Bounded expectancy search (cc1 proposal Rev 3 step 3).

Pre-registered in reports/honest_fills_fleet/EXPECTANCY_SEARCH_PREREG.md
(committed b3cb9c4 BEFORE any run). V0 control + 12 variants, marketable
fills only, on the faithful EXP-1220 base (exp1220_faithful in run.py).

Usage:  .venv/bin/python experiments/honest-fills-fleet/search.py V2 search
        .venv/bin/python experiments/honest-fills-fleet/search.py V2 holdout
Windows: search  = 2020-01-02 .. 2024-12-31
         holdout = 2025-01-02 .. 2026-04-02  (run ONLY for search passers, once)
Offline only; never touches live/paper workers.
"""
from __future__ import annotations

import calendar
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
OUT = Path(__file__).resolve().parent / "results"

from run import assert_holdout_seal, BACKTEST_BLOCK, EXPERIMENTS, FidelityShims, _load_env, _per_year_returns  # noqa: E402

WINDOWS = {
    "search": ("2020-01-02", "2024-12-31"),
    "holdout": ("2025-01-02", "2026-04-02"),
}

BASE = EXPERIMENTS["exp1220_faithful"]


# ── NFP calendar (ported from run_twin.py — deterministic BLS reconstruction) ──
def _first_friday(year: int, month: int) -> date:
    for d in range(1, 8):
        dt = date(year, month, d)
        if dt.weekday() == 4:
            return dt
    raise RuntimeError("unreachable")


def _nfp_schedule_rule(year: int, month: int) -> date:
    d = _first_friday(year, month)
    if d.month == 1 and d.day == 1:
        return d + timedelta(days=7)
    if d.month == 7 and d.day in (3, 4):
        return d - timedelta(days=1)
    return d


def build_nfp_dates(start_year: int, end_year: int) -> set:
    dates, published = set(), set()
    try:
        from compass.orchestrator.calendars import nfp_dates as published_nfp
        for y in range(start_year, end_year + 1):
            try:
                dates.update(published_nfp(y))
                published.add(y)
            except Exception:
                pass
    except Exception:
        pass
    for y in range(start_year, end_year + 1):
        if y in published:
            continue
        for m in range(1, 13):
            dates.add(_nfp_schedule_rule(y, m))
    return dates


# ── search-specific gates (harness wrappers; engine code untouched) ──────────
class SearchGates:
    """Entry gates + month-anchored breaker per the pre-registration."""

    def __init__(self, bt, *, trend_gate=False, nfp_gate=False,
                 contango_gate=False, breaker=False):
        import pandas as pd
        self.pd = pd
        self.bt = bt
        self.trend_gate = trend_gate
        self.contango_gate = contango_gate
        self.nfp_dates = build_nfp_dates(2019, 2027) if nfp_gate else None
        self.counts = {"trend": 0, "nfp": 0, "contango": 0, "breaker_half_days": 0,
                       "breaker_halt_days": 0}
        # breaker state (V3/V12): month-anchored, per prereg + proposal §2
        self.breaker = breaker
        self.base_risk = float(bt.risk_params["max_risk_per_trade"])
        self.month = None
        self.month_start_nav = bt.starting_capital
        self.prev_month_start = bt.starting_capital
        self.mode = "full"          # full | half | halt
        self.entered_month_mode = "full"
        if breaker:
            self._orig_manage = bt._manage_positions
            bt._manage_positions = self._wrapped_manage
        for name in ("_find_backtest_opportunity", "_find_bear_call_opportunity",
                     "_find_iron_condor_opportunity"):
            setattr(bt, name, self._gate(getattr(bt, name)))

    # entry gate: args = (ticker, date, price, price_data, ...)
    def _gate(self, orig):
        def fn(*a, **kw):
            d = kw.get("date", a[1] if len(a) > 1 else None)
            if d is None:
                return orig(*a, **kw)
            if self.breaker and self.mode == "halt":
                return None
            if self.trend_gate and not self._trend_ok(d, kw.get("price_data", a[3] if len(a) > 3 else None)):
                self.counts["trend"] += 1
                return None
            if self.nfp_dates is not None:
                dd = d.date() if hasattr(d, "date") else d
                if dd in self.nfp_dates or (dd + timedelta(days=1)) in self.nfp_dates:
                    self.counts["nfp"] += 1
                    return None
            if self.contango_gate and not self._contango_ok(d):
                self.counts["contango"] += 1
                return None
            return orig(*a, **kw)
        return fn

    def _trend_ok(self, d, price_data):
        """Prior-day close > 200d MA. Insufficient history -> block (conservative)."""
        if price_data is None:
            return False
        prev = self.pd.Timestamp((d - timedelta(days=1)).date())
        col = "Close" if "Close" in price_data.columns else "close"
        closes = price_data.loc[:prev][col].dropna()
        if len(closes) < 200:
            return False
        return float(closes.iloc[-1]) > float(closes.tail(200).mean())

    def _contango_ok(self, d):
        """Allow entry only when VIX < VIX3M. Missing data -> allow (don't distort)."""
        ts = self.pd.Timestamp(d.date() if hasattr(d, "date") else d)
        vix = self.bt._vix_by_date.get(ts)
        vix3m = self.bt._vix3m_by_date.get(ts)
        if vix is None or vix3m is None:
            return True
        return float(vix) < float(vix3m)

    # month-anchored breaker (V3/V12)
    def _wrapped_manage(self, positions, current_date, current_price, ticker=""):
        positions = self._orig_manage(positions, current_date, current_price, ticker)
        equity = self.bt.capital + sum(p.get("current_value", 0) for p in positions)
        m = (current_date.year, current_date.month)
        if self.month is None:
            self.month = m
        if m != self.month:
            month_ret = equity / self.month_start_nav - 1 if self.month_start_nav else 0.0
            if self.entered_month_mode == "full" and month_ret >= 0:
                new_mode = "full"
            elif month_ret > 0:
                new_mode = "full"        # positive month restores full size
            else:
                new_mode = "half"        # resume next month at half after any breach/negative
            # a clean full-size positive month keeps full; a halted/halved month resumes half
            if self.mode == "full" and month_ret >= 0:
                new_mode = "full"
            self.mode = new_mode
            self.entered_month_mode = new_mode
            self.month = m
            self.prev_month_start = self.month_start_nav
            self.month_start_nav = equity
        dd = (equity - self.month_start_nav) / self.month_start_nav * 100.0 if self.month_start_nav else 0.0
        if dd <= -10.0:
            self.mode = "halt"
        elif dd <= -5.0 and self.mode == "full":
            self.mode = "half"
        eff = {"full": self.base_risk, "half": self.base_risk * 0.5, "halt": 0.0}[self.mode]
        if self.mode == "half":
            self.counts["breaker_half_days"] += 1
        elif self.mode == "halt":
            self.counts["breaker_halt_days"] += 1
        self.bt.risk_params["max_risk_per_trade"] = max(eff, 0.0)
        return positions


# ── variant table (mirrors the pre-registration exactly) ─────────────────────
def variant_spec(vid: str):
    s = {"strategy": dict(BASE["strategy"]), "risk": dict(BASE["risk"]),
         "otm_pct": BASE["otm_pct"], "monday_only": False, "manage_dte": 5,
         "gates": {}}
    if vid == "V0":
        pass
    elif vid == "V1":
        s["monday_only"] = True
    elif vid == "V2":
        s["gates"]["trend_gate"] = True
    elif vid == "V3":
        s["gates"]["breaker"] = True
    elif vid == "V4":
        s["strategy"].update(use_delta_selection=True, target_delta=0.15)
    elif vid == "V5":
        s["strategy"].update(use_delta_selection=True, target_delta=0.10)
    elif vid == "V6":
        s["strategy"]["min_credit_pct"] = 10
    elif vid == "V7":
        s["risk"]["stop_loss_multiplier"] = 1.0
    elif vid == "V8":
        s["risk"].update(profit_target=65, stop_loss_multiplier=1.5)
    elif vid == "V9":
        s["gates"]["nfp_gate"] = True
    elif vid == "V10":
        s["gates"]["contango_gate"] = True
    elif vid == "V11":
        s["gates"]["trend_gate"] = True
        s["strategy"].update(use_delta_selection=True, target_delta=0.15)
    elif vid == "V12":
        s["gates"].update(trend_gate=True, breaker=True, nfp_gate=True)
    else:
        raise SystemExit(f"unknown variant {vid}")
    return s


def main():
    vid, window = sys.argv[1], sys.argv[2]
    start_s, end_s = WINDOWS[window]
    spec = variant_spec(vid)

    logging.basicConfig(level=logging.WARNING)
    _load_env(ROOT / ".env.expv8a")

    engine_config = {
        "backtest": {**BACKTEST_BLOCK, "fill_model": "marketable"},
        "strategy": spec["strategy"],
        "risk": spec["risk"],
    }
    assert_holdout_seal(end_s)
    from backtest.backtester import Backtester
    from backtest.historical_data import HistoricalOptionsData

    hist = HistoricalOptionsData(os.environ.get("POLYGON_API_KEY", "dummy"), offline_mode=True)
    bt = Backtester(config=engine_config, historical_data=hist, otm_pct=float(spec["otm_pct"]))
    shims = FidelityShims(bt, spec["monday_only"], spec["manage_dte"])
    gates = SearchGates(bt, **spec["gates"]) if spec["gates"] else None

    results = bt.run_backtest(ticker="SPY",
                              start_date=datetime.fromisoformat(start_s),
                              end_date=datetime.fromisoformat(end_s))
    hist.close()
    if not results:
        print("ERROR: empty results", file=sys.stderr)
        sys.exit(1)

    trades = results.get("trades", [])
    pnls = [t["pnl"] for t in trades]
    expectancy = sum(pnls) / len(pnls) if pnls else 0.0
    per_year = _per_year_returns(bt.equity_curve)
    summary = {
        "variant": vid, "window": window, "range": [start_s, end_s],
        "fill_model": "marketable",
        "metrics": {
            "total_trades": results.get("total_trades"),
            "return_pct": results.get("return_pct"),
            "win_rate": results.get("win_rate"),
            "sharpe_ratio": results.get("sharpe_ratio"),
            "max_drawdown_pct": results.get("max_drawdown"),
            "expectancy_per_trade": round(expectancy, 2),
            "ending_capital": results.get("ending_capital"),
        },
        "per_year_returns_pct": per_year,
        "unfilled_entries": results.get("unfilled_entries", 0),
        "gate_counts": gates.counts if gates else {},
        "shims": {"monday_blocked": shims.monday_blocked, "dte_closes": shims.dte_closes},
        "exit_reasons": {},
        "trades": [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in t.items()} for t in trades],
        "equity_curve": [(d.isoformat() if hasattr(d, "isoformat") else str(d), float(v)) for d, v in bt.equity_curve],
    }
    for t in trades:
        r = str(t.get("exit_reason", "?"))
        summary["exit_reasons"][r] = summary["exit_reasons"].get(r, 0) + 1
    out = OUT / f"search_{vid}_{window}.json"
    out.write_text(json.dumps(summary, indent=1, default=str))
    m = summary["metrics"]
    print(f"[{vid}/{window}] trades={m['total_trades']} total={m['return_pct']}% "
          f"exp/trade=${m['expectancy_per_trade']} wr={m['win_rate']}% maxDD={m['max_drawdown_pct']}% "
          f"per_year={per_year} gates={summary['gate_counts']}")


if __name__ == "__main__":
    main()
