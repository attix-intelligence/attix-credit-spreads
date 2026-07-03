#!/usr/bin/env python3
"""
exp_nbbo_real_quotes.py — Inside-NBBO study with REAL historical option quotes.

Upgrade over exp_nbbo_execution_study.py: instead of ASSUMING a half-spread,
we look up the ACTUAL NBBO (bid/ask) for every traded leg at entry and exit
from Polygon /v3/quotes (POLYGON_API_KEY, history back to 2022-03-07).

Method (Rule Zero — all real data):
  1. Run the validated v8a CS+SS blend backtest (final_validation config) on
     IronVault EOD → produces closed trades (ticker, legs, strikes, expirations,
     contracts, entry_date, exit_date, realized_pnl computed at trade prices).
  2. For each leg, query Polygon for the last NBBO at-or-before the EOD decision
     time (default 15:55 ET) on entry_date and exit_date. Real bid/ask.
  3. Compute execution cost under 3 fill policies using the REAL half-spread:
       cross   : pay the full quoted spread (sell shorts @ bid, buy longs @ ask)
       mid     : transact at the real mid (zero spread cost) — idealized
       nbbo    : capture (1 - improvement) of the half-spread; i.e. you post
                 inside and get filled at mid +/- improvement*half_spread.
                 Plus an unfilled fraction that crosses (pays full spread).
  4. Report net P&L / return / CAGR per policy and the nbbo-vs-cross uplift.

Only trades whose legs have real quotes on both dates are counted (others are
reported as 'unpriced' so coverage is transparent).

Usage:
    PYTHONPATH=. .venv/bin/python scripts/exp_nbbo_real_quotes.py [decision_hh:mm_ET]
Output:
    output/nbbo_real_quotes.json, reports/nbbo_real_quotes.html
"""
from __future__ import annotations
import json, math, os, sys, time, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from strategies import STRATEGY_REGISTRY          # noqa: E402
from strategies.base import LegType               # noqa: E402
from engine.portfolio_backtester import PortfolioBacktester  # noqa: E402
from backtest.historical_data import HistoricalOptionsData   # noqa: E402
from scripts.final_validation import (            # noqa: E402
    build_blend_params, TICKERS, STARTING_CAPITAL, ALL_YEARS,
)

