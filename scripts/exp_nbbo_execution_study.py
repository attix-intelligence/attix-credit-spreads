#!/usr/bin/env python3
"""
exp_nbbo_execution_study.py — Inside-NBBO Execution Upgrade Backtest

Answers the brief's Step 1 (market_making_1mm_brief): quantify the P&L / Sharpe
uplift from posting INSIDE the NBBO on v8a entries/exits instead of crossing the
spread.

Method (HONEST — Rule Zero):
  - Run the REAL v8a-style CS+SS blend backtest once on IronVault EOD data
    (same engine as scripts/final_validation.py — the validated Sharpe source).
  - The backtester produces gross trade P&L using last-trade leg prices.
  - We then apply three EXECUTION PROFILES as per-contract-per-leg costs, exactly
    matching final_validation.py's slippage convention ($/share x 100):

      cross    (taker, market orders) : entry $0.10/sh, exit $0.15/sh
      baseline (current v8a assumption): entry $0.05/sh, exit $0.10/sh
      nbbo     (proposed upgrade)      : entry $0.02/sh, exit $0.03/sh
               + partial-fill haircut: a fraction of trades miss the passive
                 quote and must cross (modeled as 'unfilled_cross_pct' paying
                 the cross cost instead of the nbbo cost).

  - For each profile we recompute: total net P&L, net return %, annualized
    Sharpe (from daily equity), CAGR, and the uplift of nbbo vs baseline.

  DATA REALITY (documented, not hidden): IronVault EOD cache has NO bid/ask
  (only OHLC trade prints). So the half-spread is a PARAMETER, not measured.
  This is a sensitivity study / upper-bound, NOT proof. The brief's Step 2
  (live <=$100k passive-quote pilot) is required to measure real adverse
  selection / markouts. We print the spread assumptions explicitly.

Usage:
    PYTHONPATH=. python3 scripts/exp_nbbo_execution_study.py
Output:
    output/nbbo_execution_study.json
    reports/nbbo_execution_study.html
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from strategies import STRATEGY_REGISTRY  # noqa: E402
from engine.portfolio_backtester import PortfolioBacktester  # noqa: E402

# Reuse the validated blend config from final_validation.py
from scripts.final_validation import (  # noqa: E402
    build_blend_params, TICKERS, STARTING_CAPITAL, ALL_YEARS,
)

# ── Execution profiles: $/share half-cost per leg (x100 = $/contract/leg) ──
PROFILES = {
    "cross":    {"entry": 0.10, "exit": 0.15, "label": "Cross the spread (taker / market orders)"},
    "baseline": {"entry": 0.05, "exit": 0.10, "label": "Current v8a assumption"},
    "nbbo":     {"entry": 0.02, "exit": 0.03, "label": "Post inside NBBO (proposed upgrade)"},
}
# Fraction of passive (nbbo) quotes that fail to fill and must cross instead.
# Conservative: a meaningful chunk of resting quotes get skipped on EOD-style fills.
UNFILLED_CROSS_PCT = 0.30


def run_full_backtest() -> List:
    """Run the real CS+SS blend across all years; return all closed trades + daily equity."""
    cs_params, ss_params = build_blend_params()
    cs_cls = STRATEGY_REGISTRY["credit_spread"]
    ss_cls = STRATEGY_REGISTRY["straddle_strangle"]

    all_trades = []
    daily_equity = []  # list of (date, equity) across the whole window, base (no exec cost)

    for year in ALL_YEARS:
        bt = PortfolioBacktester(
            strategies=[("credit_spread", cs_cls(dict(cs_params))),
                        ("straddle_strangle", ss_cls(dict(ss_params)))],
            tickers=TICKERS,
            start_date=datetime(year, 1, 1),
            end_date=datetime(year, 12, 31),
            starting_capital=STARTING_CAPITAL,
            max_positions=10,
            max_positions_per_strategy=5,
        )
        bt.run()
        all_trades.extend(bt.closed_trades)
        daily_equity.extend(list(bt.equity_curve))
    return all_trades, daily_equity


def profile_cost(trade, entry_sh: float, exit_sh: float) -> float:
    n_legs = len(trade.legs)
    c = trade.contracts
    return (entry_sh * 100 * c * n_legs) + (exit_sh * 100 * c * n_legs)


def trade_exec_cost(trade, profile_key: str) -> float:
    p = PROFILES[profile_key]
    if profile_key != "nbbo":
        return profile_cost(trade, p["entry"], p["exit"])
    # nbbo: blend passive fills with the unfilled fraction that crosses
    cross = PROFILES["cross"]
    nbbo_cost = profile_cost(trade, p["entry"], p["exit"])
    cross_cost = profile_cost(trade, cross["entry"], cross["exit"])
    return (1 - UNFILLED_CROSS_PCT) * nbbo_cost + UNFILLED_CROSS_PCT * cross_cost


def annualized_sharpe(daily_pnl: np.ndarray, periods: int = 252) -> float:
    if daily_pnl.size < 2:
        return 0.0
    mu = daily_pnl.mean()
    sd = daily_pnl.std(ddof=1)
    if sd == 0:
        return 0.0
    return float(mu / sd * math.sqrt(periods))


def build_daily_returns(daily_equity: List, exec_cost_by_date: Dict) -> np.ndarray:
    """Reconstruct daily returns subtracting per-day execution cost on exit dates."""
    # daily_equity: chronological (date, equity). Convert to daily $ change.
    if not daily_equity:
        return np.array([])
    eq = [(d, float(e)) for d, e in daily_equity]
    eq.sort(key=lambda x: x[0])
    rets = []
    prev = STARTING_CAPITAL
    for d, e in eq:
        change = e - prev
        # subtract exec cost attributed to this date (entry+exit costs booked at exit date)
        key = d.date() if hasattr(d, "date") else d
        change -= exec_cost_by_date.get(key, 0.0)
        rets.append(change / STARTING_CAPITAL)
        prev = e
    return np.array(rets, dtype=float)


def main():
    t0 = datetime.now()
    print("=" * 72)
    print("INSIDE-NBBO EXECUTION UPGRADE STUDY  (v8a CS+SS blend, IronVault EOD)")
    print("=" * 72)
    print("DATA NOTE: EOD cache has NO bid/ask. Half-spread is a PARAMETER.")
    print("This is a sensitivity/upper-bound study, not proof. See Step 2 (live pilot).")
    print(f"Unfilled-passive-cross fraction (nbbo): {UNFILLED_CROSS_PCT:.0%}\n")

    all_trades, daily_equity = run_full_backtest()
    base_pnl = sum(t.realized_pnl for t in all_trades)
    n = len(all_trades)
    print(f"Backtest done: {n} closed trades, gross P&L ${base_pnl:,.0f}, "
          f"{len(daily_equity)} equity points.\n")

    n_years = len(ALL_YEARS)
    results = {}
    for key, p in PROFILES.items():
        # per-date exec cost (book at exit date if present, else entry date)
        cost_by_date = {}
        total_cost = 0.0
        for t in all_trades:
            cost = trade_exec_cost(t, key)
            total_cost += cost
            d = getattr(t, "exit_date", None) or getattr(t, "entry_date", None)
            if d is not None:
                kd = d.date() if hasattr(d, "date") else d
                cost_by_date[kd] = cost_by_date.get(kd, 0.0) + cost

        net_pnl = base_pnl - total_cost
        net_ret_pct = net_pnl / STARTING_CAPITAL * 100
        cagr = ((1 + net_pnl / STARTING_CAPITAL) ** (1 / n_years) - 1) * 100
        daily_rets = build_daily_returns(daily_equity, cost_by_date)
        sharpe = annualized_sharpe(daily_rets)

        results[key] = {
            "label": p["label"],
            "entry_per_share": p["entry"],
            "exit_per_share": p["exit"],
            "total_exec_cost_usd": round(total_cost, 2),
            "exec_drag_pct_capital": round(total_cost / STARTING_CAPITAL * 100, 2),
            "net_pnl_usd": round(net_pnl, 2),
            "net_return_pct": round(net_ret_pct, 2),
            "cagr_pct": round(cagr, 2),
            "sharpe": round(sharpe, 3),
        }
        print(f"  {key:9} {p['label']}")
        print(f"            exec cost ${total_cost:,.0f} ({total_cost/STARTING_CAPITAL*100:.1f}% cap) "
              f"| net ${net_pnl:,.0f} ({net_ret_pct:+.1f}%) | CAGR {cagr:+.1f}% | Sharpe {sharpe:.2f}")

    # Uplift: nbbo vs baseline
    b = results["baseline"]; nb = results["nbbo"]; cr = results["cross"]
    uplift = {
        "net_pnl_gain_usd": round(nb["net_pnl_usd"] - b["net_pnl_usd"], 2),
        "net_return_gain_pct_pts": round(nb["net_return_pct"] - b["net_return_pct"], 2),
        "cagr_gain_pct_pts": round(nb["cagr_pct"] - b["cagr_pct"], 2),
        "sharpe_gain": round(nb["sharpe"] - b["sharpe"], 3),
        "exec_cost_saved_usd": round(b["total_exec_cost_usd"] - nb["total_exec_cost_usd"], 2),
        "vs_cross_net_pnl_gain_usd": round(nb["net_pnl_usd"] - cr["net_pnl_usd"], 2),
    }
    print("\n  UPLIFT (nbbo vs baseline):")
    print(f"    +${uplift['net_pnl_gain_usd']:,.0f} net P&L | "
          f"+{uplift['net_return_gain_pct_pts']:.1f} pts return | "
          f"+{uplift['cagr_gain_pct_pts']:.1f} pts CAGR | +{uplift['sharpe_gain']:.2f} Sharpe")

    out = {
        "generated_at": datetime.now().isoformat(),
        "engine": "PortfolioBacktester CS+SS blend (final_validation config)",
        "data_source": "IronVault options_cache.db EOD (OHLC, NO bid/ask)",
        "honesty_note": ("Half-spread is a parameter, not measured. Sensitivity/upper-bound "
                         "study. Real adverse selection requires live passive-quote pilot (Step 2)."),
        "tickers": TICKERS,
        "years": ALL_YEARS,
        "starting_capital": STARTING_CAPITAL,
        "n_trades": n,
        "gross_pnl_usd": round(base_pnl, 2),
        "unfilled_cross_pct": UNFILLED_CROSS_PCT,
        "profiles": results,
        "uplift_nbbo_vs_baseline": uplift,
        "runtime_sec": round((datetime.now() - t0).total_seconds(), 1),
    }
    outdir = ROOT / "output"; outdir.mkdir(exist_ok=True)
    (outdir / "nbbo_execution_study.json").write_text(json.dumps(out, indent=2))
    write_html(out)
    print(f"\nWrote output/nbbo_execution_study.json and reports/nbbo_execution_study.html")
    print(f"Runtime {out['runtime_sec']}s")


def write_html(out: Dict):
    repdir = ROOT / "reports"; repdir.mkdir(exist_ok=True)
    p = out["profiles"]; u = out["uplift_nbbo_vs_baseline"]
    rows = ""
    for k in ["cross", "baseline", "nbbo"]:
        r = p[k]
        hl = ' style="background:#eaf7ea;font-weight:600"' if k == "nbbo" else ""
        rows += (f"<tr{hl}><td>{k}</td><td>{r['label']}</td>"
                 f"<td>${r['entry_per_share']:.2f}/${r['exit_per_share']:.2f}</td>"
                 f"<td>${r['total_exec_cost_usd']:,.0f}</td>"
                 f"<td>{r['exec_drag_pct_capital']:.1f}%</td>"
                 f"<td>${r['net_pnl_usd']:,.0f}</td>"
                 f"<td>{r['net_return_pct']:+.1f}%</td>"
                 f"<td>{r['cagr_pct']:+.1f}%</td>"
                 f"<td style='color:#999'>{r['sharpe']:.2f}</td></tr>")
    html = f"""<!doctype html><html><head><meta charset=utf-8>
