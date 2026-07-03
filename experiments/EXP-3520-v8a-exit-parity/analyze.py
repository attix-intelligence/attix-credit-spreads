#!/usr/bin/env python3
"""EXP-3520 step 2 — exit-parity A/B analysis.

Reads results/{TICKER}_{arm}.json produced by run_arms.py and reports:
  - per-ticker metrics table (trades, return, Sharpe, MaxDD, exit reasons)
  - equal-weight 3-stream portfolio equity per arm (proxy for the live
    multi-stream book) and its MaxDD
  - drawdown inside stress windows chosen from REAL VIX (EXP-3510 backfill):
    the top VIX episodes of 2020-2026 plus the June-like low-VIX dip regime
  - the A/B verdict against the pre-registered gate:
    mechanism CONFIRMED if MaxDD(exits_off) >= 2x MaxDD(exits_on) in >=3 of
    the 5 stress windows (portfolio level), else NOT CONFIRMED.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
RES = HERE / "results"
TICKERS = ["SPY", "XLF", "XLI"]
ARMS = ["exits_on", "exits_off"]

# Stress windows: episodes of elevated realized VIX within 2020-01..2026-04
# (identified from the EXP-3510-backfilled real VIX series) plus the two
# 2026 dip regimes. Dates are calendar bounds; DD is computed inside each.
WINDOWS = {
    "covid_2020": ("2020-02-14", "2020-04-30"),      # VIX 82.7 peak
    "bear_2022H1": ("2022-01-01", "2022-06-30"),     # VIX 30-36 grind
    "bear_2022H2": ("2022-08-15", "2022-10-31"),     # VIX ~33 October leg
    "aug_2024": ("2024-07-15", "2024-08-30"),        # VIX 38.6 spike (Aug 5)
    "apr_2025": ("2025-03-15", "2025-05-15"),        # 2025 spring episode
    "q1_2026_dip": ("2026-02-01", "2026-04-01"),     # VIX ~25-30, June-like leverage test
}


def equity_series(path: Path) -> pd.Series:
    d = json.load(open(path))
    eq = pd.Series({pd.Timestamp(t[:10]): v for t, v in d["equity_curve"]}).sort_index()
    return eq


def max_dd(eq: pd.Series) -> float:
    if eq.empty:
        return 0.0
    peak = eq.cummax()
    return float(((eq / peak) - 1.0).min() * 100)


def window_dd(eq: pd.Series, lo: str, hi: str) -> float:
    sl = eq.loc[lo:hi]
    return max_dd(sl) if len(sl) > 2 else float("nan")


def main() -> None:
    conn = sqlite3.connect(f"file:{ROOT/'data'/'historical_indices.sqlite'}?mode=ro", uri=True)
    vix = pd.read_sql_query(
        "SELECT date, close FROM historical_indices WHERE ticker='I:VIX' ORDER BY date",
        conn,
    ).set_index("date")["close"]
    conn.close()

    report = {"experiment": "EXP-3520", "windows": {}, "tickers": {}, "portfolio": {}}
    eqs = {}
    print(f"{'ticker':6} {'arm':10} {'trades':>6} {'return%':>9} {'sharpe':>7} {'maxDD%':>8}  exits")
    for t in TICKERS:
        report["tickers"][t] = {}
        for a in ARMS:
            p = RES / f"{t}_{a}.json"
            if not p.exists():
                print(f"{t:6} {a:10}  MISSING"); continue
            d = json.load(open(p))
            m = d["metrics"]
            eqs[(t, a)] = equity_series(p)
            report["tickers"][t][a] = {**m, "exit_reasons": d["exit_reasons"]}
            print(f"{t:6} {a:10} {m['total_trades']:>6} {m['return_pct']:>9} "
                  f"{m['sharpe_ratio']:>7} {m['max_drawdown']:>8}  {d['exit_reasons']}")

    # Equal-weight 3-stream portfolio: mean of per-ticker equity indexed to 1.0
    print("\nPortfolio (equal-weight 3 streams):")
    port = {}
    for a in ARMS:
        norm = [eqs[(t, a)] / eqs[(t, a)].iloc[0] for t in TICKERS if (t, a) in eqs]
        if not norm:
            continue
        df = pd.concat(norm, axis=1).ffill().dropna()
        p_eq = df.mean(axis=1)
        port[a] = p_eq
        ret = (p_eq.iloc[-1] / p_eq.iloc[0] - 1) * 100
        dly = p_eq.pct_change().dropna()
        sharpe = (dly.mean() / dly.std() * (252 ** 0.5)) if dly.std() > 0 else 0.0
        report["portfolio"][a] = {
            "return_pct": round(float(ret), 2),
            "sharpe": round(float(sharpe), 2),
            "max_dd_pct": round(max_dd(p_eq), 2),
        }
        print(f"  {a:10} return={ret:+.2f}%  sharpe={sharpe:.2f}  maxDD={max_dd(p_eq):.2f}%")

    print(f"\nStress-window portfolio drawdowns (real VIX from EXP-3510 backfill):")
    print(f"{'window':14} {'VIXmax':>7} {'DD exits_on':>12} {'DD exits_off':>13} {'ratio':>6}")
    confirms = 0
    judged = 0
    for name, (lo, hi) in WINDOWS.items():
        vmax = float(vix.loc[lo:hi].max()) if len(vix.loc[lo:hi]) else float("nan")
        dd_on = window_dd(port["exits_on"], lo, hi)
        dd_off = window_dd(port["exits_off"], lo, hi)
        ratio = (dd_off / dd_on) if dd_on < -0.01 else float("nan")
        report["windows"][name] = {"bounds": [lo, hi], "vix_max": round(vmax, 1),
                                    "dd_exits_on_pct": round(dd_on, 2),
                                    "dd_exits_off_pct": round(dd_off, 2),
                                    "ratio_off_over_on": round(ratio, 2) if ratio == ratio else None}
        if name != "q1_2026_dip":  # gate counts the 5 historical stress windows
            judged += 1
            if ratio == ratio and ratio >= 2.0:
                confirms += 1
        print(f"{name:14} {vmax:>7.1f} {dd_on:>11.2f}% {dd_off:>12.2f}% {ratio:>6.2f}")

    verdict = "CONFIRMED" if confirms >= 3 else "NOT CONFIRMED"
    report["gate"] = {"rule": "MaxDD(exits_off) >= 2x MaxDD(exits_on) in >=3 of 5 stress windows",
                      "windows_confirming": confirms, "windows_judged": judged, "verdict": verdict}
    print(f"\nGATE: {confirms}/{judged} stress windows with DD ratio >= 2x -> mechanism {verdict}")

    with open(RES / "analysis.json", "w") as f:
        json.dump(report, f, indent=2)
    print(f"wrote {RES/'analysis.json'}")


if __name__ == "__main__":
    main()
