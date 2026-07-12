#!/usr/bin/env python3
"""EXP-P1F — TLT rate-vol premium (prereg: reports/profitability_program/EXP-P1F_PREREG.md).

Runs the 6 pre-registered variants on TLT, 2020-01-02 -> 2024-12-31 HARD CAP,
marketable fills ONLY (program rule). Engine path identical to the fleet
harness (run_twin.py). No live/deploy configs touched; offline cache marks.

Variants (final per prereg — no additions):
  V1 put-30        always-on put credit vertical, DTE 30 (21-45)
  V2 call-30       always-on call credit vertical, DTE 30
  V3 strangle-30   both sides entered together (direction both, both bypasses)
  V4 put-15        always-on put vertical, DTE 15 (12-25)
  V5 trend-30      engine-native 200d-MA trend conditioning, both sides
  V6 put-30-rich   V1 + min_credit_pct 22 (P0A median-premium floor)

Shared base: strikes 2% OTM, $4 width, Monday-only entries, 5% flat risk
non-compounding / $100k, max 15 contracts / 5 positions / 2 per expiration,
PT 50% of credit, SL 2.0x credit, no early-DTE exit, min_credit_pct 12,
no momentum filter, no VIX gate (equity-vol measure — wrong driver for TLT),
iron_condor disabled (strangle = two verticals). Engine drawdown CB left at
its default (40, latching) — immaterial to pass/fail since the prereg's DD
gate (-20%) fails a variant long before the CB binds; share documented.

Always-on variants bypass the engine's non-combo MA trend gate by
neutralizing _compute_trend_ma per finder call (put -> -inf, call -> +inf),
the precedented fleet-shim pattern. V5 uses the gate natively at MA 200.
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

TICKER = "TLT"
WINDOW = (datetime(2020, 1, 2), datetime(2024, 12, 31))
assert WINDOW[1] <= datetime(2024, 12, 31), "prereg hard cap: nothing past 2024-12-31"
FILL_MODEL = "marketable"  # prereg: marketable only

VARIANTS = {
    "V1_put30":      {"direction": "bull_put",  "dte": (30, 21, 45), "bypass": ("put",),         "min_credit_pct": 12},
    "V2_call30":     {"direction": "bear_call", "dte": (30, 21, 45), "bypass": ("call",),        "min_credit_pct": 12},
    "V3_strangle30": {"direction": "both",      "dte": (30, 21, 45), "bypass": ("put", "call"),  "min_credit_pct": 12},
    "V4_put15":      {"direction": "bull_put",  "dte": (15, 12, 25), "bypass": ("put",),         "min_credit_pct": 12},
    "V5_trend30":    {"direction": "both",      "dte": (30, 21, 45), "bypass": (),               "min_credit_pct": 12},
    "V6_put30rich":  {"direction": "bull_put",  "dte": (30, 21, 45), "bypass": ("put",),         "min_credit_pct": 22},
}


def _load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class P1FOverlay:
    """Monday-only entry gate + per-variant trend-gate bypass."""

    def __init__(self, bt, bypass: tuple):
        self.bt = bt
        self.counters = {"non_monday_blocked": 0, "attempts": 0}
        self._orig_put = bt._find_backtest_opportunity
        self._orig_call = bt._find_bear_call_opportunity
        bt._find_backtest_opportunity = self._make("put", self._orig_put, "put" in bypass, float("-inf"))
        bt._find_bear_call_opportunity = self._make("call", self._orig_call, "call" in bypass, float("inf"))
        # iron condor finder disabled via config; belt-and-braces:
        bt._find_iron_condor_opportunity = lambda *a, **kw: None

    def _make(self, side, orig, bypass, ma_value):
        def fn(*a, **kw):
            when = a[1]
            self.counters["attempts"] += 1
            if when.weekday() != 0:  # Monday-only entries (prereg)
                self.counters["non_monday_blocked"] += 1
                return None
            if not bypass:
                return orig(*a, **kw)
            old = self.bt._compute_trend_ma
            self.bt._compute_trend_ma = lambda closes: ma_value
            try:
                return orig(*a, **kw)
            finally:
                self.bt._compute_trend_ma = old
        return fn


def _per_year_returns(equity_curve):
    import pandas as pd
    s = pd.Series({pd.Timestamp(d): v for d, v in equity_curve}).sort_index()
    out = {}
    for year, grp in s.groupby(s.index.year):
        prior = s[s.index < grp.index[0]]
        base = prior.iloc[-1] if len(prior) else grp.iloc[0]
        out[int(year)] = round((grp.iloc[-1] / base - 1) * 100, 2)
    return out


def run_variant(name: str) -> dict:
    v = VARIANTS[name]
    target, lo, hi = v["dte"]
    engine_config = {
        "backtest": {
            "starting_capital": 100000,
            "commission_per_contract": 0.65,
            "slippage": 0.05,
            "exit_slippage": 0.10,
            "sizing_mode": "flat",
            "compound": False,
            "fill_model": FILL_MODEL,
        },
        "strategy": {
            "direction": v["direction"],
            "target_dte": target,
            "min_dte": lo,
            "max_dte": hi,
            "use_delta_selection": False,
            "spread_width": 4,
            "regime_mode": "none",           # non-combo: direction fixed per variant
            "trend_ma_period": 200,           # V5 native gate; bypassed elsewhere
            "iron_condor": {"enabled": False},
            "min_credit_pct": v["min_credit_pct"],
            "vix_max_entry": 0,
            "momentum_filter_pct": None,
            "max_positions_per_expiration": 2,
        },
        "risk": {
            "max_risk_per_trade": 5.0,
            "max_contracts": 15,
            "max_positions": 5,
            "profit_target": 50,
            "stop_loss_multiplier": 2.0,
        },
    }

    from backtest.backtester import Backtester
    from backtest.historical_data import HistoricalOptionsData

    hist = HistoricalOptionsData(os.environ.get("POLYGON_API_KEY", "dummy"), offline_mode=True)
    bt = Backtester(config=engine_config, historical_data=hist, otm_pct=0.02)
    overlay = P1FOverlay(bt, v["bypass"])
    results = bt.run_backtest(ticker=TICKER, start_date=WINDOW[0], end_date=WINDOW[1])
    hist.close()
    if not results:
        raise RuntimeError(f"{name}: empty results")

    trades = results.get("trades", [])
    total_trades = results.get("total_trades", len(trades))
    total_pnl = float(results.get("total_pnl", 0.0))
    expectancy = total_pnl / total_trades if total_trades else 0.0
    unfilled = int(results.get("unfilled_entries", 0))
    fallbacks = int(results.get("fill_model_naive_fallbacks", 0))
    per_year = _per_year_returns(bt.equity_curve)
    worst_year = min(per_year.values()) if per_year else None
    ending = float(results.get("ending_capital", 0))
    years = (WINDOW[1] - WINDOW[0]).days / 365.25
    cagr = ((ending / 100000) ** (1 / years) - 1) * 100 if ending > 0 else -100.0

    exit_reasons = {}
    for t in trades:
        r = str(t.get("exit_reason", "?"))
        exit_reasons[r] = exit_reasons.get(r, 0) + 1

    summary = {
        "experiment": "EXP-P1F",
        "variant": name,
        "fill_model": FILL_MODEL,
        "window": [WINDOW[0].date().isoformat(), WINDOW[1].date().isoformat()],
        "metrics": {
            "trades": total_trades,
            "total_return": results.get("return_pct"),
            "cagr": round(cagr, 2),
            "win_rate": results.get("win_rate"),
            "sharpe": results.get("sharpe_ratio"),
            "max_dd": results.get("max_drawdown"),
            "worst_year": worst_year,
            "expectancy_per_trade": round(expectancy, 2),
            "total_pnl": round(total_pnl, 2),
            "ending_capital": ending,
            "ruin_triggered": bool(getattr(bt, "_ruin_triggered", False)),
        },
        "fills": {
            "unfilled_entries": unfilled,
            "pct_unfillable_slot_basis": round(unfilled / (unfilled + total_trades) * 100, 2) if (unfilled + total_trades) else 0.0,
            "naive_fallbacks": fallbacks,
            "naive_fallback_share_pct": round(fallbacks / total_trades * 100, 2) if total_trades else 0.0,
        },
        "per_year_returns_pct": per_year,
        "exit_reasons": exit_reasons,
        "overlay_counters": overlay.counters,
        "equity_curve": [(d.isoformat() if hasattr(d, "isoformat") else str(d), float(x)) for d, x in bt.equity_curve],
        "trades": [{k: (x.isoformat() if hasattr(x, "isoformat") else x) for k, x in t.items()} for t in trades],
    }
    (OUT / f"p1f_{name}.json").write_text(json.dumps(summary, indent=2, default=str))
    m = summary["metrics"]
    print(f"[P1F/{name}] trades={m['trades']} total={m['total_return']}% cagr={m['cagr']}% "
          f"wr={m['win_rate']}% sharpe={m['sharpe']} maxDD={m['max_dd']}% worstYr={m['worst_year']}% "
          f"exp/tr=${m['expectancy_per_trade']} fallbacks={fallbacks} unfilled={unfilled} ruin={m['ruin_triggered']}")
    print(f"  per-year: {per_year}  exits: {exit_reasons}")
    return summary


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    _load_env(ROOT / ".env.expv8a")  # POLYGON_API_KEY for TLT daily bars only
    names = sys.argv[1:] or list(VARIANTS)
    for n in names:
        run_variant(n)


if __name__ == "__main__":
    main()
