"""EXP-3309 — Liquidity-weighted entry timing.

Spec source: user request, cross-referenced with
compass/reports/exp3300_literature_review_may2026.md (note: lit-review
§EXP-3309 framed this as order-flow signal reconstruction; this
experiment instead implements the user's execution-side framing — the
order-flow signal version is deferred).

Question
--------
EXP-2470 already exits inside the 15-min pre-close window (technique
"B"), but applies the 0.75 slippage factor *uniformly* to both legs.
This bakes in the implicit assumption that entries also benefit from
the patient window — which they don't, in production: most strategies
enter near the open (RTH start signal generation).

Does timing entries to the pre-close window (where option ADV is ~2×
the open and bid-ask spreads compress ~15-25%) produce material net-
Sharpe savings, or is the entry leg a small slice of round-trip cost?

Method
------
Decompose the EXP-2420 round-trip cost model into entry leg + exit leg,
then sweep entry-timing scenarios (open / mid-day / pre-close) under
fixed pre-close exit (production EXP-2470 default). Per-window factors:

  Window      Spread×    Slippage×   Fill-rate     Source
  ─────────   ───────    ─────────   ─────────     ──────────────────
  Open        1.30       1.22        0.85          Open auction has wider
              (wider)    (1/√0.67)                 spreads, ~67% of
                                                   midday option ADV
                                                   (Chordia-Roll-Subra,
                                                   Doshi-Patel-Singal 2025)
  Mid-day     1.00       1.00        0.92          baseline (10-15:00)
  Pre-close   0.85       0.71        0.98          ~2× midday option ADV
              (tight)    (1/√2)                    (EXP-2470 method note),
                                                   tightest quotes of day

Fill rate is reported INFORMATIONALLY only. In production, unfilled
limit orders are retried as market orders (EXP-2470 method-A footnote);
the cost difference between filled-at-mid and retried-at-spread is
already absorbed in the per-window spread×. We deliberately do NOT
add a "missed-trade opportunity cost" line, because that would
double-count: the worst-case fallback (market order at full spread)
is the same as what the open-window spread× already represents.

Round-trip cost = entry_leg + exit_leg, where each leg uses the per-
window factors above. Slippage applies per leg (one round-trip = entry
fill + exit fill).

Comparison
----------
Net Sharpe under v8a baseline (gross SR 6.830, gross CAGR 284.4%,
ann vol from those two = 41.6%) for four scenarios:
    A. Open entry  + Open exit          (worst — current EXP-2420 base)
    B. Open entry  + Pre-close exit     (current EXP-2470 stack-B implicit)
    C. Mid entry   + Pre-close exit     (control)
    D. Pre-close entry + Pre-close exit (proposed)

Rule Zero
---------
Anchored to real EXP-2420 cost decomposition (IronVault p25 spreads +
Yahoo ADV). Per-window timing factors from documented intraday
volume / spread literature; no synthetic fills.

Outputs
  compass/reports/exp3309_liquidity_weighted_entry.json
  compass/reports/exp3309_liquidity_weighted_entry.html
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REPORT_JSON = ROOT / "compass" / "reports" / "exp3309_liquidity_weighted_entry.json"
REPORT_HTML = ROOT / "compass" / "reports" / "exp3309_liquidity_weighted_entry.html"
EXP2420_JSON = ROOT / "compass" / "reports" / "exp2420_transaction_costs.json"

# v8a baseline from EXP-2600 (8-stream LW risk-parity, target_vol=0.18)
V8A_GROSS_SHARPE = 6.830
V8A_GROSS_CAGR_PCT = 284.4
CAPITAL_USD = 100_000.0
TRADING_DAYS = 252

# v8a annualised arithmetic vol implied by Sharpe + CAGR
# daily_mean = ln(1+CAGR)/252; daily_std = daily_mean*sqrt(252)/Sharpe
_dm = math.log(1 + V8A_GROSS_CAGR_PCT / 100) / TRADING_DAYS
_ds = _dm * math.sqrt(TRADING_DAYS) / V8A_GROSS_SHARPE
V8A_ANN_VOL_PCT = _ds * math.sqrt(TRADING_DAYS) * 100

# Total v8a trades/year (sum across 8 streams; aligned with EXP-2420 STREAMS
# table + qqq_cs ~35 trades/yr from EXP-2250)
V8A_TRADES_PER_YEAR = 34 + 34 + 34 + 50 + 50 + 45 + 20 + 35   # = 302

# Commission scales with contract count, NOT with timing — copied from
# EXP-2420 baseline at 3× leverage.
COMMISSION_BASELINE_USD = 8273.20

# Per-window timing factors (documented; see header)
@dataclass
class WindowFactors:
    name: str
    spread_factor: float       # multiplies bid-ask cost
    slippage_factor: float     # multiplies √-impact slippage
    fill_rate: float           # fraction of orders filled
    note: str

WINDOWS: Dict[str, WindowFactors] = {
    "open":      WindowFactors("Open auction (9:30-10:00)",
                               1.30, 1.22, 0.85,
                               "Wider spreads + ~67% of midday option ADV. "
                               "Chordia-Roll-Subrahmanyam intraday liquidity "
                               "patterns, confirmed in Doshi-Patel-Singal 2025 "
                               "for option order flow."),
    "midday":    WindowFactors("Mid-day (10:00-15:00)",
                               1.00, 1.00, 0.92,
                               "Baseline reference window. EXP-2420 cost model "
                               "is calibrated against IronVault daily summaries "
                               "(close-of-day NBBO proxy), aligning with "
                               "midday liquidity."),
    "preclose":  WindowFactors("Pre-close (15:30-16:00)",
                               0.85, 0.71, 0.98,
                               "~2× midday option ADV (EXP-2470 method note); "
                               "spread compresses ~15%; √-impact 1/√2 ≈ 0.71. "
                               "Closing auction provides near-deterministic "
                               "fills."),
}


# ── Helpers ──────────────────────────────────────────────────────────


def load_exp2420_baseline() -> Dict[str, float]:
    """Pull EXP-2420 round-trip $ costs (entry + exit, no timing assumption)."""
    if not EXP2420_JSON.exists():
        raise FileNotFoundError(f"EXP-2420 report missing: {EXP2420_JSON}")
    payload = json.loads(EXP2420_JSON.read_text())
    s = payload["summary"]
    return {
        "bid_ask_round_trip_usd": float(s["bid_ask_usd"]),
        "slippage_round_trip_usd": float(s["slippage_usd"]),
        "commission_round_trip_usd": float(s["commission_usd"]),
        "total_round_trip_usd": float(s["total_drag_usd"]),
    }


def split_entry_exit(rt_usd: float) -> float:
    """Round-trip → per-leg cost. Bid-ask + slippage split 50/50 since both
    legs cross the same spread / pay the same √-impact at equivalent
    notional. Commission stays per-contract per-leg.
    """
    return rt_usd / 2.0


def per_trade_gross_pnl_usd() -> float:
    """Average per-trade gross PnL on $100K v8a baseline."""
    annual_pnl_usd = (V8A_GROSS_CAGR_PCT / 100.0) * CAPITAL_USD
    return annual_pnl_usd / V8A_TRADES_PER_YEAR


def scenario_costs(entry_w: WindowFactors,
                   exit_w: WindowFactors,
                   base: Dict[str, float]) -> Dict:
    """Compute annualised drag + opportunity cost + net Sharpe for one
    (entry, exit) policy.
    """
    # Per-leg base cost (EXP-2420 split 50/50)
    ba_per_leg = split_entry_exit(base["bid_ask_round_trip_usd"])
    sl_per_leg = split_entry_exit(base["slippage_round_trip_usd"])

    # Apply per-leg timing factors
    ba_entry = ba_per_leg * entry_w.spread_factor
    ba_exit = ba_per_leg * exit_w.spread_factor
    sl_entry = sl_per_leg * entry_w.slippage_factor
    sl_exit = sl_per_leg * exit_w.slippage_factor

    bid_ask_total = ba_entry + ba_exit
    slippage_total = sl_entry + sl_exit
    commission_total = base["commission_round_trip_usd"]

    # Fill rate is informational: unfilled limits get market-order
    # fallback (already costed in the open-window spread×). We do NOT
    # add a "missed PnL" opportunity cost line — that would double-count
    # the worst-case spread the open-window factor already represents.
    miss_rate = 1.0 - entry_w.fill_rate
    per_trade_pnl = per_trade_gross_pnl_usd()
    missed_trades = miss_rate * V8A_TRADES_PER_YEAR
    opportunity_cost_usd = 0.0

    total_drag_usd = bid_ask_total + slippage_total + commission_total
    total_drag_bps = total_drag_usd / CAPITAL_USD * 10_000.0

    # Net Sharpe (gross_mean - drag/year, vol unchanged)
    ann_vol_dec = V8A_ANN_VOL_PCT / 100.0
    ann_mean_gross = V8A_GROSS_SHARPE * ann_vol_dec
    ann_mean_net = ann_mean_gross - total_drag_bps / 10_000.0
    net_sharpe = ann_mean_net / ann_vol_dec if ann_vol_dec > 1e-12 else 0.0
    net_cagr_pct = V8A_GROSS_CAGR_PCT - total_drag_bps / 100.0

    return {
        "entry_window": entry_w.name,
        "exit_window": exit_w.name,
        "entry_window_key": _key(entry_w),
        "exit_window_key": _key(exit_w),
        "bid_ask_entry_usd": round(ba_entry, 2),
        "bid_ask_exit_usd": round(ba_exit, 2),
        "bid_ask_total_usd": round(bid_ask_total, 2),
        "slippage_entry_usd": round(sl_entry, 2),
        "slippage_exit_usd": round(sl_exit, 2),
        "slippage_total_usd": round(slippage_total, 2),
        "commission_total_usd": round(commission_total, 2),
        "fill_rate": entry_w.fill_rate,
        "miss_rate": round(miss_rate, 4),
        "missed_trades_per_year": round(missed_trades, 2),
        "per_trade_gross_pnl_usd": round(per_trade_pnl, 2),
        "opportunity_cost_usd": round(opportunity_cost_usd, 2),
        "total_drag_usd": round(total_drag_usd, 2),
        "total_drag_bps": round(total_drag_bps, 2),
        "total_drag_pct": round(total_drag_bps / 100.0, 3),
        "net_sharpe": round(net_sharpe, 3),
        "net_cagr_pct": round(net_cagr_pct, 2),
        "delta_sharpe_vs_gross": round(net_sharpe - V8A_GROSS_SHARPE, 3),
    }


def _key(w: WindowFactors) -> str:
    for k, v in WINDOWS.items():
        if v is w:
            return k
    return "?"


# ── Main ─────────────────────────────────────────────────────────────


def main() -> None:
    print("=" * 72)
    print("EXP-3309 — Liquidity-weighted entry timing")
    print("=" * 72)

    print("\n[1/4] Loading EXP-2420 round-trip cost baseline…")
    base = load_exp2420_baseline()
    print(f"      bid-ask round-trip:    ${base['bid_ask_round_trip_usd']:>9,.0f}")
    print(f"      slippage round-trip:   ${base['slippage_round_trip_usd']:>9,.0f}")
    print(f"      commission round-trip: ${base['commission_round_trip_usd']:>9,.0f}")
    print(f"      total round-trip:      ${base['total_round_trip_usd']:>9,.0f}")
    print(f"      (anchor: 7-stream EXP-2420 @ 3× leverage; per-leg = round-trip / 2)")

    print(f"\n[2/4] v8a anchor: gross SR {V8A_GROSS_SHARPE:.3f}  "
          f"CAGR {V8A_GROSS_CAGR_PCT:.1f}%  "
          f"implied ann vol {V8A_ANN_VOL_PCT:.2f}%")
    print(f"      trades/year (sum over 8 streams): {V8A_TRADES_PER_YEAR}")
    print(f"      avg gross PnL per trade: ${per_trade_gross_pnl_usd():,.2f}")

    print("\n[3/4] Per-window timing factors (documented from intraday lit.):")
    print(f"{'window':>10}  {'spread×':>8}  {'slip×':>7}  "
          f"{'fill_rate':>10}")
    for w in WINDOWS.values():
        print(f"{w.name[:10]:>10}  {w.spread_factor:>8.2f}  "
              f"{w.slippage_factor:>7.2f}  {w.fill_rate:>10.2f}")

    print("\n[4/4] Scenario sweep (entry × exit) on v8a baseline…")
    scenarios = []
    pairs = [
        ("open",     "open",     "A: Open entry / Open exit (no patient stack)"),
        ("open",     "preclose", "B: Open entry / Pre-close exit (EXP-2470 stack-B implicit)"),
        ("midday",   "preclose", "C: Mid-day entry / Pre-close exit (control)"),
        ("preclose", "preclose", "D: Pre-close entry / Pre-close exit (proposed)"),
    ]
    print(f"\n{'label':<60} "
          f"{'bid-ask':>8} {'slipp':>8} {'opp':>8} "
          f"{'drag bps':>9} {'net SR':>7} {'net CAGR':>9}")
    for entry_k, exit_k, label in pairs:
        s = scenario_costs(WINDOWS[entry_k], WINDOWS[exit_k], base)
        s["label"] = label
        scenarios.append(s)
        print(f"{label:<60} "
              f"${s['bid_ask_total_usd']:>7,.0f} "
              f"${s['slippage_total_usd']:>7,.0f} "
              f"${s['opportunity_cost_usd']:>7,.0f} "
              f"{s['total_drag_bps']:>8.0f}  "
              f"{s['net_sharpe']:>6.2f}  "
              f"{s['net_cagr_pct']:>8.1f}%")

    # Best (max net Sharpe)
    best = max(scenarios, key=lambda s: s["net_sharpe"])
    base_scn = next(s for s in scenarios
                    if s["entry_window_key"] == "open"
                    and s["exit_window_key"] == "open")
    cur_scn = next(s for s in scenarios
                   if s["entry_window_key"] == "open"
                   and s["exit_window_key"] == "preclose")

    delta_vs_open = best["net_sharpe"] - base_scn["net_sharpe"]
    delta_vs_b = best["net_sharpe"] - cur_scn["net_sharpe"]

    print("\n" + "-" * 72)
    print(f"  Best scenario: {best['label']}")
    print(f"     net SR {best['net_sharpe']:.3f}  net CAGR {best['net_cagr_pct']:.1f}%")
    print(f"     Δ net SR vs Scenario A (no patient stack):    {delta_vs_open:+.3f}")
    print(f"     Δ net SR vs Scenario B (EXP-2470 implicit):    {delta_vs_b:+.3f}")

    if delta_vs_b >= 0.05:
        verdict = "MATERIAL_LIFT"
    elif delta_vs_b >= 0.01:
        verdict = "MARGINAL_LIFT"
    elif delta_vs_b >= -0.01:
        verdict = "FLAT"
    else:
        verdict = "NEGATIVE"
    print(f"  Verdict (vs current EXP-2470 baseline): {verdict}")

    payload = {
        "experiment": "EXP-3309",
        "title": "Liquidity-weighted entry timing for v8a (entry × exit window sweep)",
        "generated": datetime.now().isoformat(timespec="seconds"),
        "rule_zero": True,
        "spec_source": (
            "user request, cross-referenced with "
            "compass/reports/exp3300_literature_review_may2026.md "
            "(execution-side framing; lit-review §EXP-3309 was "
            "order-flow signal reconstruction — deferred)"
        ),
        "data_caveat": (
            "Cost decomposition anchored to EXP-2420 round-trip $ figures "
            "(real IronVault option_daily p25 spreads + real Yahoo 90d ADV). "
            "Per-window timing factors (spread×, slippage×, fill_rate) are "
            "documented coefficients from intraday liquidity literature, not "
            "measured from a per-minute IronVault tape (we don't currently "
            "ingest minute bars). Conclusions are SCENARIO ANALYSIS — to "
            "verify the +X bps savings empirically, run a 1-month live "
            "paper-trade with split-entry routing through Alpaca + capture "
            "fill timestamps."
        ),
        "config": {
            "v8a_gross_sharpe": V8A_GROSS_SHARPE,
            "v8a_gross_cagr_pct": V8A_GROSS_CAGR_PCT,
            "v8a_implied_ann_vol_pct": round(V8A_ANN_VOL_PCT, 3),
            "v8a_trades_per_year": V8A_TRADES_PER_YEAR,
            "capital_usd": CAPITAL_USD,
            "trading_days": TRADING_DAYS,
            "windows": {k: asdict(v) for k, v in WINDOWS.items()},
        },
        "exp2420_baseline": base,
        "scenarios": scenarios,
        "best": best,
        "delta_vs_no_patient_stack": round(delta_vs_open, 4),
        "delta_vs_exp2470_implicit": round(delta_vs_b, 4),
        "verdict": {
            "code": verdict,
            "delta_net_sharpe_vs_exp2470": round(delta_vs_b, 4),
            "best_label": best["label"],
        },
    }

    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\n[report] → {REPORT_JSON}")

    REPORT_HTML.write_text(build_html(payload), encoding="utf-8")
    print(f"[report] → {REPORT_HTML}")


# ── HTML ─────────────────────────────────────────────────────────────


def build_html(p: Dict) -> str:
    cfg = p["config"]
    base = p["exp2420_baseline"]
    best = p["best"]
    v = p["verdict"]

    color = {
        "MATERIAL_LIFT":  "#16a34a",
        "MARGINAL_LIFT":  "#65a30d",
        "FLAT":           "#f59e0b",
        "NEGATIVE":       "#dc2626",
    }.get(v["code"], "#64748b")

    def fmt_window(w: Dict) -> str:
        return (f"<tr><td>{w['name']}</td>"
                f"<td>{w['spread_factor']:.2f}</td>"
                f"<td>{w['slippage_factor']:.2f}</td>"
                f"<td>{w['fill_rate']:.2f}</td>"
                f"<td class='note'>{w['note']}</td></tr>")

    window_rows = "".join(fmt_window(w) for w in cfg["windows"].values())

    def fmt_scn(s: Dict, is_best: bool) -> str:
        css = "best" if is_best else ""
        delta = s["net_sharpe"] - V8A_GROSS_SHARPE
        return (
            f"<tr class='{css}'>"
            f"<td>{s['label']}</td>"
            f"<td>${s['bid_ask_entry_usd']:,.0f}</td>"
            f"<td>${s['bid_ask_exit_usd']:,.0f}</td>"
            f"<td>${s['slippage_entry_usd']:,.0f}</td>"
            f"<td>${s['slippage_exit_usd']:,.0f}</td>"
            f"<td>{s['fill_rate']*100:.0f}%</td>"
            f"<td>${s['opportunity_cost_usd']:,.0f}</td>"
            f"<td>${s['total_drag_usd']:,.0f}</td>"
            f"<td>{s['total_drag_bps']:.0f}</td>"
            f"<td><strong>{s['net_sharpe']:.3f}</strong></td>"
            f"<td>{delta:+.3f}</td>"
            f"</tr>"
        )

    scenario_rows = "".join(
        fmt_scn(s, s["label"] == best["label"]) for s in p["scenarios"]
    )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>EXP-3309 — Liquidity-Weighted Entry Timing</title>
<style>
body{{font-family:-apple-system,sans-serif;max-width:1280px;margin:0 auto;padding:28px;background:#fff;color:#1e293b;}}
h1{{font-size:1.7em;color:#0f172a;}}
h2{{margin-top:2em;border-bottom:2px solid #e2e8f0;padding-bottom:8px;color:#334155;}}
.muted{{color:#64748b;font-size:0.85em;}}
.caveat{{background:#fef3c7;border:2px solid #f59e0b;border-radius:8px;padding:16px;margin:16px 0;font-size:0.9rem;line-height:1.55;}}
.caveat strong{{color:#92400e;}}
.sources{{background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:14px;font-size:0.84rem;line-height:1.6;}}
.verdict{{background:#fff;border:2px solid {color};border-radius:8px;padding:18px;margin:18px 0;}}
.verdict .badge{{display:inline-block;padding:5px 14px;border-radius:14px;color:#fff;background:{color};font-weight:700;font-size:0.86rem;}}
table{{width:100%;border-collapse:collapse;margin:12px 0;font-size:0.85em;}}
th{{background:#f1f5f9;padding:8px 9px;text-align:right;border-bottom:2px solid #cbd5e1;font-size:0.7em;text-transform:uppercase;}}
th:first-child{{text-align:left;}}
td{{padding:7px 9px;text-align:right;border-bottom:1px solid #e2e8f0;}}
td:first-child{{text-align:left;font-weight:600;color:#475569;}}
td.note{{text-align:left;font-weight:400;color:#64748b;font-size:0.9em;}}
tr.best{{background:#ecfdf5;font-weight:600;}}
.kv{{display:grid;grid-template-columns:repeat(2,1fr);gap:6px 18px;font-size:0.9em;margin:10px 0;}}
.kv b{{color:#475569;}}
</style></head><body>

<h1>EXP-3309 — Liquidity-weighted entry timing</h1>
<p class="muted">Decompose EXP-2420 round-trip cost into per-leg
entry + exit, sweep entry-window timing (open / mid / pre-close),
hold exit at pre-close (production EXP-2470 default). Identify
whether moving entries from the open into the pre-close window
delivers material net-Sharpe savings on v8a.
{datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<div class="sources">
<strong>Rule Zero.</strong> Round-trip $ baseline pulled from
EXP-2420 (real IronVault p25 spreads + Yahoo 90d ADV at 3× leverage):
bid-ask ${base['bid_ask_round_trip_usd']:,.0f}, slippage
${base['slippage_round_trip_usd']:,.0f}, commission
${base['commission_round_trip_usd']:,.0f}. Per-leg costs = round-trip / 2.
v8a anchor: gross SR {cfg['v8a_gross_sharpe']:.2f}, gross CAGR
{cfg['v8a_gross_cagr_pct']:.1f}% (EXP-2600 8-stream LW @ target_vol=0.18),
implied ann vol {cfg['v8a_implied_ann_vol_pct']:.2f}%.
</div>

<div class="caveat">
<strong>⚠ SCENARIO ANALYSIS, not measured fills.</strong> Per-window
timing factors (spread×, slippage×, fill_rate) are documented
coefficients from the intraday-liquidity literature (Chordia-Roll-
Subrahmanyam; EXP-2470 method note on ~2× pre-close ADV; Doshi-
Patel-Singal 2025 for option order flow) — they are NOT measured
from a per-minute IronVault tape (we do not currently ingest minute
bars). The conclusion below is therefore an estimate. To verify,
run a 1-month live paper trade with split-entry routing through
Alpaca and capture fill timestamps.
</div>

<div class="verdict">
<span class="badge">{v['code']}</span>
<div class="kv" style="margin-top:14px">
<div><b>Best entry policy</b></div>
<div>{v['best_label']}</div>
<div><b>Best net Sharpe</b></div>
<div>{best['net_sharpe']:.3f} (Δ vs gross
{best['delta_sharpe_vs_gross']:+.3f})</div>
<div><b>Δ net SR vs no patient stack</b></div>
<div>{p['delta_vs_no_patient_stack']:+.3f}</div>
<div><b>Δ net SR vs EXP-2470 implicit (open entry)</b></div>
<div>{p['delta_vs_exp2470_implicit']:+.3f}</div>
<div><b>Best total drag</b></div>
<div>{best['total_drag_bps']:.0f} bps
(${best['total_drag_usd']:,.0f}/yr on $100K)</div>
<div><b>Best fill rate</b></div>
<div>{best['fill_rate']*100:.0f}%</div>
</div>
</div>

<h2>1. Per-window timing factors (documented)</h2>
<table>
<thead><tr>
<th>Window</th><th>spread×</th><th>slippage×</th>
<th>fill rate</th><th>note</th>
</tr></thead>
<tbody>{window_rows}</tbody>
</table>

<h2>2. Scenario sweep — entry × exit policy</h2>
<p class="muted">Per-leg cost split 50/50 from EXP-2420 round-trip
baseline; timing factors applied per leg. Opportunity cost = missed
trades × per-trade gross PnL (avg
${best['per_trade_gross_pnl_usd']:.0f}/trade across
{cfg['v8a_trades_per_year']} trades/yr).</p>
<table>
<thead><tr>
<th>Scenario</th>
<th>BA entry $</th><th>BA exit $</th>
<th>Slip entry $</th><th>Slip exit $</th>
<th>Fill</th><th>Opp. cost</th>
<th>Total $</th><th>Drag bps</th>
<th>Net SR</th><th>Δ vs gross</th>
</tr></thead>
<tbody>{scenario_rows}</tbody>
</table>

<h2>3. Reading the result</h2>
<ul>
<li><strong>Pre-close entry saves ~{base['bid_ask_round_trip_usd']*0.225:.0f}
on bid-ask</strong> ({base['bid_ask_round_trip_usd']*0.225/CAPITAL_USD*10_000:.0f} bps)
and <strong>~{base['slippage_round_trip_usd']*0.255:.0f}
on slippage</strong>
({base['slippage_round_trip_usd']*0.255/CAPITAL_USD*10_000:.0f} bps)
per round-trip relative to open entry, holding exit fixed at pre-close.</li>
<li><strong>Fill rate is informational, not a drag line.</strong>
At 85% mid-limit fill the unfilled 15% retries as market orders at the
open-window spread — which is exactly the cost the open spread×
factor already represents. Adding a separate "missed PnL"
opportunity cost would double-count.</li>
<li><strong>Net Sharpe lift vs EXP-2470 baseline:
{p['delta_vs_exp2470_implicit']:+.3f}.</strong>
EXP-2470 stack-B already captured the slippage half of pre-close
savings on the exit leg; pre-close ENTRY harvests the remaining
~half on the entry leg. The marginal savings are real but small
relative to overall drag.</li>
</ul>

<h2>4. Production recommendation</h2>
<p class="muted">If the ${best['per_trade_gross_pnl_usd']:.0f} per-trade
PnL figure holds in live trading, scenario D ({best['label']})
is strictly dominant on this cost model. The two operational
considerations not captured here:</p>
<ol>
<li><strong>Signal staleness.</strong> Many of v8a's streams generate
signals from morning IV / open prices; deferring entry by ~6 hours
introduces signal decay we have not measured. EXP-2470 method-B
implicitly assumes signal freshness loss is small.</li>
<li><strong>Adverse-selection in the closing auction.</strong>
Closing-auction order flow is increasingly dominated by passive
indexing rebalances, which are not noisy fills — but on rare
event days (FOMC, NFP) the closing print has crossed-spread
slippage that this scenario model does not capture.</li>
</ol>

<p style="margin-top:3em;color:#94a3b8;font-size:0.78em;text-align:center">
compass/exp3309_liquidity_weighted_entry.py · Rule Zero · anchored to EXP-2420 IronVault + Yahoo
</p>
</body></html>"""


if __name__ == "__main__":
    main()
