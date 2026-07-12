#!/usr/bin/env python3
"""EXP-P1A-CAPACITY runner — 32-cell sizing sweep on A4-as-passed.

Prereg: reports/profitability_program/EXP-P1A-CAPACITY_PREREG.md @ b2b77df
(committed before any run). In-sample 2020-2024 ONLY (assert_holdout_seal).
Marketable fills. Base config identical to p1a.py A4 except the swept axes:
max_positions {3,5,8,12} x max_risk {5,8,10,15}% x cadence {mon, monthu};
max_contracts raised to 30 per prereg so risk% binds.

Usage: .venv/bin/python experiments/honest-fills-fleet/capacity.py 8 10 monthu
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
OUT = Path(__file__).resolve().parent / "results"

from run import assert_holdout_seal, BACKTEST_BLOCK, FidelityShims, _load_env, _per_year_returns  # noqa: E402
from p1a import P1AShims, base_strategy, FLOOR_VERT  # noqa: E402

WINDOW = ("2020-01-02", "2024-12-31")
CADENCE_DAYS = {"mon": {0}, "monthu": {0, 3}}


class CadenceGate:
    """Entry weekday gate (generalizes the Monday-only shim)."""

    def __init__(self, bt, days: set):
        self.days = days
        self.blocked = 0
        for name in ("_find_backtest_opportunity", "_find_bear_call_opportunity",
                     "_find_iron_condor_opportunity"):
            setattr(bt, name, self._gate(getattr(bt, name)))

    def _gate(self, orig):
        def fn(*a, **kw):
            d = kw.get("date", a[1] if len(a) > 1 else None)
            if d is not None and d.weekday() not in self.days:
                self.blocked += 1
                return None
            return orig(*a, **kw)
        return fn


def peak_book_max_loss(trades, width=12.0, capital=100000.0):
    """Peak aggregate open max-loss as % of capital + max concurrency."""
    events = []
    for t in trades:
        ml = (width - float(t["credit"])) * 100 * int(t["contracts"])
        e0 = t["entry_date"][:10]
        e1 = (t.get("exit_date") or t["expiration"])[:10]
        events.append((e0, ml, 1))
        events.append((e1, -ml, -1))
    events.sort()
    cur = peak = 0.0
    ccur = cpeak = 0
    for _, ml, dc in events:
        cur += ml
        ccur += dc
        peak = max(peak, cur)
        cpeak = max(cpeak, ccur)
    return round(peak / capital * 100, 1), cpeak


def main():
    positions, risk, cad = int(sys.argv[1]), float(sys.argv[2]), sys.argv[3]
    assert cad in CADENCE_DAYS
    logging.basicConfig(level=logging.WARNING)
    _load_env(ROOT / ".env.expv8a")
    assert_holdout_seal(WINDOW[1])

    strat = base_strategy(0.05, ic_enabled=False)   # A4 base
    strat["spread_width"] = 12
    strat["iron_condor"]["spread_width"] = 12
    engine_config = {
        "backtest": {**BACKTEST_BLOCK, "fill_model": "marketable"},
        "strategy": strat,
        "risk": {
            "max_risk_per_trade": risk,
            "max_contracts": 30,           # prereg: risk% must be the binding variable
            "max_positions": positions,
            "profit_target": 50,
            "stop_loss_multiplier": 2.0,
            "drawdown_cb_pct": 1000,
        },
    }
    from backtest.backtester import Backtester
    from backtest.historical_data import HistoricalOptionsData

    hist = HistoricalOptionsData(os.environ.get("POLYGON_API_KEY", "dummy"), offline_mode=True)
    bt = Backtester(config=engine_config, historical_data=hist, otm_pct=0.05)
    fid = FidelityShims(bt, monday_only=False, manage_dte=5)
    gate = CadenceGate(bt, CADENCE_DAYS[cad])
    shims = P1AShims(bt, ic_only=False, floor=FLOOR_VERT)

    results = bt.run_backtest(ticker="QQQ",
                              start_date=datetime.fromisoformat(WINDOW[0]),
                              end_date=datetime.fromisoformat(WINDOW[1]))
    hist.close()
    if not results:
        print("ERROR: empty results", file=sys.stderr)
        sys.exit(1)

    trades = results.get("trades", [])
    pnls = [t["pnl"] for t in trades]
    expectancy = sum(pnls) / len(pnls) if pnls else 0.0
    per_year = {int(k): float(v) for k, v in _per_year_returns(bt.equity_curve).items()}
    ending = float(results["ending_capital"])
    years = 5.0
    cagr = ((ending / 100000.0) ** (1 / years) - 1) * 100 if ending > 0 else -100.0
    peak_ml_pct, max_conc = peak_book_max_loss(
        [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in t.items()} for t in trades])

    summary = {
        "cell": {"positions": positions, "risk_pct": risk, "cadence": cad},
        "prereg": "reports/profitability_program/EXP-P1A-CAPACITY_PREREG.md@b2b77df",
        "window": list(WINDOW), "fill_model": "marketable",
        "metrics": {
            "total_trades": results.get("total_trades"),
            "return_pct": results.get("return_pct"),
            "cagr_pct": round(cagr, 2),
            "win_rate": results.get("win_rate"),
            "sharpe_ratio": results.get("sharpe_ratio"),
            "max_drawdown_pct": results.get("max_drawdown"),
            "expectancy_per_trade": round(expectancy, 2),
            "worst_year": min(per_year.values()) if per_year else None,
            "peak_book_max_loss_pct": peak_ml_pct,
            "max_concurrent_reached": max_conc,
        },
        "per_year_returns_pct": per_year,
        "unfilled_entries": results.get("unfilled_entries", 0),
        "naive_fallbacks": results.get("fill_model_naive_fallbacks", 0),
        "floor_rejects": shims.floor_rejects,
        "cadence_blocked": gate.blocked,
        "exit_reasons": {},
    }
    for t in trades:
        r = str(t.get("exit_reason", "?"))
        summary["exit_reasons"][r] = summary["exit_reasons"].get(r, 0) + 1
    name = f"cap_p{positions}_r{int(risk)}_{cad}"
    (OUT / f"{name}.json").write_text(json.dumps(summary, indent=1, default=str))
    m = summary["metrics"]
    print(f"[{name}] trades={m['total_trades']} cagr={m['cagr_pct']}% total={m['return_pct']}% "
          f"maxDD={m['max_drawdown_pct']}% worst_yr={m['worst_year']} exp=${m['expectancy_per_trade']} "
          f"peakML={m['peak_book_max_loss_pct']}% maxconc={m['max_concurrent_reached']}")


if __name__ == "__main__":
    main()
