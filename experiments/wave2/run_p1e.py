#!/usr/bin/env python3
"""EXP-P1E — skew-harvest butterflies, debit-reclassified (prereg: EXP-P1E_PREREG.md).

Usage: .venv/bin/python experiments/wave2/run_p1e.py [X1_SPY_flat_30 ...]
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)

WINDOW = ("2020-01-02", "2024-12-31")

_spec = importlib.util.spec_from_file_location(
    "hf_run", ROOT / "experiments" / "honest-fills-fleet" / "run.py")
_hf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_hf)
_hf.assert_holdout_seal(WINDOW[1])

from backtest.multileg import (  # noqa: E402
    Leg, MarksDB, net_mark, profit_target, roll_at_dte, run_portfolio, stop_loss,
)

DB = ROOT / "data" / "options_cache.db"
RISK_DOLLARS = 2_500.0
MAX_CONTRACTS = 25
MAX_POSITIONS = 3

GEOM = {"flat": (0.98, 0.95, 0.92), "crash": (0.98, 0.95, 0.935), "cheap": (0.98, 0.95, 0.90)}

VARIANTS = {
    "X1_SPY_flat_30":  {"ticker": "SPY", "geom": "flat",  "dte": 30},
    "X2_SPY_crash_30": {"ticker": "SPY", "geom": "crash", "dte": 30},
    "X3_SPY_cheap_30": {"ticker": "SPY", "geom": "cheap", "dte": 30},
    "X4_QQQ_flat_30":  {"ticker": "QQQ", "geom": "flat",  "dte": 30},
    "X5_QQQ_crash_30": {"ticker": "QQQ", "geom": "crash", "dte": 30},
    "X6_SPY_crash_15": {"ticker": "SPY", "geom": "crash", "dte": 15},
}


def underlier_closes(ticker: str) -> dict[str, float]:
    for line in (ROOT / ".env.expv8a").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"'))
    from backtest.market_history import load_market_history
    df = load_market_history(ticker, datetime(2019, 10, 1), datetime(2024, 12, 31))
    return {d.strftime("%Y-%m-%d"): float(r["Close"]) for d, r in df.iterrows()}


def pick_expiry(db, ticker, day, target):
    d = date.fromisoformat(day)
    lo, hi = int(target * 0.6), int(target * 1.4)
    exps = db.expirations(ticker, (d + timedelta(days=lo)).isoformat(),
                          (d + timedelta(days=hi)).isoformat())
    return min(exps, key=lambda e: abs((date.fromisoformat(e) - d).days - target)) if exps else None


def is_first_trading_day_of_week(days, i):
    if i == 0:
        return True
    return date.fromisoformat(days[i]).isocalendar()[:2] != \
        date.fromisoformat(days[i - 1]).isocalendar()[:2]


def make_signal(db, v, days, closes):
    ticker, dte = v["ticker"], v["dte"]
    up_pct, body_pct, lo_pct = GEOM[v["geom"]]
    day_index = {d: i for i, d in enumerate(days)}

    def signal(day, _db, open_positions):
        if not is_first_trading_day_of_week(days, day_index[day]):
            return []
        spot = closes.get(day)
        if spot is None:
            return []
        exp = pick_expiry(db, ticker, day, dte)
        if not exp or any(p.meta.get("expiry") == exp for p in open_positions):
            return []
        puts = db.strikes(ticker, exp, "P")
        if len(puts) < 5:
            return []
        ku = min(puts, key=lambda s: abs(s - spot * up_pct))
        kb = min(puts, key=lambda s: abs(s - spot * body_pct))
        kl = min(puts, key=lambda s: abs(s - spot * lo_pct))
        if not (kl < kb < ku):
            return []
        syms = [db.contract(ticker, exp, k, "P") for k in (ku, kb, kl)]
        if any(s is None for s in syms):
            return []
        legs = [Leg(syms[0], +1, 1, exp), Leg(syms[1], -1, 2, exp), Leg(syms[2], +1, 1, exp)]
        open_net, complete, _ = net_mark(db, legs, day, "open")
        if open_net is None or not complete or open_net >= -0.01:
            return []  # must be a debit (net < 0); credit prints are mark noise here
        debit = -open_net
        width_diff = max(0.0, (kb - kl) - (ku - kb))   # extra tail loss for 'cheap'
        modeled = (debit + width_diff) * 100
        contracts = max(1, min(MAX_CONTRACTS, int(RISK_DOLLARS // modeled))) if modeled > 0 else 1
        meta = {"expiry": exp, "strikes": [ku, kb, kl], "debit_1x": round(debit, 4),
                "modeled_max_loss_1x": round(modeled / 100, 4)}
        return [(legs, contracts, meta)]

    return signal


def per_year(equity):
    out, by_year, prev = {}, {}, None
    for d, v_ in equity:
        by_year.setdefault(d[:4], []).append(v_)
    for y in sorted(by_year):
        base = prev if prev is not None else by_year[y][0]
        out[y] = round((by_year[y][-1] / base - 1) * 100, 2)
        prev = by_year[y][-1]
    return out


def month_pnl(equity, ym):
    pts = [v for d, v in equity if d[:7] == ym]
    if not pts:
        return None
    prior = [v for d, v in equity if d[:7] < ym]
    base = prior[-1] if prior else pts[0]
    return round((pts[-1] / base - 1) * 100, 2)


def main() -> None:
    names = sys.argv[1:] or list(VARIANTS)
    db = MarksDB(DB)
    closes_cache: dict = {}
    for name in names:
        v = VARIANTS[name]
        closes = closes_cache.setdefault(v["ticker"], underlier_closes(v["ticker"]))
        days = db.trading_days(v["ticker"], *WINDOW)
        res = run_portfolio(
            db, days, make_signal(db, v, days, closes),
            exit_rules=[profit_target(1.00), stop_loss(0.50), roll_at_dte(5)],
            starting_capital=100_000.0, fill_model="marketable",
            max_positions=MAX_POSITIONS,
        )
        s = res.summary(100_000.0)
        py = per_year(res.equity_curve)
        s["worst_year"] = min(py.values()) if py else None
        s["expectancy_per_trade"] = round(
            sum(t["pnl"] for t in res.trades) / len(res.trades), 2) if res.trades else 0.0
        s["fill_rate_pct"] = round(100.0 * s["total_trades"] / s["entry_attempts"], 1) \
            if s["entry_attempts"] else 0.0
        s["pnl_2020_03_pct"] = month_pnl(res.equity_curve, "2020-03")
        s["pnl_2022_pct"] = py.get("2022")
        debits = sorted(t["meta"]["debit_1x"] for t in res.trades if t.get("meta"))
        med_debit = debits[len(debits) // 2] if debits else None
        s["median_debit_usd"] = round(med_debit * 100, 2) if med_debit else None
        s["friction_share_of_debit_pct"] = round(35.2 / (med_debit * 100) * 100, 1) \
            if med_debit else None
        out = {"experiment": "EXP-P1E", "variant": name, "spec": v,
               "window": list(WINDOW), "fill_model": "marketable",
               "summary": s, "per_year": py,
               "equity_curve": res.equity_curve, "trades": res.trades}
        (OUT / f"p1e_{name}.json").write_text(json.dumps(out, indent=2, default=str))
        print(f"[P1E/{name}] trades={s['total_trades']} ret={s['total_return_pct']}% "
              f"wr={s['win_rate_pct']}% sharpe={s['sharpe']} dd={s['max_dd_pct']}% "
              f"worstYr={s['worst_year']} exp/tr=${s['expectancy_per_trade']} "
              f"fill%={s['fill_rate_pct']} 2020-03={s['pnl_2020_03_pct']}% 2022={s['pnl_2022_pct']}% "
              f"medDebit=${s['median_debit_usd']} fric%={s['friction_share_of_debit_pct']}")
        print(f"  per-year: {py}")
    db.close()


if __name__ == "__main__":
    main()
