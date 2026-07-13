#!/usr/bin/env python3
"""EXP-P1B — calendar/diagonal term-structure VRP (prereg: EXP-P1B_PREREG.md).

Runs the 6 pre-registered variants on the shared direct-marks multi-leg
harness (backtest/multileg.py), 2020-01-02 -> 2024-12-31, marketable only.
Holdout seal enforced via the shared guard (one implementation, imported).

Usage: .venv/bin/python experiments/wave2/run_p1b.py [B1_GLD_cal ...]
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent / "results"
OUT.mkdir(exist_ok=True)

WINDOW = ("2020-01-02", "2024-12-31")

# One seal implementation: import the guard from the fleet runner.
_spec = importlib.util.spec_from_file_location(
    "hf_run", ROOT / "experiments" / "honest-fills-fleet" / "run.py")
_hf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_hf)
_hf.assert_holdout_seal(WINDOW[1])

from backtest.multileg import (  # noqa: E402
    Leg, MarksDB, profit_target, roll_at_dte, run_portfolio, stop_loss,
)

DB = ROOT / "data" / "options_cache.db"
RISK_DOLLARS = 2_500.0     # modeled max loss (debit) per trade
MAX_CONTRACTS = 25
MAX_POSITIONS = 3
FRONT = (15, 10, 25)       # target, lo, hi DTE
BACK = (45, 35, 60)

VARIANTS = {
    "B1_GLD_cal":      {"ticker": "GLD", "otype": "P", "diag_down": 0},
    "B2_SPY_cal":      {"ticker": "SPY", "otype": "P", "diag_down": 0},
    "B3_QQQ_cal":      {"ticker": "QQQ", "otype": "P", "diag_down": 0},
    "B4_TLT_cal":      {"ticker": "TLT", "otype": "P", "diag_down": 0},
    "B5_GLD_diag":     {"ticker": "GLD", "otype": "P", "diag_down": 1},
    "B6_SPY_call_cal": {"ticker": "SPY", "otype": "C", "diag_down": 0},
}


def pick_expiry(db: MarksDB, ticker: str, day: str, target: int, lo: int, hi: int) -> str | None:
    d = date.fromisoformat(day)
    exps = db.expirations(ticker, (d + timedelta(days=lo)).isoformat(),
                          (d + timedelta(days=hi)).isoformat())
    if not exps:
        return None
    return min(exps, key=lambda e: abs((date.fromisoformat(e) - d).days - target))


def parity_atm(db: MarksDB, ticker: str, expiration: str, day: str) -> float | None:
    """Strike minimizing |C-P| on the given chain/date (P0A method, no feed)."""
    rows = db.conn.execute(
        """SELECT c.strike, c.option_type, d.close FROM option_daily d
           JOIN option_contracts c USING(contract_symbol)
           WHERE c.ticker=? AND c.expiration=? AND d.date=? AND d.close>0""",
        (ticker, expiration, day)).fetchall()
    ch: dict = {}
    for strike, ot, close in rows:
        ch[(strike, ot)] = close
    best, atm = None, None
    for (k, t) in ch:
        if t != "C":
            continue
        p = ch.get((k, "P"))
        if p is None:
            continue
        diff = abs(ch[(k, "C")] - p)
        if best is None or diff < best:
            best, atm = diff, k
    return atm


def is_first_trading_day_of_week(days: list[str], i: int) -> bool:
    d = date.fromisoformat(days[i])
    if i == 0:
        return True
    prev = date.fromisoformat(days[i - 1])
    return d.isocalendar()[:2] != prev.isocalendar()[:2]


def make_signal(db: MarksDB, v: dict, days: list[str]):
    ticker, otype, diag = v["ticker"], v["otype"], v["diag_down"]
    day_index = {d: i for i, d in enumerate(days)}

    def signal(day: str, _db, open_positions):
        if not is_first_trading_day_of_week(days, day_index[day]):
            return []
        front = pick_expiry(db, ticker, day, *FRONT)
        back = pick_expiry(db, ticker, day, *BACK)
        if not front or not back or back <= front:
            return []
        if any(p.meta.get("front_exp") == front for p in open_positions):
            return []
        atm = parity_atm(db, ticker, front, day)
        if atm is None:
            return []
        # same strike must exist on BOTH chains (calendar); diagonal drops the
        # long leg N listed strikes below ATM on the back chain
        front_strikes = set(db.strikes(ticker, front, otype))
        back_strikes = sorted(db.strikes(ticker, back, otype))
        if atm not in front_strikes:
            cands = [s for s in front_strikes if abs(s - atm) <= 2]
            if not cands:
                return []
            atm = min(cands, key=lambda s: abs(s - atm))
        long_strike = atm
        if diag:
            below = [s for s in back_strikes if s < atm]
            if len(below) < diag:
                return []
            long_strike = below[-diag]
        elif atm not in back_strikes:
            return []
        s_short = db.contract(ticker, front, atm, otype)
        s_long = db.contract(ticker, back, long_strike, otype)
        if not s_short or not s_long:
            return []
        legs = [Leg(s_short, side=-1, qty=1, expiration=front),
                Leg(s_long, side=+1, qty=1, expiration=back)]
        # size off the decision-time OPEN net (same basis as the fill limit)
        from backtest.multileg import net_mark
        open_net, complete, had_open = net_mark(db, legs, day, "open")
        if open_net is None or not complete:
            return []
        debit = -open_net  # calendars are debits: open_net < 0
        if debit <= 0.01:
            return []      # degenerate/credit-priced pair — not the structure under test
        contracts = max(1, min(MAX_CONTRACTS, int(RISK_DOLLARS // (debit * 100))))
        meta = {"front_exp": front, "back_exp": back, "short_strike": atm,
                "long_strike": long_strike, "modeled_max_loss_1x": round(debit, 4)}
        return [(legs, contracts, meta)]

    return signal


def per_year(equity):
    out, by_year = {}, {}
    for d, v in equity:
        by_year.setdefault(d[:4], []).append(v)
    prev_end = None
    for y in sorted(by_year):
        base = prev_end if prev_end is not None else by_year[y][0]
        out[y] = round((by_year[y][-1] / base - 1) * 100, 2)
        prev_end = by_year[y][-1]
    return out


def main() -> None:
    names = sys.argv[1:] or list(VARIANTS)
    db = MarksDB(DB)
    for name in names:
        v = VARIANTS[name]
        days = db.trading_days(v["ticker"], *WINDOW)
        res = run_portfolio(
            db, days, make_signal(db, v, days),
            exit_rules=[profit_target(0.30), stop_loss(0.50), roll_at_dte(5)],
            starting_capital=100_000.0, fill_model="marketable",
            max_positions=MAX_POSITIONS,
        )
        s = res.summary(100_000.0)
        py = per_year(res.equity_curve)
        s["worst_year"] = min(py.values()) if py else None
        s["expectancy_per_trade"] = round(
            sum(t["pnl"] for t in res.trades) / len(res.trades), 2) if res.trades else 0.0
        # mark-trust gate: worst realized loss vs 1.5x modeled max (debit+friction)
        worst = None
        for t in res.trades:
            modeled = t.get("meta", {}).get("modeled_max_loss_1x", 0) * 100 * t["contracts"] \
                + t["commission"]
            if t["pnl"] < 0:
                ratio = -t["pnl"] / modeled if modeled > 0 else float("inf")
                if worst is None or ratio > worst[0]:
                    worst = (ratio, t["pnl"], round(modeled, 2))
        s["max_loss_vs_modeled_ratio"] = round(worst[0], 3) if worst else 0.0
        s["worst_trade"] = worst[1] if worst else 0.0
        out = {"experiment": "EXP-P1B", "variant": name, "spec": v,
               "window": list(WINDOW), "fill_model": "marketable",
               "summary": s, "per_year": py,
               "equity_curve": res.equity_curve,
               "trades": res.trades}
        (OUT / f"p1b_{name}.json").write_text(json.dumps(out, indent=2, default=str))
        print(f"[P1B/{name}] trades={s['total_trades']} ret={s['total_return_pct']}% "
              f"cagr={s['cagr_pct']}% wr={s['win_rate_pct']}% sharpe={s['sharpe']} "
              f"dd={s['max_dd_pct']}% worstYr={s['worst_year']} exp/tr=${s['expectancy_per_trade']} "
              f"fallback%={s['naive_fallback_share_pct']} stale%={s['stale_mark_day_share_pct']} "
              f"lossRatio={s['max_loss_vs_modeled_ratio']}")
        print(f"  per-year: {py}")
    db.close()


if __name__ == "__main__":
    main()
