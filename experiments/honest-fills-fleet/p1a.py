#!/usr/bin/env python3
"""EXP-P1A runner — XLI + QQQ defined-risk premium (prereg: EXP-P1A_PREREG.md,
signed off & committed c2356b7 BEFORE any run).

Six variants A1..A6, marketable fills only, 2020-01-02..2024-12-31 only.
Harness shims (engine code untouched):
  - Monday-only entries (FidelityShims)
  - manage_dte <= 5 (FidelityShims; live semantics)
  - constant-'bull' regime series override: kills the MA/direction gate and
    bear-calls, so vertical entries are unconditional weekly premium harvest
    and ICs are entered regardless of regime (prereg: no direction engine)
  - puts-only for vertical variants is implied by the constant-bull override;
    IC-only variants additionally gate the bull-put finder to None
  - absolute credit floor at entry: credit*100 >= 35.20 (verticals) /
    70.40 (ICs) per the P0A ledger 2x-friction rule (A6 runs floorless)

Usage: .venv/bin/python experiments/honest-fills-fleet/p1a.py A3
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
OUT = Path(__file__).resolve().parent / "results"

from run import assert_holdout_seal, BACKTEST_BLOCK, FidelityShims, _load_env, _per_year_returns  # noqa: E402

WINDOW = ("2020-01-02", "2024-12-31")
FRICTION_2LEG = 17.60
FRICTION_4LEG = 35.20
FLOOR_VERT = 2 * FRICTION_2LEG   # $35.20 per prereg
FLOOR_IC = 2 * FRICTION_4LEG     # $70.40

BASE_RISK = {
    "max_risk_per_trade": 5.0,
    "max_contracts": 10,
    "max_positions": 3,
    "profit_target": 50,
    "stop_loss_multiplier": 2.0,
    "drawdown_cb_pct": 1000,   # no per-experiment breaker exists live
}

def base_strategy(otm_pct, ic_enabled):
    return {
        "direction": "bull_put",
        "target_dte": 30, "min_dte": 21, "max_dte": 45,
        "use_delta_selection": False,
        "spread_width": None,          # set per variant
        "regime_mode": "combo",        # series overridden to constant 'bull' below
        "regime_config": {"signals": ["price_vs_ma200", "rsi_momentum", "vix_structure"],
                          "ma_slow_period": 50},
        "iron_condor": {"enabled": ic_enabled, "neutral_regime_only": False,
                        "otm_pct_put": 0.04, "otm_pct_call": 0.03,
                        "spread_width": None, "min_combined_credit_pct": 0,
                        "profit_target_pct": 0.50, "stop_loss_multiplier": 2.0,
                        "max_risk_pct": 5.0},
        "min_credit_pct": 1,           # engine %-of-width floor ~off; absolute floor is shimmed
        "vix_max_entry": 35.0,
        "momentum_filter_pct": None,
        "trend_ma_period": 50,
        "max_positions_per_expiration": 2,
    }

# spread widths ~3% of typical spot (ledger 'wide' class): XLI ~110 -> 3; QQQ ~400 -> 12
VARIANTS = {
    "A1": {"ticker": "XLI", "otm": 0.02, "width": 3,  "ic": False, "floor": FLOOR_VERT},
    "A2": {"ticker": "XLI", "otm": 0.04, "width": 3,  "ic": True,  "floor": FLOOR_IC},
    "A3": {"ticker": "QQQ", "otm": 0.02, "width": 12, "ic": False, "floor": FLOOR_VERT},
    "A4": {"ticker": "QQQ", "otm": 0.05, "width": 12, "ic": False, "floor": FLOOR_VERT},
    "A5": {"ticker": "QQQ", "otm": 0.04, "width": 12, "ic": True,  "floor": FLOOR_IC},
    "A6": {"ticker": "QQQ", "otm": 0.02, "width": 12, "ic": False, "floor": 0.0},
}


class P1AShims:
    """Constant-bull regime override + IC-only gating + absolute credit floor."""

    def __init__(self, bt, ic_only: bool, floor: float):
        self.bt = bt
        self.floor = floor
        self.floor_rejects = 0
        # after the engine builds its regime series, flatten it to 'bull'
        orig_build = bt._build_combo_regime_series
        def build(*a, **kw):
            orig_build(*a, **kw)
            bt._regime_by_date = {k: "bull" for k in bt._regime_by_date}
        bt._build_combo_regime_series = build
        if ic_only:
            bt._find_backtest_opportunity = lambda *a, **kw: None
        if floor > 0:
            for name in ("_find_backtest_opportunity", "_find_iron_condor_opportunity"):
                setattr(bt, name, self._floor_gate(getattr(bt, name)))

    def _floor_gate(self, orig):
        def fn(*a, **kw):
            pos = orig(*a, **kw)
            if pos is None:
                return None
            if pos.get("credit", 0) * 100 < self.floor:
                self.floor_rejects += 1
                return None
            return pos
        return fn


def main():
    vid = sys.argv[1]
    v = VARIANTS[vid]
    logging.basicConfig(level=logging.WARNING)
    _load_env(ROOT / ".env.expv8a")

    strat = base_strategy(v["otm"], v["ic"])
    strat["spread_width"] = v["width"]
    strat["iron_condor"]["spread_width"] = v["width"]
    engine_config = {
        "backtest": {**BACKTEST_BLOCK, "fill_model": "marketable"},
        "strategy": strat,
        "risk": dict(BASE_RISK),
    }
    from backtest.backtester import Backtester
    from backtest.historical_data import HistoricalOptionsData

    assert_holdout_seal(WINDOW[1])
    hist = HistoricalOptionsData(os.environ.get("POLYGON_API_KEY", "dummy"), offline_mode=True)
    bt = Backtester(config=engine_config, historical_data=hist, otm_pct=float(v["otm"]))
    fid = FidelityShims(bt, monday_only=True, manage_dte=5)
    shims = P1AShims(bt, ic_only=v["ic"], floor=v["floor"])

    results = bt.run_backtest(ticker=v["ticker"],
                              start_date=datetime.fromisoformat(WINDOW[0]),
                              end_date=datetime.fromisoformat(WINDOW[1]))
    hist.close()
    if not results:
        print("ERROR: empty results", file=sys.stderr)
        sys.exit(1)

    trades = results.get("trades", [])
    pnls = [t["pnl"] for t in trades]
    expectancy = sum(pnls) / len(pnls) if pnls else 0.0
    per_year = {int(k): float(x) for k, x in _per_year_returns(bt.equity_curve).items()}
    n_entries = len(trades)
    fallbacks = results.get("fill_model_naive_fallbacks", 0)
    summary = {
        "variant": vid, "spec": {k: vv for k, vv in v.items()},
        "prereg": "reports/honest_fills_fleet/EXP-P1A_PREREG.md@c2356b7",
        "window": list(WINDOW), "fill_model": "marketable",
        "metrics": {
            "total_trades": results.get("total_trades"),
            "return_pct": results.get("return_pct"),
            "win_rate": results.get("win_rate"),
            "sharpe_ratio": results.get("sharpe_ratio"),
            "max_drawdown_pct": results.get("max_drawdown"),
            "expectancy_per_trade": round(expectancy, 2),
        },
        "per_year_returns_pct": per_year,
        "unfilled_entries": results.get("unfilled_entries", 0),
        "naive_fallbacks": fallbacks,
        "naive_fallback_pct_of_trades": round(fallbacks / n_entries * 100, 1) if n_entries else None,
        "floor_rejects": shims.floor_rejects,
        "shims": {"monday_blocked": fid.monday_blocked, "dte_closes": fid.dte_closes},
        "exit_reasons": {},
        "trades": [{k: (x.isoformat() if hasattr(x, "isoformat") else x) for k, x in t.items()} for t in trades],
        "equity_curve": [(d.isoformat() if hasattr(d, "isoformat") else str(d), float(val)) for d, val in bt.equity_curve],
    }
    for t in trades:
        r = str(t.get("exit_reason", "?"))
        summary["exit_reasons"][r] = summary["exit_reasons"].get(r, 0) + 1
    (OUT / f"p1a_{vid}.json").write_text(json.dumps(summary, indent=1, default=str))
    m = summary["metrics"]
    print(f"[P1A/{vid}/{v['ticker']}] trades={m['total_trades']} total={m['return_pct']}% "
          f"exp=${m['expectancy_per_trade']} wr={m['win_rate']}% maxDD={m['max_drawdown_pct']}% "
          f"worst_yr={min(per_year.values()) if per_year else None} fallbacks={fallbacks} "
          f"floor_rejects={shims.floor_rejects} per_year={per_year}")


if __name__ == "__main__":
    main()
