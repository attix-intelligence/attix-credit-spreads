#!/usr/bin/env python3
"""Aggregate the 4 EXP-V8A per-stream honest-fill backtests into a portfolio
approximation, per fill model.

METHOD (documented, deliberately simple — NOT the live allocator):
  - Each stream backtest runs on its own $100k with flat 5% per-trade risk.
  - Stream daily returns are computed from each equity curve (dates aligned
    on the union calendar, equity forward-filled across per-ticker gaps).
  - Portfolio daily return = sum(w_i * r_i) with FIXED weights, rebalanced
    daily: the EXP-2600 equal-risk v8a baseline weights
    (compass/exp2690_signal_generators.py PORTFOLIO_WEIGHTS) renormalized
    over the 4 live credit-spread streams:
        exp1220 0.316, xlf_cs 0.245, xli_cs 0.192, qqq_cs 0.100
        -> /0.853 -> 0.3705 / 0.2872 / 0.2251 / 0.1172
  - The LIVE allocator (Ledoit-Wolf risk parity + 12% vol target +
    dollar-notional sizing) is NOT replicated — it consumes live covariance
    estimates and has no offline twin. Fixed-weight daily rebalancing is the
    closest static approximation and is identical across fill models, so the
    naive-vs-marketable delta is attributable to fills only.
  - Trades / win_rate are pooled across streams; pct_unfillable is
    1 - marketable_trades/naive_trades (trade-count basis) plus the raw
    per-slot rejection counters.

Usage:  .venv/bin/python experiments/EXP-V8A-BT-honest-fills/aggregate.py
Writes: results/portfolio_{naive,marketable}.json
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = HERE / "results"

WEIGHTS_RAW = {"exp1220": 0.316, "xlf_cs": 0.245, "xli_cs": 0.192, "qqq_cs": 0.100}
_tot = sum(WEIGHTS_RAW.values())
WEIGHTS = {k: v / _tot for k, v in WEIGHTS_RAW.items()}


def portfolio_metrics(fill_model: str) -> dict:
    import pandas as pd

    streams = {}
    for s in WEIGHTS:
        p = RES / f"{s}_{fill_model}.json"
        if not p.exists():
            raise SystemExit(f"missing {p} — run run_stream.py {s} {fill_model} first")
        streams[s] = json.loads(p.read_text())

    curves = {}
    for s, data in streams.items():
        pts = data["equity_curve"]
        ser = pd.Series({pd.Timestamp(d): v for d, v in pts}).sort_index()
        curves[s] = ser
    df = pd.DataFrame(curves).ffill().dropna()
    rets = df.pct_change().fillna(0.0)
    port_ret = sum(WEIGHTS[s] * rets[s] for s in WEIGHTS)
    equity = 100000 * (1 + port_ret).cumprod()

    total_return = float(equity.iloc[-1] / 100000 - 1) * 100
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    cagr = ((equity.iloc[-1] / 100000) ** (1 / years) - 1) * 100 if equity.iloc[-1] > 0 else -100.0
    daily = port_ret
    sharpe = float(daily.mean() / daily.std() * math.sqrt(252)) if daily.std() > 0 else 0.0
    dd = (equity / equity.cummax() - 1).min() * 100

    trades = sum(d["metrics"]["total_trades"] for d in streams.values())
    wins = sum(d["metrics"]["total_trades"] * d["metrics"]["win_rate"] / 100
               for d in streams.values())
    win_rate = wins / trades * 100 if trades else 0.0
    rejects = sum(d["unfilled_entries"] for d in streams.values())
    fallbacks = sum(d["fill_model_naive_fallbacks"] for d in streams.values())

    return {
        "fill_model": fill_model,
        "weights": WEIGHTS,
        "window": streams["exp1220"]["window"],
        "trades": trades,
        "total_return_pct": round(total_return, 2),
        "cagr_pct": round(cagr, 2),
        "win_rate_pct": round(win_rate, 2),
        "sharpe": round(sharpe, 2),
        "max_dd_pct": round(float(dd), 2),
        "unfilled_entry_rejections_raw": rejects,
        "fill_model_naive_fallbacks": fallbacks,
        "per_stream": {
            s: {
                "trades": d["metrics"]["total_trades"],
                "total_return_pct": d["metrics"]["return_pct"],
                "sharpe": d["metrics"]["sharpe_ratio"],
                "max_dd_pct": d["metrics"]["max_drawdown_pct"],
                "win_rate_pct": d["metrics"]["win_rate"],
                "unfilled_rejections": d["unfilled_entries"],
                "naive_fallbacks": d["fill_model_naive_fallbacks"],
            } for s, d in streams.items()
        },
        "equity_curve": [(d.date().isoformat(), round(float(v), 2))
                         for d, v in equity.items()],
    }


def main() -> None:
    out = {}
    for fm in ("naive", "marketable"):
        m = portfolio_metrics(fm)
        (RES / f"portfolio_{fm}.json").write_text(json.dumps(m, indent=2))
        out[fm] = m
        print(f"[EXP-V8A-BT/portfolio/{fm}] trades={m['trades']} "
              f"total={m['total_return_pct']}% cagr={m['cagr_pct']}% "
              f"sharpe={m['sharpe']} maxDD={m['max_dd_pct']}% "
              f"winrate={m['win_rate_pct']}% rejects={m['unfilled_entry_rejections_raw']}")
    n, mk = out["naive"], out["marketable"]
    if n["trades"]:
        print(f"pct_unfillable (trade basis): {(1 - mk['trades']/n['trades'])*100:.1f}%")


if __name__ == "__main__":
    main()
