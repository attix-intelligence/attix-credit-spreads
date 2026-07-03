#!/usr/bin/env python3
"""EXP-3550 — analysis: winner selection + ship gate.

Protocol (fixed before looking at test-period results), mirroring EXP-3540:
  - Portfolio = equal-weight sum of SPY/XLF/XLI equity curves (ffill, union days).
  - TRAIN (selection) 2020-01-02..2023-12-31; winner = best train Calmar of
    the 6 configs. TEST (untouched) 2024-01-01..2026-04-01.
  - Ship gate: test MaxDD <= 10% AND test CAGR >= 70% of the live-like
    unprotected baseline (EXP-3540 s215_doff_eoff portfolio, reused) AND
    rank-stable = top-3-of-6 Calmar in BOTH periods (top half of field,
    analog of EXP-3540's top-5-of-18).
  - Secondary (hypothesis vs EXP-3540): rank in the combined 24-config
    universe (18 EXP-3540 core cells + 6 EXP-3550 configs); hypothesis
    supported if a vol-target cell is top-5 combined in BOTH periods.
"""
import json
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = HERE / "results"
RES3540 = HERE.parent / "EXP-3540-protection-grid" / "results"
TICKERS = ["SPY", "XLF", "XLI"]
TRAIN = (date(2020, 1, 2), date(2023, 12, 31))
TEST = (date(2024, 1, 1), date(2026, 4, 1))
SPIKES = {
    "covid_2020": (date(2020, 2, 15), date(2020, 4, 30)),
    "bear_2022": (date(2022, 1, 1), date(2022, 12, 31)),
    "aug_2024_vix": (date(2024, 7, 15), date(2024, 8, 30)),
    "apr_2025_tariff": (date(2025, 3, 15), date(2025, 5, 15)),
}
CELLS = [f"vt{t}_{b}" for t in ("08", "12", "16") for b in ("foff", "fon")]
CELLS3540 = [f"{s}_{d}_{e}" for s in ("s215", "s100")
             for d in ("doff", "d81012", "d479") for e in ("eoff", "enfp", "enf")]
BASELINE = "s215_doff_eoff"


def load_curve(resdir, ticker, cell):
    j = json.load(open(resdir / f"{ticker}_{cell}.json"))
    return {date.fromisoformat(d[:10]): v for d, v in j["equity_curve"]}, j


def portfolio_curve(resdir, cell):
    curves = [load_curve(resdir, t, cell)[0] for t in TICKERS]
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
    return {"cagr": g, "maxdd": m, "calmar": calmar, "start": c[0][1], "end": c[-1][1]}


def evaluate(resdir, cell):
    pc = portfolio_curve(resdir, cell)
    r = {"train": perf(pc, *TRAIN), "test": perf(pc, *TEST),
         "full": perf(pc, TRAIN[0], TEST[1]),
         "spikes": {n: maxdd(slice_curve(pc, a, b)) for n, (a, b) in SPIKES.items()}}
    return r


def main():
    rows = {c: evaluate(RES, c) for c in CELLS}
    for c in CELLS:  # per-ticker detail
        rows[c]["tickers"] = {}
        for t in TICKERS:
            _, j = load_curve(RES, t, c)
            rows[c]["tickers"][t] = {"metrics": j["metrics"],
                                     "eff_risk_pct_stats": j["eff_risk_pct_stats"],
                                     "exit_reasons": j["exit_reasons"]}
    base = evaluate(RES3540, BASELINE)

    rank_train = sorted(CELLS, key=lambda c: -rows[c]["train"]["calmar"])
    rank_test = sorted(CELLS, key=lambda c: -rows[c]["test"]["calmar"])
    winner = rank_train[0]

    gates = {}
    for c in CELLS:
        g_dd = rows[c]["test"]["maxdd"] >= -10.0
        g_cagr = rows[c]["test"]["cagr"] >= 0.7 * base["test"]["cagr"]
        g_rank = c in rank_train[:3] and c in rank_test[:3]
        gates[c] = {"dd_le_10": g_dd, "cagr_ge_70pct_livelike": g_cagr,
                    "rank_stable_top3of6": g_rank, "pass": g_dd and g_cagr and g_rank}

    # combined 24-config universe (secondary, hypothesis vs EXP-3540)
    combo = dict(rows)
    for c in CELLS3540:
        combo[f"3540:{c}"] = evaluate(RES3540, c)
    ctr = sorted(combo, key=lambda c: -combo[c]["train"]["calmar"])
    cte = sorted(combo, key=lambda c: -combo[c]["test"]["calmar"])
    combined_stable_top5 = [c for c in combo if c in ctr[:5] and c in cte[:5]]

    out = {"winner_train_calmar": winner, "rank_train": rank_train, "rank_test": rank_test,
           "baseline": {"cell": BASELINE, **{k: base[k] for k in ("train", "test", "full")}},
           "gates": gates, "rows": rows,
           "combined_rank_train_top8": ctr[:8], "combined_rank_test_top8": cte[:8],
           "combined_rank_stable_top5": combined_stable_top5}
    with open(HERE / "analysis.json", "w") as f:
        json.dump(out, f, indent=2, default=str)

    hdr = f"{'cell':12s} {'trCAGR':>7s} {'trDD':>7s} {'trCal':>6s} | {'teCAGR':>7s} {'teDD':>7s} {'teCal':>6s} | {'aug24':>6s} {'apr25':>6s} | gate"
    print(hdr)
    print("-" * len(hdr))
    for c in rank_train:
        r, g = rows[c], gates[c]
        flag = "PASS" if g["pass"] else "".join(
            x for x, ok in (("D", g["dd_le_10"]), ("C", g["cagr_ge_70pct_livelike"]),
                            ("R", g["rank_stable_top3of6"])) if ok)
        print(f"{c:12s} {r['train']['cagr']:7.1f} {r['train']['maxdd']:7.1f} {r['train']['calmar']:6.2f} | "
              f"{r['test']['cagr']:7.1f} {r['test']['maxdd']:7.1f} {r['test']['calmar']:6.2f} | "
              f"{r['spikes']['aug_2024_vix']:6.1f} {r['spikes']['apr_2025_tariff']:6.1f} | {flag}")
    b = base
    print(f"{'BASE '+BASELINE:12s} {b['train']['cagr']:7.1f} {b['train']['maxdd']:7.1f} {b['train']['calmar']:6.2f} | "
          f"{b['test']['cagr']:7.1f} {b['test']['maxdd']:7.1f} {b['test']['calmar']:6.2f}")
    print(f"\nWinner (train Calmar): {winner}  |  gate: {gates[winner]}")
    print(f"Combined-24 train top8: {ctr[:8]}")
    print(f"Combined-24 test  top8: {cte[:8]}")
    print(f"Combined-24 rank-stable top5 both periods: {combined_stable_top5}")


if __name__ == "__main__":
    main()