<title>Inside-NBBO Execution Study</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#fff;color:#1a1a1a;max-width:980px;margin:24px auto;padding:0 16px;line-height:1.5}}
h1{{font-size:22px;margin-bottom:4px}} h2{{font-size:16px;margin-top:24px}}
.sub{{color:#666;font-size:13px}}
table{{border-collapse:collapse;width:100%;margin:12px 0;font-size:13px}}
th,td{{border:1px solid #ddd;padding:6px 8px;text-align:right}} th{{background:#f5f5f5}}
td:nth-child(1),td:nth-child(2),th:nth-child(1),th:nth-child(2){{text-align:left}}
.note{{background:#fff8e1;border:1px solid #f0e0a0;padding:10px 12px;border-radius:6px;font-size:13px;margin:12px 0}}
.big{{font-size:18px;font-weight:700;color:#1a7a1a}}
.mono{{font-family:ui-monospace,Menlo,monospace}}
</style></head><body>
<h1>Inside-NBBO Execution Upgrade — Backtest</h1>
<div class="sub">v8a CS+SS blend · IronVault EOD · {out['years'][0]}–{out['years'][-1]} · {out['n_trades']} trades · generated {out['generated_at'][:19]}</div>

<div class="note"><b>Honesty / data reality:</b> {out['honesty_note']}<br>
Half-spread costs below are <b>assumptions</b> (EOD cache has no bid/ask). NBBO profile also pays the full cross cost on {out['unfilled_cross_pct']:.0%} of trades (passive quotes that miss).<br>
<b>Sharpe column is UNRELIABLE</b> and shown greyed: it is reconstructed from a sparse daily equity curve with lumpy exec costs booked on exit dates, which distorts daily volatility. Trust the P&amp;L / return / CAGR / exec-cost columns; ignore Sharpe here. The validated v8a Sharpe (6.39) comes from the standard exit-date P&amp;L convention, not this reconstruction.</div>

<h2>Result</h2>
<p>Gross P&amp;L (pre-execution): <span class="mono">${out['gross_pnl_usd']:,.0f}</span> on ${out['starting_capital']:,} seed.</p>
<table>
<tr><th>Profile</th><th>Meaning</th><th>Entry/Exit $/sh</th><th>Exec cost</th><th>Drag</th><th>Net P&amp;L</th><th>Net ret</th><th>CAGR</th><th style="color:#999">Sharpe*</th></tr>
{rows}
</table>

<h2>Uplift — posting inside NBBO vs current baseline</h2>
<p class="big">+${u['net_pnl_gain_usd']:,.0f} net P&amp;L &nbsp;·&nbsp; +{u['net_return_gain_pct_pts']:.1f} pts return &nbsp;·&nbsp; +{u['cagr_gain_pct_pts']:.1f} pts CAGR</p>
<p class="sub">*Sharpe excluded from the headline — unreliable in this reconstruction (see note).</p>
<p class="sub">Execution cost saved vs baseline: ${u['exec_cost_saved_usd']:,.0f}. Vs crossing the spread (taker): +${u['vs_cross_net_pnl_gain_usd']:,.0f}.</p>

<h2>What this does and does not prove</h2>
<ul>
<li><b>Does:</b> bounds the P&amp;L sensitivity of v8a to execution quality; shows the spread we pay is a material, recoverable cost.</li>
<li><b>Does not:</b> measure real fill probability or adverse selection — EOD data can't. The {out['unfilled_cross_pct']:.0%} unfilled haircut is a guess.</li>
<li><b>Next (brief Step 2):</b> ring-fenced live ≤$100k passive-quote pilot on XLF/XLI/SLV to measure true markouts; then buy 1-min/OPRA NBBO before trusting any MM backtest.</li>
</ul>
</body></html>"""
    (repdir / "nbbo_execution_study.html").write_text(html)


if __name__ == "__main__":
    main()
