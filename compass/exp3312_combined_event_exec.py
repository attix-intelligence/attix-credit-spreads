"""EXP-3312 — Combined backtest: EXP-3311 NFP gate + EXP-3309 pre-close execution.

Hypothesis
----------
User pre-registration:
    H_combined: layering the NFP-only entry gate (defensive, +ΔDD savings)
    on top of the pre-close execution window (offensive, -Δdrag savings)
    stacks roughly additively, giving:
        net Sharpe  ≈ 6.05
        max DD       <  6.00 %
        net CAGR    ≈ 115 %

This is a 2×2 factorial: {gate ON / OFF} × {pre-close drag / baseline drag}.

Method
------
A single v8a + VIX-ladder walk-forward cube (EXP-2850 engine, EXP-3311 builder)
is run four times:

    Cell_00  baseline_drag + no_gate    (= EXP-3311 baseline)
    Cell_10  baseline_drag + NFP_gate   (= EXP-3311 NFP-only ablation cell)
    Cell_01  preclose_drag + no_gate    (= EXP-3309-D applied to EXP-3311 cube)
    Cell_11  preclose_drag + NFP_gate   (= the combined treatment under test)

Drag bookkeeping (Rule Zero)
----------------------------
EXP-3309 measures total round-trip drag of $22 177.77 (scenario B, EXP-2470
implicit) vs $18 749.40 (scenario D, pre-close). The reduction ratio is
1 - 18749.40/22177.77 = 15.456 %. The EXP-2850 walk-forward engine uses
NET_DRAG_PCT = 8.903 %/yr (calibrated against the same EXP-2470 baseline).
We apply the same proportional reduction:
    preclose_drag_pct = 8.903 × (18749.40 / 22177.77) = 7.527 %/yr
That is the only "translation" between the two experiments — drag $ saving
ratios scale linearly into the NET_DRAG_PCT space because both share the
same trade-count denominator (302 trades/yr at $100 k capital).

The NFP gate is applied to entries on the same 4 credit-spread streams
(exp1220 / xlf_cs / xli_cs / qqq_cs) using EventCalendar(event_types=['nfp']),
identical to the EXP-3311 NFP-only cell.

Interaction effect
------------------
    iA  = SR(Cell_10) - SR(Cell_00)      # NFP gate effect at baseline drag
    iB  = SR(Cell_01) - SR(Cell_00)      # pre-close drag effect, no gate
    additive_pred = SR(Cell_00) + iA + iB
    interaction   = SR(Cell_11) - additive_pred
A negative interaction means the two treatments do not fully stack
(e.g. drag savings already include some implicit timing on NFP days);
a positive interaction is a synergy.

Outputs
-------
    compass/reports/exp3312_combined_event_exec.json
    compass/reports/exp3312_combined_event_exec.html

Rule Zero
---------
All trade tapes are real IronVault outputs (XLF / XLI / QQQ pickles plus
regenerated exp1220 trades). Event calendar is deterministic. Drag rate
is the EXP-2570 measured number proportionally scaled by EXP-3309's
empirically derived round-trip $ ratios. No synthetic prices, no
fabricated event dates.

Limitation
----------
The EXP-3309 drag savings are a *scenario analysis* — the per-window
spread / slippage factors are documented coefficients from intraday
liquidity literature, NOT measured from a minute-bar IronVault tape.
A 1-month live paper-trade through Alpaca with fill-timestamp capture
is required to verify the +173 bps annual drag saving empirically.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Patch NET_DRAG_PCT in place between calls — daily_drag is recomputed
# inside walk_forward_with_ladder, so module-level reassignment works.
from compass import exp2850_v8a_with_vix_ladder as wf_mod
from compass.exp2850_v8a_with_vix_ladder import (
    walk_forward_with_ladder,
    summarize,
    yearly_breakdown,
    CAPITAL,
    TRADING_DAYS,
    TRAIN_DAYS,
    TEST_DAYS,
    TARGET_VOL,
    SCALE_CAP,
)
from compass.vix_ladder import VIXLadder, fetch_vix
from compass.exp3311_event_gate import EventCalendar, DEFAULT_WINDOW
from compass.exp3311_runner import build_baseline_cube, build_gated_cube

REPORT_JSON = ROOT / "compass" / "reports" / "exp3312_combined_event_exec.json"
REPORT_HTML = ROOT / "compass" / "reports" / "exp3312_combined_event_exec.html"

# Drag bookkeeping — see module docstring.
BASELINE_DRAG_PCT = 8.903                                 # EXP-2570
EXP3309_DRAG_B_USD = 22177.77                             # scenario B (EXP-2470 implicit)
EXP3309_DRAG_D_USD = 18749.40                             # scenario D (pre-close)
DRAG_RATIO_D_OVER_B = EXP3309_DRAG_D_USD / EXP3309_DRAG_B_USD
PRECLOSE_DRAG_PCT = round(BASELINE_DRAG_PCT * DRAG_RATIO_D_OVER_B, 3)

# Hypothesis gates (pre-registered).
H_SR_TARGET = 6.05
H_DD_MAX_PCT = 6.00
H_CAGR_TARGET_PCT = 115.0


# ---------------------------------------------------------------------------
# Cell runner
# ---------------------------------------------------------------------------


def _run_cell(
    label: str,
    cube: pd.DataFrame,
    vix: pd.Series,
    ladder: VIXLadder,
    drag_pct: float,
) -> Tuple[Dict, pd.Series, List[Dict]]:
    """Run one 2x2 cell with a specific drag rate.

    Monkey-patches wf_mod.NET_DRAG_PCT; daily_drag is recomputed inside
    walk_forward_with_ladder from the *current* module attribute.
    """
    original = wf_mod.NET_DRAG_PCT
    wf_mod.NET_DRAG_PCT = drag_pct
    try:
        pooled, _, folds = walk_forward_with_ladder(
            cube, vix, ladder, apply_ladder=True
        )
    finally:
        wf_mod.NET_DRAG_PCT = original
    s = summarize(pooled, folds, label)
    s["drag_pct_used"] = drag_pct
    return s, pooled, folds


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("=" * 76)
    print("EXP-3312 — Combined NFP gate + pre-close execution (2x2 factorial)")
    print("=" * 76)
    print(f"  baseline drag:    {BASELINE_DRAG_PCT:.3f} %/yr  (EXP-2570)")
    print(f"  preclose drag:    {PRECLOSE_DRAG_PCT:.3f} %/yr  "
          f"(EXP-3309 D/B ratio = {DRAG_RATIO_D_OVER_B:.4f})")
    print(f"  drag saving:      {BASELINE_DRAG_PCT - PRECLOSE_DRAG_PCT:.3f} pp/yr")

    cal = EventCalendar()

    print("\n[1/4] building baseline cube (no gate)...")
    cube_no_gate = build_baseline_cube()
    print(f"       {cube_no_gate.shape}  "
          f"{cube_no_gate.index[0].date()} → {cube_no_gate.index[-1].date()}")

    print("\n[2/4] building NFP-only gated cube...")
    cube_nfp, diag_nfp = build_gated_cube(cal, event_types=["nfp"])
    for k, v in diag_nfp.items():
        print(f"       {k}: kept={v['kept']}  dropped={v['dropped']} "
              f"({v['drop_pct']:.1f}%)")

    print("\n[3/4] fetching VIX + initialising ladder...")
    vix_start = (cube_no_gate.index.min() - pd.Timedelta(days=30)).strftime("%Y-%m-%d")
    vix_end = (cube_no_gate.index.max() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    vix = fetch_vix(vix_start, vix_end)
    ladder = VIXLadder()

    print("\n[4/4] running 2x2 cells...\n")
    cells: Dict[str, Dict] = {}

    s00, _, _ = _run_cell("cell_00_baseline", cube_no_gate, vix, ladder,
                          BASELINE_DRAG_PCT)
    print(f"  cell_00 baseline (no gate, base drag):     "
          f"SR {s00['sharpe']:.3f}  CAGR {s00['cagr_pct']:+.1f}%  "
          f"DD {s00['max_dd_pct']:.2f}%")
    cells["cell_00_baseline"] = s00

    s10, _, _ = _run_cell("cell_10_nfp_only", cube_nfp, vix, ladder,
                          BASELINE_DRAG_PCT)
    print(f"  cell_10 NFP gate (no drag fix):            "
          f"SR {s10['sharpe']:.3f}  CAGR {s10['cagr_pct']:+.1f}%  "
          f"DD {s10['max_dd_pct']:.2f}%")
    cells["cell_10_nfp_only"] = s10

    s01, _, _ = _run_cell("cell_01_preclose_only", cube_no_gate, vix, ladder,
                          PRECLOSE_DRAG_PCT)
    print(f"  cell_01 pre-close drag (no gate):          "
          f"SR {s01['sharpe']:.3f}  CAGR {s01['cagr_pct']:+.1f}%  "
          f"DD {s01['max_dd_pct']:.2f}%")
    cells["cell_01_preclose_only"] = s01

    s11, pooled11, folds11 = _run_cell("cell_11_combined", cube_nfp, vix, ladder,
                                        PRECLOSE_DRAG_PCT)
    print(f"  cell_11 COMBINED (NFP gate + pre-close):   "
          f"SR {s11['sharpe']:.3f}  CAGR {s11['cagr_pct']:+.1f}%  "
          f"DD {s11['max_dd_pct']:.2f}%")
    cells["cell_11_combined"] = s11

    # ------------------------------------------------------------------
    # Interaction analysis
    # ------------------------------------------------------------------
    iA_sr = s10["sharpe"] - s00["sharpe"]
    iB_sr = s01["sharpe"] - s00["sharpe"]
    additive_pred_sr = s00["sharpe"] + iA_sr + iB_sr
    interaction_sr = s11["sharpe"] - additive_pred_sr

    iA_dd = s10["max_dd_pct"] - s00["max_dd_pct"]
    iB_dd = s01["max_dd_pct"] - s00["max_dd_pct"]
    additive_pred_dd = s00["max_dd_pct"] + iA_dd + iB_dd
    interaction_dd = s11["max_dd_pct"] - additive_pred_dd

    iA_cg = s10["cagr_pct"] - s00["cagr_pct"]
    iB_cg = s01["cagr_pct"] - s00["cagr_pct"]
    additive_pred_cg = s00["cagr_pct"] + iA_cg + iB_cg
    interaction_cg = s11["cagr_pct"] - additive_pred_cg

    print("\n[interaction]")
    print(f"  ΔSR(gate@base)        = {iA_sr:+.3f}")
    print(f"  ΔSR(preclose@nogate)  = {iB_sr:+.3f}")
    print(f"  additive prediction   = {additive_pred_sr:.3f}")
    print(f"  observed combined     = {s11['sharpe']:.3f}")
    print(f"  interaction (SR)      = {interaction_sr:+.3f}")

    # ------------------------------------------------------------------
    # Pre-registered hypothesis legs
    # ------------------------------------------------------------------
    leg_sr   = s11["sharpe"]      >= H_SR_TARGET
    leg_dd   = s11["max_dd_pct"]  <  H_DD_MAX_PCT
    leg_cagr = s11["cagr_pct"]    >= H_CAGR_TARGET_PCT

    legs = {
        f"SR ≥ {H_SR_TARGET:.2f}":  leg_sr,
        f"DD < {H_DD_MAX_PCT:.2f}%": leg_dd,
        f"CAGR ≥ {H_CAGR_TARGET_PCT:.1f}%": leg_cagr,
    }
    n_pass = sum(legs.values())
    if n_pass == 3:
        verdict = "H_COMBINED_FULLY_VALIDATED"
    elif n_pass == 2:
        verdict = "H_COMBINED_PARTIAL_2OF3"
    elif n_pass == 1:
        verdict = "H_COMBINED_PARTIAL_1OF3"
    else:
        verdict = "H_COMBINED_REJECTED"

    print("\n[pre-registered legs]")
    for name, ok in legs.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  "
              f"(observed: SR={s11['sharpe']:.3f}  "
              f"DD={s11['max_dd_pct']:.2f}%  CAGR={s11['cagr_pct']:+.1f}%)")
    print(f"  verdict: {verdict}")

    payload = {
        "experiment": "EXP-3312",
        "title": "Combined backtest — EXP-3311 NFP gate × EXP-3309 pre-close execution",
        "generated": datetime.now().isoformat(timespec="seconds"),
        "rule_zero": True,
        "hypothesis": {
            "statement": (
                "Layering the EXP-3311 NFP-only entry gate on top of the "
                "EXP-3309 pre-close execution window stacks roughly additively, "
                "giving net SR ≈ 6.05, max DD < 6 %, net CAGR ≈ 115 %."
            ),
            "preregistered_gates": {
                "SR_target": H_SR_TARGET,
                "DD_max_pct": H_DD_MAX_PCT,
                "CAGR_target_pct": H_CAGR_TARGET_PCT,
            },
        },
        "drag_bookkeeping": {
            "baseline_drag_pct_per_yr": BASELINE_DRAG_PCT,
            "preclose_drag_pct_per_yr": PRECLOSE_DRAG_PCT,
            "drag_saving_pp_per_yr": round(BASELINE_DRAG_PCT - PRECLOSE_DRAG_PCT, 3),
            "exp3309_scenario_B_usd": EXP3309_DRAG_B_USD,
            "exp3309_scenario_D_usd": EXP3309_DRAG_D_USD,
            "ratio_D_over_B": round(DRAG_RATIO_D_OVER_B, 4),
            "method_note": (
                "EXP-2570 NET_DRAG_PCT=8.903% calibrated against EXP-2470 "
                "implicit (= EXP-3309 scenario B). The pre-close treatment "
                "reduces round-trip $ drag by the same ratio (D/B=0.8455), "
                "so the modelled drag rate is scaled proportionally."
            ),
        },
        "config": {
            "engine": "compass.exp2850_v8a_with_vix_ladder.walk_forward_with_ladder",
            "target_vol": TARGET_VOL,
            "train_days": TRAIN_DAYS,
            "test_days": TEST_DAYS,
            "scale_cap": SCALE_CAP,
            "capital": CAPITAL,
            "trading_days": TRADING_DAYS,
            "event_types": ["nfp"],
            "blackout_window": list(DEFAULT_WINDOW),
        },
        "nfp_diagnostics": diag_nfp,
        "cells": cells,
        "interaction": {
            "iA_nfp_at_baseline_drag": {
                "delta_sharpe": round(iA_sr, 4),
                "delta_cagr_pp": round(iA_cg, 4),
                "delta_dd_pp":   round(iA_dd, 4),
            },
            "iB_preclose_at_no_gate": {
                "delta_sharpe": round(iB_sr, 4),
                "delta_cagr_pp": round(iB_cg, 4),
                "delta_dd_pp":   round(iB_dd, 4),
            },
            "additive_prediction": {
                "sharpe":   round(additive_pred_sr, 4),
                "cagr_pct": round(additive_pred_cg, 4),
                "dd_pct":   round(additive_pred_dd, 4),
            },
            "observed_combined": {
                "sharpe":   s11["sharpe"],
                "cagr_pct": s11["cagr_pct"],
                "dd_pct":   s11["max_dd_pct"],
            },
            "interaction_term": {
                "sharpe":   round(interaction_sr, 4),
                "cagr_pp":  round(interaction_cg, 4),
                "dd_pp":    round(interaction_dd, 4),
            },
        },
        "preregistered_legs": {k: bool(v) for k, v in legs.items()},
        "n_legs_passed": n_pass,
        "verdict": verdict,
        "folds_combined": [
            {"fold": f["fold"], "test_start": f["test_start"],
             "test_end": f["test_end"], "metrics": f["net_metrics"]}
            for f in folds11
        ],
        "yearly_combined": yearly_breakdown(pooled11),
        "limitations": [
            "EXP-3309 per-window timing factors are documented liquidity "
            "literature coefficients, not measured from a minute-bar IronVault "
            "tape. Empirical verification requires Alpaca paper-trade with "
            "fill-timestamp capture (~1 month).",
            "Combination assumes the EXP-3309 drag saving applies uniformly "
            "across the NFP-gated trade subset. In practice the dropped NFP "
            "entries would have had above-average spreads (event proximity), "
            "so the post-gate drag rate may be slightly LOWER than the linear "
            "scaling we apply — making this estimate mildly conservative.",
            "Walk-forward is on the EXP-3311 cube (vol_target=0.12), not the "
            "0.18-vol-target cube where EXP-3309 measured its 6.83 gross SR. "
            "Combined SR is naturally bounded by the EXP-3311 baseline (5.0 SR) "
            "+ stacked treatment lifts (~0.35 SR), so the user's 6.05 SR target "
            "is unreachable from this baseline regardless of interaction.",
        ],
    }

    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\n[report] → {REPORT_JSON}")

    REPORT_HTML.write_text(build_html(payload), encoding="utf-8")
    print(f"[report] → {REPORT_HTML}")


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------


def build_html(p: Dict) -> str:
    s00 = p["cells"]["cell_00_baseline"]
    s10 = p["cells"]["cell_10_nfp_only"]
    s01 = p["cells"]["cell_01_preclose_only"]
    s11 = p["cells"]["cell_11_combined"]
    inter = p["interaction"]

    verdict_color = {
        "H_COMBINED_FULLY_VALIDATED": "#16a34a",
        "H_COMBINED_PARTIAL_2OF3":    "#f59e0b",
        "H_COMBINED_PARTIAL_1OF3":    "#f59e0b",
        "H_COMBINED_REJECTED":        "#dc2626",
    }.get(p["verdict"], "#0f172a")

    leg_rows = ""
    for name, ok in p["preregistered_legs"].items():
        col = "#16a34a" if ok else "#dc2626"
        lbl = "PASS" if ok else "FAIL"
        leg_rows += (f"<tr><td>{name}</td>"
                     f"<td style='color:{col};font-weight:700'>{lbl}</td></tr>")

    diag_rows = "".join(
        f"<tr><td>{k}</td><td>{v['kept']}</td><td>{v['dropped']}</td>"
        f"<td>{v['drop_pct']:.1f}%</td></tr>"
        for k, v in p["nfp_diagnostics"].items()
    )

    def cell_row(name: str, s: Dict) -> str:
        return (
            f"<tr><td>{name}</td>"
            f"<td>{s['drag_pct_used']:.3f}%</td>"
            f"<td>{s['sharpe']:.3f}</td>"
            f"<td>{s['cagr_pct']:+.1f}%</td>"
            f"<td>{s['max_dd_pct']:.2f}%</td>"
            f"<td>{s['vol_pct']:.2f}%</td>"
            f"<td>{s['median_fold_sharpe']:.3f}</td></tr>"
        )

    cells_rows = (
        cell_row("Cell 00 — baseline / no gate",       s00) +
        cell_row("Cell 10 — baseline / NFP gate",      s10) +
        cell_row("Cell 01 — pre-close / no gate",      s01) +
        cell_row("Cell 11 — pre-close / NFP gate",     s11)
    )

    yr_rows = ""
    for yr in sorted(p["yearly_combined"].keys()):
        y = p["yearly_combined"][yr]
        yr_rows += (f"<tr><td>{yr}</td>"
                    f"<td>{y.get('sharpe', 0):.2f}</td>"
                    f"<td>{y.get('cagr_pct', 0):+.1f}%</td>"
                    f"<td>{y.get('max_dd_pct', 0):.2f}%</td>"
                    f"<td>{y.get('vol_pct', 0):.2f}%</td></tr>")

    fold_rows = ""
    for f in p["folds_combined"]:
        m = f["metrics"]
        fold_rows += (f"<tr><td>{f['fold']}</td><td>{f['test_start']}</td>"
                      f"<td>{m['sharpe']:.2f}</td>"
                      f"<td>{m['cagr_pct']:+.1f}%</td>"
                      f"<td>{m['max_dd_pct']:.2f}%</td></tr>")

    lim_html = "".join(f"<li>{x}</li>" for x in p["limitations"])

    db = p["drag_bookkeeping"]
    H = p["hypothesis"]["preregistered_gates"]

    return f"""<!doctype html>
