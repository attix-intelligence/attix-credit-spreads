#!/usr/bin/env python3
"""EXP-P2B — event-premium harvesting (prereg: EXP-P2B_PREREG.md).

Iron flies around scheduled FOMC/CPI/NFP events on the shared multi-leg
harness. 2020-01-02 -> 2024-12-31, marketable only, holdout seal enforced.

Usage: .venv/bin/python experiments/wave2/run_p2b.py [E1_SPY_all_gated ...]
"""
from __future__ import annotations

import csv
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
    Leg, MarksDB, net_mark, run_portfolio, stop_loss, time_stop,
)

DB = ROOT / "data" / "options_cache.db"
CAL = ROOT / "compass" / "orchestrator" / "calendars"
RISK_DOLLARS = 2_500.0
MAX_CONTRACTS = 25
MAX_POSITIONS = 2
RICHNESS_MIN = 1.25
WING_PCT = 0.02

VARIANTS = {
    "E1_SPY_all_gated":  {"ticker": "SPY", "events": ("fomc", "cpi", "nfp"), "gated": True},
    "E2_SPY_all_uncond": {"ticker": "SPY", "events": ("fomc", "cpi", "nfp"), "gated": False},
    "E3_QQQ_all_gated":  {"ticker": "QQQ", "events": ("fomc", "cpi", "nfp"), "gated": True},
    "E4_SPY_fomc_gated": {"ticker": "SPY", "events": ("fomc",), "gated": True},
    "E5_SPY_cpi_gated":  {"ticker": "SPY", "events": ("cpi",), "gated": True},
    "E6_SPY_nfp_gated":  {"ticker": "SPY", "events": ("nfp",), "gated": True},
}


# ── event calendar (scheduled only) ──────────────────────────────────────────

def _csv_dates(name: str) -> list[tuple[date, str]]:
    out = []
    with open(CAL / name) as fh:
        for row in csv.DictReader(r for r in fh if not r.startswith("#")):
            if "UNSCHEDULED" in (row.get("notes") or "").upper():
                continue
            out.append((date.fromisoformat(row["date"].strip()), row.get("notes", "")))
    return out


def _first_friday(y: int, m: int) -> date:
    d = date(y, m, 1)
    return d + timedelta(days=(4 - d.weekday()) % 7)


def _nfp(y: int, m: int) -> date:
    d = _first_friday(y, m)
    if d.month == 1 and d.day == 1:
        return d + timedelta(days=7)
    if d.month == 7 and d.day in (3, 4):
        return d - timedelta(days=1)
    return d


def build_events(kinds: tuple) -> list[tuple[date, str]]:
    ev: list[tuple[date, str]] = []
    if "fomc" in kinds:
        ev += [(d, "fomc") for d, _ in _csv_dates("fomc_2020_2025.csv")]
    if "cpi" in kinds:
        ev += [(d, "cpi") for d, _ in _csv_dates("cpi_2020_2025.csv")]
    if "nfp" in kinds:
        ev += [(_nfp(y, m), "nfp") for y in range(2020, 2025) for m in range(1, 13)]
    lo, hi = date.fromisoformat(WINDOW[0]), date.fromisoformat(WINDOW[1])
    return sorted((d, k) for d, k in ev if lo <= d <= hi)


# ── underlier closes (real Polygon loader, cache-backed) ─────────────────────

def underlier_closes(ticker: str) -> dict[str, float]:
    for line in (ROOT / ".env.expv8a").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip().strip('"'))
    from backtest.market_history import load_market_history
    df = load_market_history(ticker, datetime(2019, 10, 1), datetime(2024, 12, 31))
    return {d.strftime("%Y-%m-%d"): float(r["Close"]) for d, r in df.iterrows()}


# ── structure selection ──────────────────────────────────────────────────────

def pick_fly(db: MarksDB, ticker: str, entry_day: str, event: date, spot: float):
    lo = (event + timedelta(days=1)).isoformat()
    hi = (event + timedelta(days=10)).isoformat()
    exps = db.expirations(ticker, lo, hi)
    if not exps:
        return None
    exp = exps[0]
    calls = db.strikes(ticker, exp, "C")
    puts = db.strikes(ticker, exp, "P")
    both = sorted(set(calls) & set(puts))
    if not both:
        return None
    atm = min(both, key=lambda s: abs(s - spot))
    wing_up = min(calls, key=lambda s: abs(s - spot * (1 + WING_PCT)))
    wing_dn = min(puts, key=lambda s: abs(s - spot * (1 - WING_PCT)))
    if not (wing_dn < atm < wing_up):
        return None
    syms = {
        "sc": db.contract(ticker, exp, atm, "C"),
        "sp": db.contract(ticker, exp, atm, "P"),
        "lc": db.contract(ticker, exp, wing_up, "C"),
        "lp": db.contract(ticker, exp, wing_dn, "P"),
    }
    if any(v is None for v in syms.values()):
        return None
    legs = [Leg(syms["sc"], -1, 1, exp), Leg(syms["sp"], -1, 1, exp),
            Leg(syms["lc"], +1, 1, exp), Leg(syms["lp"], +1, 1, exp)]
    return legs, exp, atm, wing_up, wing_dn