# ── Polygon key (the one with /v3/quotes entitlement) ──
def _load_key() -> str:
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line.startswith("POLYGON_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("POLYGON_API_KEY not found in .env")

POLY_KEY = _load_key()
NBBO_IMPROVEMENT = 0.5     # fraction of half-spread captured by posting inside
UNFILLED_CROSS_PCT = 0.30  # passive quotes that miss and must cross
DECISION_ET = sys.argv[1] if len(sys.argv) > 1 else "15:55"

_quote_cache: Dict[str, Optional[Tuple[float, float]]] = {}
_api_calls = 0


def occ(ticker: str, expiration: datetime, strike: float, opt: str) -> str:
    y = expiration.strftime("%y%m%d")
    return f"O:{ticker}{y}{opt}{int(round(strike*1000)):08d}"


def et_to_utc_ns(d: datetime) -> int:
    # crude ET→UTC: EDT = UTC-4 (Mar–Nov). Our window 2020-2025 mostly EDT during RTH.
    hh, mm = map(int, DECISION_ET.split(":"))
    dt = datetime(d.year, d.month, d.day, hh, mm, tzinfo=timezone.utc) + timedelta(hours=4)
    return int(dt.timestamp() * 1e9)


def get_nbbo(symbol: str, day: datetime) -> Optional[Tuple[float, float]]:
    """Last (bid, ask) at-or-before decision time on `day`. Cached."""
    global _api_calls
    ck = f"{symbol}@{day:%Y-%m-%d}"
    if ck in _quote_cache:
        return _quote_cache[ck]
    ts = et_to_utc_ns(day)
    # day window in UTC ns (covers full RTH, EDT/EST agnostic)
    day_lo = int(datetime(day.year, day.month, day.day, 0, 0, tzinfo=timezone.utc).timestamp() * 1e9)
    # Primary: last quote at/just-before decision time. Fallback: last valid quote of the day.
    urls = [
        f"https://api.polygon.io/v3/quotes/{symbol}?timestamp.lte={ts}&timestamp.gte={day_lo}&order=desc&sort=timestamp&limit=5&apiKey={POLY_KEY}",
        f"https://api.polygon.io/v3/quotes/{symbol}?timestamp.gte={day_lo}&order=desc&sort=timestamp&limit=5&apiKey={POLY_KEY}",
    ]
    val = None
    for url in urls:
        for attempt in range(4):
            try:
                _api_calls += 1
                with urllib.request.urlopen(url, timeout=25) as r:
                    d = json.load(r)
                for row in d.get("results", []):
                    b = row.get("bid_price"); a = row.get("ask_price")
                    if b and a and a >= b > 0:
                        val = (float(b), float(a)); break
                break
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    time.sleep(1.5 * (attempt + 1)); continue
                break
            except Exception:
                time.sleep(0.5); continue
        if val is not None:
            break
    _quote_cache[ck] = val
    return val


def leg_opt(lt: LegType) -> str:
    return "C" if "call" in lt.value else "P"


def run_backtest() -> List:
    cs_params, ss_params = build_blend_params()
    cs_cls = STRATEGY_REGISTRY["credit_spread"]; ss_cls = STRATEGY_REGISTRY["straddle_strangle"]
    trades = []
    for year in ALL_YEARS:
        bt = PortfolioBacktester(
            strategies=[("credit_spread", cs_cls(dict(cs_params))),
                        ("straddle_strangle", ss_cls(dict(ss_params)))],
            tickers=TICKERS, start_date=datetime(year, 1, 1), end_date=datetime(year, 12, 31),
            starting_capital=STARTING_CAPITAL, max_positions=10, max_positions_per_strategy=5)
        bt.run(); trades.extend(bt.closed_trades)
    return trades


def trade_real_costs(t) -> Optional[Dict[str, float]]:
    """Return per-policy exec cost ($) for one trade using real NBBO, or None if unpriced."""
    if not t.entry_date or not t.exit_date:
        return None
    cross = mid = nbbo = 0.0
    for leg in t.legs:
        sym = occ(t.ticker, leg.expiration, leg.strike, leg_opt(leg.leg_type))
        qe = get_nbbo(sym, t.entry_date); qx = get_nbbo(sym, t.exit_date)
        if qe is None or qx is None:
            return None
        for (b, a) in (qe, qx):
            half = (a - b) / 2.0
            # cross: pay full half-spread; mid: 0; nbbo: pay (1-impr) of half, plus unfilled cross
            cross += half
            nbbo += (1 - UNFILLED_CROSS_PCT) * (1 - NBBO_IMPROVEMENT) * half + UNFILLED_CROSS_PCT * half
            # mid stays 0
    mult = t.contracts * 100
    return {"cross": cross * mult, "mid": mid * mult, "nbbo": nbbo * mult}


def annualized(net_pnl: float, years: int) -> float:
    return ((1 + net_pnl / STARTING_CAPITAL) ** (1 / years) - 1) * 100


def main():
    t0 = time.time()
    print("=" * 72)
    print("INSIDE-NBBO STUDY — REAL POLYGON QUOTES")
    print(f"decision time {DECISION_ET} ET | nbbo improvement {NBBO_IMPROVEMENT:.0%} | "
          f"unfilled cross {UNFILLED_CROSS_PCT:.0%}")
    print("=" * 72)
    trades = run_backtest()
    gross = sum(t.realized_pnl for t in trades)
    print(f"backtest: {len(trades)} trades, gross P&L ${gross:,.0f}. Pricing legs from Polygon…", flush=True)

    priced = []; unpriced = 0
    cost = {"cross": 0.0, "mid": 0.0, "nbbo": 0.0}
    for i, t in enumerate(trades):
        c = trade_real_costs(t)
        if c is None:
            unpriced += 1; continue
        priced.append(t)
        for k in cost: cost[k] += c[k]
        if (i + 1) % 25 == 0:
            print(f"  priced {len(priced)}/{i+1}  api_calls={_api_calls}", flush=True)

    n_years = len(ALL_YEARS)
    priced_gross = sum(t.realized_pnl for t in priced)
    results = {}
    for k, lab in [("cross", "Cross the spread (pay full quoted spread)"),
                   ("mid", "Transact at real mid (idealized)"),
                   ("nbbo", "Post inside NBBO (proposed upgrade)")]:
        net = priced_gross - cost[k]
        results[k] = {
            "label": lab,
            "exec_cost_usd": round(cost[k], 2),
            "exec_drag_pct": round(cost[k] / STARTING_CAPITAL * 100, 2),
            "net_pnl_usd": round(net, 2),
            "net_return_pct": round(net / STARTING_CAPITAL * 100, 2),
            "cagr_pct": round(annualized(net, n_years), 2),
        }
        print(f"  {k:6} exec ${cost[k]:,.0f}  net ${net:,.0f} ({net/STARTING_CAPITAL*100:+.1f}%)  "
              f"CAGR {results[k]['cagr_pct']:+.1f}%")

    cr, nb = results["cross"], results["nbbo"]
    uplift = {
        "nbbo_vs_cross_pnl_usd": round(nb["net_pnl_usd"] - cr["net_pnl_usd"], 2),
        "nbbo_vs_cross_cagr_pts": round(nb["cagr_pct"] - cr["cagr_pct"], 2),
        "real_avg_halfspread_note": "computed per-leg from actual bid/ask",
    }
    out = {
        "generated_at": datetime.now().isoformat(),
        "data_source": "Polygon /v3/quotes REAL historical NBBO + IronVault EOD backtest",
        "decision_time_et": DECISION_ET,
        "nbbo_improvement": NBBO_IMPROVEMENT, "unfilled_cross_pct": UNFILLED_CROSS_PCT,
        "tickers": TICKERS, "years": ALL_YEARS, "starting_capital": STARTING_CAPITAL,
        "n_trades_total": len(trades), "n_trades_priced": len(priced), "n_unpriced": unpriced,
        "coverage_pct": round(len(priced) / max(len(trades), 1) * 100, 1),
        "priced_gross_pnl_usd": round(priced_gross, 2),
        "api_calls": _api_calls,
        "profiles": results, "uplift": uplift,
        "runtime_sec": round(time.time() - t0, 1),
    }
    (ROOT / "output").mkdir(exist_ok=True)
    (ROOT / "output" / "nbbo_real_quotes.json").write_text(json.dumps(out, indent=2))
    write_html(out)
    print(f"\ncoverage {out['coverage_pct']}% ({len(priced)}/{len(trades)}) | api_calls {_api_calls} | "
          f"runtime {out['runtime_sec']}s")
    print("wrote output/nbbo_real_quotes.json + reports/nbbo_real_quotes.html")


def write_html(out: Dict):
    (ROOT / "reports").mkdir(exist_ok=True)
    p = out["profiles"]; u = out["uplift"]
    rows = ""
    for k in ["cross", "mid", "nbbo"]:
        r = p[k]; hl = ' style="background:#eaf7ea;font-weight:600"' if k == "nbbo" else ""
        rows += (f"<tr{hl}><td>{k}</td><td>{r['label']}</td><td>${r['exec_cost_usd']:,.0f}</td>"
                 f"<td>{r['exec_drag_pct']:.1f}%</td><td>${r['net_pnl_usd']:,.0f}</td>"
                 f"<td>{r['net_return_pct']:+.1f}%</td><td>{r['cagr_pct']:+.1f}%</td></tr>")
    html = f"""<!doctype html><html><head><meta charset=utf-8><title>Inside-NBBO (Real Quotes)</title>
<style>body{{font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:#fff;color:#1a1a1a;max-width:960px;margin:24px auto;padding:0 16px;line-height:1.5}}
h1{{font-size:22px;margin-bottom:4px}}h2{{font-size:16px;margin-top:22px}}.sub{{color:#666;font-size:13px}}
table{{border-collapse:collapse;width:100%;margin:10px 0;font-size:13px}}th,td{{border:1px solid #ddd;padding:6px 8px;text-align:right}}th{{background:#f5f5f5}}
td:nth-child(1),td:nth-child(2),th:nth-child(1),th:nth-child(2){{text-align:left}}
.note{{background:#e8f4ff;border:1px solid #b8d8f0;padding:10px 12px;border-radius:6px;font-size:13px;margin:12px 0}}
.big{{font-size:18px;font-weight:700;color:#1a7a1a}}.mono{{font-family:ui-monospace,Menlo,monospace}}</style></head><body>
<h1>Inside-NBBO Execution Upgrade — Real Quotes</h1>
<div class="sub">v8a CS+SS blend · IronVault EOD trades priced with <b>real Polygon NBBO</b> · {out['years'][0]}–{out['years'][-1]} · decision {out['decision_time_et']} ET · {out['generated_at'][:19]}</div>
<div class="note"><b>This version uses real measured bid/ask</b> (Polygon /v3/quotes), not assumed spreads. Quote coverage: <b>{out['coverage_pct']}%</b> of trades ({out['n_trades_priced']}/{out['n_trades_total']}; {out['n_unpriced']} unpriced excluded). NBBO profile captures {out['nbbo_improvement']:.0%} of the real half-spread and still crosses on {out['unfilled_cross_pct']:.0%} of fills.</div>
<h2>Result</h2>
<p>Priced-trades gross P&amp;L: <span class="mono">${out['priced_gross_pnl_usd']:,.0f}</span> on ${out['starting_capital']:,} seed.</p>
<table><tr><th>Policy</th><th>Meaning</th><th>Exec cost</th><th>Drag</th><th>Net P&amp;L</th><th>Net ret</th><th>CAGR</th></tr>{rows}</table>
<h2>Uplift — inside NBBO vs crossing the spread</h2>
<p class="big">+${u['nbbo_vs_cross_pnl_usd']:,.0f} net P&amp;L · +{u['nbbo_vs_cross_cagr_pts']:.1f} pts CAGR</p>
<p class="sub">Half-spread measured per leg from actual quotes. {out['api_calls']:,} Polygon calls. Runtime {out['runtime_sec']}s.</p>
</body></html>"""
    (ROOT / "reports" / "nbbo_real_quotes.html").write_text(html)


if __name__ == "__main__":
    main()