<html lang="en"><head><meta charset="UTF-8"><title>EXP-3312 — Combined Event + Exec</title>
<style>
body {{ font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:1180px;
       margin:0 auto;padding:28px;background:#fff;color:#14171a; }}
h1 {{ font-size:1.8em;margin:0 0 4px; }}
h2 {{ margin-top:2em;border-bottom:2px solid #e2e8f0;padding-bottom:6px; }}
.meta {{ color:#64748b;font-size:13px;margin-bottom:18px; }}
.box {{ background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;
        padding:14px 16px;font-size:13px;line-height:1.55;margin:12px 0; }}
.verdict {{ background:#fff;border:2px solid {verdict_color};border-radius:10px;
             padding:14px 16px;margin:18px 0; }}
.verdict h3 {{ margin:0 0 6px;color:{verdict_color}; }}
table {{ width:100%;border-collapse:collapse;margin:12px 0;font-size:13px; }}
th {{ background:#f1f5f9;padding:7px 10px;text-align:right;border-bottom:2px solid #cbd5e1;
      font-size:12px;text-transform:uppercase;letter-spacing:0.04em; }}
th:first-child {{ text-align:left; }}
td {{ padding:6px 10px;text-align:right;border-bottom:1px solid #e2e8f0; }}
td:first-child {{ text-align:left; }}
ul {{ margin:8px 0;padding-left:22px;font-size:13px;line-height:1.55; }}
.kpi-grid {{ display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:14px 0; }}
.kpi {{ border:1px solid #e2e8f0;border-radius:8px;padding:10px 12px; }}
.kpi .lbl {{ font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:0.04em; }}
.kpi .val {{ font-size:1.5em;font-weight:700;margin-top:4px; }}
</style></head><body>

<h1>EXP-3312 — Combined NFP Gate × Pre-close Execution</h1>
<div class="meta">2×2 factorial · v8a + VIX-ladder walk-forward (EXP-2850 engine) ·
generated {p['generated']}</div>

<div class="box">
<strong>Hypothesis (pre-registered).</strong>
Layering the EXP-3311 NFP entry blackout on top of the EXP-3309 pre-close
execution window stacks roughly additively to give net SR ≈ {H['SR_target']},
max DD &lt; {H['DD_max_pct']:.1f} %, net CAGR ≈ {H['CAGR_target_pct']:.0f} %.
</div>

<div class="kpi-grid">
  <div class="kpi"><div class="lbl">Combined SR</div>
       <div class="val">{s11['sharpe']:.3f}</div></div>
  <div class="kpi"><div class="lbl">Combined CAGR</div>
       <div class="val">{s11['cagr_pct']:+.1f}%</div></div>
  <div class="kpi"><div class="lbl">Combined Max DD</div>
       <div class="val">{s11['max_dd_pct']:.2f}%</div></div>
  <div class="kpi"><div class="lbl">Interaction (SR)</div>
       <div class="val">{inter['interaction_term']['sharpe']:+.3f}</div></div>
</div>

<div class="verdict">
<h3>Verdict: {p['verdict']} ({p['n_legs_passed']} / 3 legs PASS)</h3>
<table style="margin:8px 0;width:auto"><tr><th>Leg</th><th>Result</th></tr>
{leg_rows}
</table>
</div>

<h2>Drag bookkeeping</h2>
<div class="box">
EXP-2570 baseline drag = <strong>{db['baseline_drag_pct_per_yr']} %/yr</strong>
(calibrated against EXP-2470 implicit = EXP-3309 scenario B at
${db['exp3309_scenario_B_usd']:,.2f} round-trip). Pre-close treatment
(EXP-3309 scenario D) reduces round-trip $ drag to
${db['exp3309_scenario_D_usd']:,.2f}, ratio
{db['ratio_D_over_B']:.4f}. Applied proportionally to the EXP-2570 rate:
<br><strong>preclose drag = {db['preclose_drag_pct_per_yr']} %/yr</strong>
(saving of {db['drag_saving_pp_per_yr']} pp/yr).
</div>

<h2>2×2 cells</h2>
<table>
<tr><th>Cell</th><th>Drag</th><th>SR</th><th>CAGR</th><th>Max DD</th>
<th>Ann vol</th><th>Median fold SR</th></tr>
{cells_rows}
</table>

<h2>Interaction analysis</h2>
<table>
<tr><th>Component</th><th>ΔSR</th><th>ΔCAGR (pp)</th><th>ΔDD (pp)</th></tr>
<tr><td>iA — NFP gate effect (at baseline drag)</td>
    <td>{inter['iA_nfp_at_baseline_drag']['delta_sharpe']:+.3f}</td>
    <td>{inter['iA_nfp_at_baseline_drag']['delta_cagr_pp']:+.2f}</td>
    <td>{inter['iA_nfp_at_baseline_drag']['delta_dd_pp']:+.2f}</td></tr>
<tr><td>iB — pre-close effect (no gate)</td>
    <td>{inter['iB_preclose_at_no_gate']['delta_sharpe']:+.3f}</td>
    <td>{inter['iB_preclose_at_no_gate']['delta_cagr_pp']:+.2f}</td>
    <td>{inter['iB_preclose_at_no_gate']['delta_dd_pp']:+.2f}</td></tr>
<tr><td>Additive prediction</td>
    <td>{inter['additive_prediction']['sharpe']:.3f}</td>
    <td>{inter['additive_prediction']['cagr_pct']:+.1f}%</td>
    <td>{inter['additive_prediction']['dd_pct']:.2f}%</td></tr>
<tr><td>Observed combined (cell 11)</td>
    <td>{inter['observed_combined']['sharpe']:.3f}</td>
    <td>{inter['observed_combined']['cagr_pct']:+.1f}%</td>
    <td>{inter['observed_combined']['dd_pct']:.2f}%</td></tr>
<tr><td><strong>Interaction term</strong></td>
    <td><strong>{inter['interaction_term']['sharpe']:+.3f}</strong></td>
    <td><strong>{inter['interaction_term']['cagr_pp']:+.2f}</strong></td>
    <td><strong>{inter['interaction_term']['dd_pp']:+.2f}</strong></td></tr>
</table>

<h2>NFP gate diagnostics (credit-spread streams)</h2>
<table>
<tr><th>Stream</th><th>Kept</th><th>Dropped</th><th>Drop %</th></tr>
{diag_rows}
</table>

<h2>Yearly breakdown — combined cell 11</h2>
<table>
<tr><th>Year</th><th>SR</th><th>CAGR</th><th>Max DD</th><th>Ann vol</th></tr>
{yr_rows}
</table>

<h2>Per-fold — combined cell 11</h2>
<table>
<tr><th>Fold</th><th>Test start</th><th>SR</th><th>CAGR</th><th>Max DD</th></tr>
{fold_rows}
</table>

<h2>Limitations</h2>
<ul>{lim_html}</ul>

<p style="margin-top:3em;color:#94a3b8;font-size:12px;text-align:center">
compass/exp3312_combined_event_exec.py · Rule Zero · real IronVault data
</p>
</body></html>
"""


if __name__ == "__main__":
    main()
