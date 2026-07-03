#!/usr/bin/env python3
"""EXP-3540 — grid analysis: winner selection + ship gate.

Protocol (fixed before looking at test-period results):
  - Portfolio = equal-weight sum of the three per-ticker equity curves
    (SPY, XLF, XLI), forward-filled on the union of trading days. This
    mirrors live V8A running parallel per-ticker streams off one NAV.
  - TRAIN (selection): 2020-01-02 .. 2023-12-31. Winner = best train
    Calmar (CAGR / |MaxDD|) among the 18 core cells (v30 reference cell
    excluded from selection, reported alongside).
  - TEST (untouched validation): 2024-01-01 .. 2026-04-01.
  - Ship gate (registry.json notes): test-period portfolio MaxDD <= 10%
    AND test CAGR >= 70% of the same-sizing unprotected baseline's test
    CAGR (baseline = s{X}_doff_eoff) AND rank-stable: top-5 portfolio
    Calmar in BOTH periods (train half and test half).
  - Spike windows (reported, per user's 'spike-window MaxDD' phrasing):
    COVID 2020-02-15..2020-04-30 (train), 2022 bear full year (train),
    Aug-2024 VIX spike 2024-07-15..2024-08-30 (test),
    Apr-2025 tariff spike 2025-03-15..2025-05-15 (test).
"""
import json
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
TICKERS = ["SPY", "XLF", "XLI"]
TRAIN = (date(2020, 1, 2), date(2023, 12, 31))
TEST = (date(2024, 1, 1), date(2026, 4, 1))
SPIKES = {
    "covid_2020": (date(2020, 2, 15), date(2020, 4, 30)),
    "bear_2022": (date(2022, 1, 1), date(2022, 12, 31)),
    "aug_2024_vix": (date(2024, 7, 15), date(2024, 8, 30)),
    "apr_2025_tariff": (date(2025, 3, 15), date(2025, 5, 15)),
}
S = ["s215", "s100"]
D = ["doff", "d81012", "d479"]
E = ["eoff", "enfp", "enf"]
CELLS = [f"{s}_{d}_{e}" for s in S for d in D for e in E]
V30 = "s215_doff_eoff_v30"


def load_curve(ticker, cell):
    j = json.load(open(RES / f"{ticker}_{cell}.json"))
    return {date.fromisoformat(d[:10]): v for d, v in j["equity_curve"]}, j


def portfolio_curve(cell):
    curves = [load_curve(t, cell)[0] for t in TICKERS]
    days = sorted(set().union(*curves))
    out, last = [], [None] * 3
    for day in days:
        for i, c in enumerate(curves):
            last[i] = c.get(day, last[i] if last[i] is not None else 100000.0)
        out.append((day, sum(last)))
    return out


def slice_curve(curve, a, b):
    return [(d, v) for d, v in curve if a <= d <= b]


def maxdd(curve):
    hwm, worst = float("-inf"), 0.0
    for _, v in curve:
        hwm = max(hwm, v)
        worst = min(worst, v / hwm - 1.0)
    return worst * 100.0


def cagr(curve):
    (d0, v0), (d1, v1) = curve[0], curve[-1]
    years = (d1 - d0).days / 365.25
    if years <= 0 or v0 <= 0 or v1 <= 0:
        return float("nan")
    return ((v1 / v0) ** (1 / years) - 1.0) * 100.0


def perf(curve, a, b):
    c = slice_curve(curve, a, b)
    g, m = cagr(c), maxdd(c)
    calmar = g / abs(m) if m < -0.01 else (float("inf") if g > 0 else 0.0)
    return {"cagr": g, "maxdd": m, "calmar": calmar,
            "start": c[0][1], "end": c[-1][1]}


def main():
    rows = {}
    for cell in CELLS + [V30]:
        pc = portfolio_curve(cell)
        r = {"train": perf(pc, *TRAIN), "test": perf(pc, *TEST),
             "full": perf(pc, TRAIN[0], TEST[1]), "spikes": {}}
        for name, (a, b) in SPIKES.items():
            r["spikes"][name] = maxdd(slice_curve(pc, a, b))
        # per-ticker breaker/trade info
        r["tickers"] = {}
        for t in TICKERS:
            _, j = load_curve(t, cell)
            r["tickers"][t] = {"metrics": j["metrics"],
                               "n_breaker_events": len(j["breaker_events"]),
                               "breaker_events": j["breaker_events"],
                               "exit_reasons": j["exit_reasons"]}
        rows[cell] = r

    core = {c: rows[c] for c in CELLS}
    rank_train = sorted(core, key=lambda c: -core[c]["train"]["calmar"])
    rank_test = sorted(core, key=lambda c: -core[c]["test"]["calmar"])
    winner = rank_train[0]

    gates = {}
    for c in CELLS:
        base = f"{c.split('_')[0]}_doff_eoff"
        bt_cagr = core[base]["test"]["cagr"]
        g_dd = core[c]["test"]["maxdd"] >= -10.0
        g_cagr = core[c]["test"]["cagr"] >= 0.7 * bt_cagr
        g_rank = c in rank_train[:5] and c in rank_test[:5]
        gates[c] = {"dd_le_10": g_dd, "cagr_ge_70pct_base": g_cagr,
                    "rank_stable_top5": g_rank,
                    "pass": g_dd and g_cagr and g_rank,
                    "baseline": base, "baseline_test_cagr": bt_cagr}

    out = {"winner_train_calmar": winner,
           "rank_train": rank_train, "rank_test": rank_test,
           "gates": gates, "rows": rows}
    with open(HERE / "analysis.json", "w") as f:
        json.dump(out, f, indent=2, default=str)

    hdr = f"{'cell':22s} {'trCAGR':>7s} {'trDD':>7s} {'trCal':>6s} | {'teCAGR':>7s} {'teDD':>7s} {'teCal':>6s} | {'aug24':>6s} {'apr25':>6s} | gate"
    print(hdr)
    print("-" * len(hdr))
    for c in rank_train + [V30]:
        r = rows[c]
        g = gates.get(c, {})
        flag = "PASS" if g.get("pass") else ("ref" if c == V30 else
               "".join(x[0] for x, ok in
                       [("D", g.get("dd_le_10")), ("C", g.get("cagr_ge_70pct_base")), ("R", g.get("rank_stable_top5"))] if ok))
        print(f"{c:22s} {r['train']['cagr']:7.1f} {r['train']['maxdd']:7.1f} {r['train']['calmar']:6.2f} | "
              f"{r['test']['cagr']:7.1f} {r['test']['maxdd']:7.1f} {r['test']['calmar']:6.2f} | "
              f"{r['spikes']['aug_2024_vix']:6.1f} {r['spikes']['apr_2025_tariff']:6.1f} | {flag}")
    print(f"\nWinner (train Calmar): {winner}")
    print(f"Gate result: {gates[winner]}")


if __name__ == "__main__":
    main()