def straddle_close(db: MarksDB, ticker: str, day: str, event: date, spot: float):
    """ATM straddle close mark on the front post-event expiry (richness numerator)."""
    sel = pick_fly(db, ticker, day, event, spot)
    if sel is None:
        return None
    legs = sel[0][:2]  # the two short legs = the straddle
    val, complete, _ = net_mark(db, legs, day, "close")
    return val if (val is not None and complete) else None  # premium received = straddle price


def make_signal(db, v, days, events, closes, stats):
    ticker = v["ticker"]
    day_index = {d: i for i, d in enumerate(days)}
    entry_days = {}
    for ev_date, kind in events:
        prior = [d for d in days if d < ev_date.isoformat()]
        if prior:
            entry_days.setdefault(prior[-1], []).append((ev_date, kind))

    def signal(day, _db, open_positions):
        cands = []
        for ev_date, kind in entry_days.get(day, []):
            stats["events_seen"] += 1
            spot = closes.get(day)
            if spot is None:
                continue
            # richness R = (straddle/spot) / trailing mean |daily ret| (21d)
            i = day_index[day]
            rets = []
            for j in range(max(1, i - 21), i):
                a, b = closes.get(days[j - 1]), closes.get(days[j])
                if a and b:
                    rets.append(abs(b / a - 1))
            strad = straddle_close(db, ticker, day, ev_date, spot)
            if strad is None or not rets:
                stats["no_quote"] += 1
                continue
            r = (strad / spot) / (sum(rets) / len(rets))
            stats["richness"].append(round(r, 3))
            if v["gated"] and r < RICHNESS_MIN:
                stats["gate_rejected"] += 1
                continue
            sel = pick_fly(db, ticker, day, ev_date, spot)
            if sel is None:
                continue
            legs, exp, atm, wu, wd = sel
            open_net, complete, _ = net_mark(db, legs, day, "open")
            if open_net is None or not complete or open_net <= 0:
                continue
            wing = min(wu - atm, atm - wd)
            max_loss_1x = (wing - open_net) * 100
            if max_loss_1x <= 0:
                continue
            contracts = max(1, min(MAX_CONTRACTS, int(RISK_DOLLARS // max_loss_1x)))
            cands.append((legs, contracts,
                          {"event": ev_date.isoformat(), "kind": kind, "richness": round(r, 3),
                           "expiry": exp, "atm": atm, "wings": [wd, wu],
                           "modeled_max_loss_1x": round(max_loss_1x / 100, 4)}))
        return cands

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


def main() -> None:
    names = sys.argv[1:] or list(VARIANTS)
    db = MarksDB(DB)
    closes_cache: dict[str, dict] = {}
    for name in names:
        v = VARIANTS[name]
        t = v["ticker"]
        closes = closes_cache.setdefault(t, underlier_closes(t))
        days = db.trading_days(t, *WINDOW)
        events = build_events(v["events"])
        stats = {"events_seen": 0, "gate_rejected": 0, "no_quote": 0, "richness": []}
        res = run_portfolio(
            db, days, make_signal(db, v, days, events, closes, stats),
            exit_rules=[stop_loss(2.5), time_stop(2)],
            starting_capital=100_000.0, fill_model="marketable",
            max_positions=MAX_POSITIONS,
        )
        s = res.summary(100_000.0)
        py = per_year(res.equity_curve)
        s["worst_year"] = min(py.values()) if py else None
        s["expectancy_per_trade"] = round(
            sum(tr["pnl"] for tr in res.trades) / len(res.trades), 2) if res.trades else 0.0
        credits = sorted(tr["entry_net"] * 100 for tr in res.trades)
        s["median_credit_usd"] = round(credits[len(credits) // 2], 2) if credits else None
        adm = stats["events_seen"] - stats["gate_rejected"] - stats["no_quote"]
        s["events_seen"] = stats["events_seen"]
        s["events_admitted_pct"] = round(adm / stats["events_seen"] * 100, 1) if stats["events_seen"] else None
        s["gate_rejected"] = stats["gate_rejected"]
        s["no_quote"] = stats["no_quote"]
        out = {"experiment": "EXP-P2B", "variant": name, "spec": {k: v[k] for k in ("ticker", "events", "gated")},
               "window": list(WINDOW), "fill_model": "marketable",
               "summary": s, "per_year": py, "richness_dist": stats["richness"],
               "equity_curve": res.equity_curve, "trades": res.trades}
        (OUT / f"p2b_{name}.json").write_text(json.dumps(out, indent=2, default=str))
        print(f"[P2B/{name}] trades={s['total_trades']} ret={s['total_return_pct']}% "
              f"wr={s['win_rate_pct']}% sharpe={s['sharpe']} dd={s['max_dd_pct']}% "
              f"worstYr={s['worst_year']} exp/tr=${s['expectancy_per_trade']} "
              f"medCredit=${s['median_credit_usd']} admitted={s['events_admitted_pct']}% "
              f"gateRej={s['gate_rejected']} fallback%={s['naive_fallback_share_pct']}")
        print(f"  per-year: {py}")
    db.close()


if __name__ == "__main__":
    main()
