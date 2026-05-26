"""EXP-3303b — Per-stream selective regime gate (v8a).

Follow-up to EXP-3303 (portfolio-level gate produced -0.04 gross SR but
-2.05% max DD). EXP-3151 showed exp1220 contributes 18.7% of v8a Sharpe
and qqq_cs another 8.2%; the other 6 streams (xlf_cs, xli_cs, gld_cal,
slv_cal, cross_vol, v5_hedge) carry the rest and have near-zero SPY-β
(EXP-3151 calibration). The portfolio gate was too blunt — it cut
leverage on the carry streams during stress days where they earn most.

Mechanic
--------
Identical composite stress score as EXP-3303
(VVIX + SKEW + VIX-3M-spread, 63d trailing z, no look-ahead). Apply
the gate ONLY to {exp1220, qqq_cs}; leave the other 6 streams at full
leverage even on high-composite-stress days.

Implementation: per-day per-stream leverage matrix L applied as a
Hadamard product to the OOS test slice inside walk-forward. Training
data is unchanged so LW weights match the baseline run exactly.

Compared metrics (full 2020-12 .. 2025-10 OOS pooled):
  1. Gross + net Sharpe
  2. Max DD
  3. Regime-transition post-DD (sum across up-crossing events)
  4. Per-stream "gated days" count

Outputs
  compass/reports/exp3303b_per_stream_gate.json
  compass/reports/exp3303b_per_stream_gate.html
"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from compass.exp2600_north_star_v8 import (  # noqa: E402
    build_cubes,
    fold_metrics,
    apply_net_drag,
    NET_DRAG_BPS,
    NET_DRAG_PCT,
    TRAIN_DAYS,
    TEST_DAYS,
    TRADING_DAYS,
)
from compass.exp3303_regime_transition_dd import (  # noqa: E402
    fetch_regime_features,
    build_composite_stress,
    compute_transition_dd,
    find_upcrossings,
    TRANSITION_DD_RADIUS,
)

REPORT_JSON = ROOT / "compass" / "reports" / "exp3303b_per_stream_gate.json"
REPORT_HTML = ROOT / "compass" / "reports" / "exp3303b_per_stream_gate.html"

V8A_TARGET_VOL = 0.18
GATED_STREAMS = ["exp1220", "qqq_cs"]   # SPX-VRP-sensitive; EXP-3151 §verdict
THETAS = [1.0, 1.5, 2.0, 2.5]
GATE_LEVERAGES = [0.0, 0.3, 0.5]


# ── Per-stream leverage matrix ───────────────────────────────────────


def build_leverage_matrix(
    cube: pd.DataFrame, composite: pd.Series,
    theta: float, gate_leverage: float, gated_streams: List[str],
) -> pd.DataFrame:
    """L[t, s] = gate_leverage if (s in gated_streams and composite[t-1] > θ)
                else 1.0
    Reindexed to cube.index. NaN composite (warm-up) → 1.0."""
    cols = list(cube.columns)
    comp_lag = composite.shift(1).reindex(cube.index)
    stress = (comp_lag > theta).fillna(False).to_numpy()
    L = np.ones((len(cube), len(cols)), dtype=float)
    for s in gated_streams:
        if s in cols:
            j = cols.index(s)
            L[stress, j] = gate_leverage
    return pd.DataFrame(L, index=cube.index, columns=cols)


# ── Walk-forward with OOS-only leverage matrix ───────────────────────


def walk_forward_lw_with_gate(
    cube: pd.DataFrame, leverage: pd.DataFrame,
    target_vol: float, scale_cap: float = 20.0,
) -> Tuple[pd.Series, List[Dict]]:
    """Same as exp2600.walk_forward_lw but applies per-day per-stream
    leverage to the test slice ONLY (training is on the unmodified cube)."""
    from compass.exp2360_robust_cov import cov_ledoit_wolf, risk_parity_weights

    cols = list(cube.columns)
    n = len(cube)
    pooled_idx: List = []
    pooled_vals: List[float] = []
    fold_rows: List[Dict] = []

    i = TRAIN_DAYS
    fold_ix = 0
    while i + TEST_DAYS <= n:
        train = cube.iloc[i - TRAIN_DAYS:i]
        test = cube.iloc[i:i + TEST_DAYS]
        L_test = leverage.iloc[i:i + TEST_DAYS]
        Sigma = cov_ledoit_wolf(train.values)
        w = risk_parity_weights(Sigma)
        train_port = train.values @ w
        train_vol = float(np.std(train_port, ddof=1)) * math.sqrt(TRADING_DAYS)
        scale = target_vol / train_vol if train_vol > 1e-10 else 1.0
        scale = float(np.clip(scale, 0.1, scale_cap))
        # Per-day per-stream leverage applied to test slice only
        gated_test = test.values * L_test.values
        raw_oos = pd.Series(gated_test @ w * scale, index=test.index)
        fold_rows.append({
            "fold": fold_ix,
            "test_start": str(test.index[0].date()),
            "test_end": str(test.index[-1].date()),
            "vol_scale": round(scale, 4),
            "weights": {cols[j]: round(float(w[j]), 4) for j in range(len(cols))},
        })
        pooled_idx.extend(test.index.tolist())
        pooled_vals.extend(raw_oos.tolist())
        i += TEST_DAYS
        fold_ix += 1

    return pd.Series(pooled_vals, index=pooled_idx, dtype=float), fold_rows


# ── Per-stream gated-day count (over OOS only) ───────────────────────


def per_stream_gated_days(
    leverage: pd.DataFrame, oos_index: pd.Index,
) -> Dict[str, Dict]:
    L = leverage.reindex(oos_index)
    out: Dict[str, Dict] = {}
    for c in L.columns:
        s = L[c]
        n_gated = int((s < 1.0 - 1e-9).sum())
        n_full_off = int((s < 1e-9).sum())
        out[c] = {
            "days_gated": n_gated,
            "days_full_off": n_full_off,
            "pct_gated": round(100 * n_gated / len(s), 3),
        }
    return out


# ── Main ─────────────────────────────────────────────────────────────


def main() -> None:
    print("=" * 72)
    print("EXP-3303b — Per-stream selective regime gate (exp1220, qqq_cs)")
    print("=" * 72)

    print("\n[1/5] Building v8a cube + baseline walk-forward (no gate)…")
    cubes = build_cubes()
    v8a = cubes["v8a_add_qqq"]
    # Baseline: leverage matrix of ones
    L_ones = pd.DataFrame(
        np.ones(v8a.shape), index=v8a.index, columns=v8a.columns,
    )
    base_pooled, base_folds = walk_forward_lw_with_gate(
        v8a, L_ones, target_vol=V8A_TARGET_VOL,
    )
    base_pooled = base_pooled.dropna()
    base_gross = fold_metrics(base_pooled)
    base_net = fold_metrics(apply_net_drag(base_pooled))
    print(f"      pooled OOS: {base_pooled.index[0].date()}..{base_pooled.index[-1].date()}  "
          f"({len(base_pooled)} days, {len(base_folds)} folds)")
    print(f"      baseline gross: SR {base_gross['sharpe']:.3f}  "
          f"CAGR {base_gross['cagr_pct']:.1f}%  DD {base_gross['max_dd_pct']:.2f}%")
    print(f"      baseline net  : SR {base_net['sharpe']:.3f}  "
          f"CAGR {base_net['cagr_pct']:.1f}%  DD {base_net['max_dd_pct']:.2f}%")

    print("\n[2/5] Loading regime composite (cached from EXP-3303)…")
    feats_raw = fetch_regime_features(v8a.index[0], v8a.index[-1])
    feats = build_composite_stress(feats_raw)
    composite = feats.reindex(v8a.index).ffill()["composite_stress"]
    print(f"      composite percentiles "
          f"p50={composite.quantile(0.50):.2f}  "
          f"p90={composite.quantile(0.90):.2f}  "
          f"p95={composite.quantile(0.95):.2f}  "
          f"p99={composite.quantile(0.99):.2f}")

    # ── Sweep ──
    print("\n[3/5] Per-stream gate sweep "
          f"(gated streams: {GATED_STREAMS})…")
    print(f"{'θ':>5}  {'gate':>5}  "
          f"{'gross_SR':>9}  {'net_SR':>7}  {'CAGR':>7}  "
          f"{'DD':>6}  {'trans_DD':>9}  "
          f"{'exp1220%':>9}  {'qqq_cs%':>8}  {'n_evt':>6}")
    sweep: List[Dict] = []
    for theta in THETAS:
        events_count = len(find_upcrossings(composite, theta))
        for g in GATE_LEVERAGES:
            L = build_leverage_matrix(v8a, composite, theta, g, GATED_STREAMS)
            pooled, _folds = walk_forward_lw_with_gate(
                v8a, L, target_vol=V8A_TARGET_VOL,
            )
            pooled = pooled.dropna()
            gross_m = fold_metrics(pooled)
            net_m = fold_metrics(apply_net_drag(pooled))
            _evts, total_trans_dd = compute_transition_dd(pooled, composite, theta)
            stream_stats = per_stream_gated_days(L, pooled.index)
            sweep.append({
                "theta": theta,
                "gate_leverage": g,
                "gross": gross_m,
                "net": net_m,
                "transition_post_dd_pct_total": round(total_trans_dd, 3),
                "transition_events": events_count,
                "per_stream": stream_stats,
            })
            print(f"{theta:>5.1f}  {g:>5.2f}  "
                  f"{gross_m['sharpe']:>9.3f}  {net_m['sharpe']:>7.3f}  "
                  f"{net_m['cagr_pct']:>6.1f}%  "
                  f"{gross_m['max_dd_pct']:>5.2f}%  "
                  f"{total_trans_dd:>8.2f}%  "
                  f"{stream_stats['exp1220']['pct_gated']:>8.2f}%  "
                  f"{stream_stats['qqq_cs']['pct_gated']:>7.2f}%  "
                  f"{events_count:>6d}")

    # ── Pick best (max net SR among configs with DD ≤ baseline) ──
    base_dd = abs(base_gross["max_dd_pct"])
    candidates = [s for s in sweep if abs(s["gross"]["max_dd_pct"]) <= base_dd]
    best = max(
        candidates if candidates else sweep,
        key=lambda s: s["net"]["sharpe"],
    )
    sr_lift_g = best["gross"]["sharpe"] - base_gross["sharpe"]
    sr_lift_n = best["net"]["sharpe"] - base_net["sharpe"]
    dd_delta = best["gross"]["max_dd_pct"] - base_gross["max_dd_pct"]
    print(f"\n      Best (net SR, DD ≤ baseline): "
          f"θ={best['theta']:.1f}  gate={best['gate_leverage']:.2f}  "
          f"net SR {best['net']['sharpe']:.3f}  "
          f"DD {best['gross']['max_dd_pct']:.2f}%")

    # ── Detailed top-event table under best gate ──
    print(f"\n[4/5] Top-10 transition events under best gate "
          f"(θ={best['theta']:.1f}, gate={best['gate_leverage']:.2f})…")
    L_best = build_leverage_matrix(
        v8a, composite, best["theta"], best["gate_leverage"], GATED_STREAMS,
    )
    gated_pooled, _ = walk_forward_lw_with_gate(
        v8a, L_best, target_vol=V8A_TARGET_VOL,
    )
    gated_pooled = gated_pooled.dropna()
    base_evts, base_trans_dd = compute_transition_dd(base_pooled, composite, best["theta"])
    gated_evts, gated_trans_dd = compute_transition_dd(gated_pooled, composite, best["theta"])
    top = sorted(base_evts, key=lambda e: -e.post_drawdown_pct)[:10]
    print(f"      n_events: {len(base_evts)}")
    print(f"      baseline ΣDD post-transition: {base_trans_dd:.2f}%")
    print(f"      gated     ΣDD post-transition: {gated_trans_dd:.2f}%")
    print(f"      reduction: {(base_trans_dd - gated_trans_dd):+.2f}% absolute, "
          f"{(1 - gated_trans_dd / base_trans_dd) * 100 if base_trans_dd > 1e-9 else 0:+.1f}% relative")
    top_events_payload = []
    for e in top:
        post_g = next((ge.post_drawdown_pct for ge in gated_evts if ge.date == e.date), 0.0)
        delta = post_g - e.post_drawdown_pct
        print(f"        {e.date.date()}  composite={e.composite_at:5.2f}  "
              f"baseline post-DD {e.post_drawdown_pct:5.2f}%  "
              f"→ gated {post_g:5.2f}%  Δ {delta:+5.2f}%")
        top_events_payload.append({
            "date": str(e.date.date()),
            "composite": e.composite_at,
            "baseline_post_dd_pct": e.post_drawdown_pct,
            "gated_post_dd_pct": post_g,
        })

    # ── Side-by-side comparison vs EXP-3303 portfolio gate ──
    print("\n[5/5] Verdict (per-stream selective gate vs portfolio-wide gate)")
    print("-" * 72)
    print(f"  Baseline gross SR : {base_gross['sharpe']:.3f}")
    print(f"  Baseline max DD   : {base_gross['max_dd_pct']:.2f}%")
    print(f"  Baseline ΣDD trans: {base_trans_dd:.2f}%")
    print()
    print(f"  Best per-stream:  θ={best['theta']:.1f}  gate={best['gate_leverage']:.2f}")
    print(f"    Δ gross SR     : {sr_lift_g:+.3f}  (lit. predicted +0.20 to +0.40)")
    print(f"    Δ net SR       : {sr_lift_n:+.3f}")
    print(f"    Δ max DD       : {dd_delta:+.2f}%  (negative = improvement)")
    print(f"    Δ ΣDD trans    : {(gated_trans_dd - base_trans_dd):+.2f}%")
    print(f"    days gated (exp1220): "
          f"{best['per_stream']['exp1220']['pct_gated']:.2f}%   "
          f"(qqq_cs): {best['per_stream']['qqq_cs']['pct_gated']:.2f}%")

    if sr_lift_g >= 0.20:
        verdict = "IN_LIT_BAND"
        print("  ✓ per-stream gate produces ≥+0.20 gross SR lift — confirms literature.")
    elif sr_lift_g > 0.0:
        verdict = "POSITIVE_BUT_BELOW_LIT_BAND"
        print("  ◐ small positive lift — better than portfolio-wide gate, "
              "below lit band.")
    elif sr_lift_g >= -0.05:
        verdict = "FLAT_WITH_DD_BENEFIT"
        print("  ◐ Sharpe-neutral but DD-reducing — useful for risk-bound mandates.")
    else:
        verdict = "NO_LIFT"
        print("  ✗ per-stream gate does not improve gross SR.")

    payload = {
        "experiment": "EXP-3303b",
        "title": "Per-stream selective regime gate (exp1220 + qqq_cs only)",
        "generated": datetime.now().isoformat(timespec="seconds"),
        "rule_zero": True,
        "spec_source": (
            "Follow-up to EXP-3303; derived from EXP-3151 finding that "
            "exp1220 + qqq_cs together contribute 26.9% of v8a Sharpe "
            "and the other 6 streams 73.1%. Hypothesis: the EXP-3303 "
            "portfolio-wide gate was blunt — gating only the SPX-VRP-"
            "sensitive streams should preserve the carry-stream upside "
            "on stress days."
        ),
        "config": {
            "v8a_target_vol": V8A_TARGET_VOL,
            "gated_streams": GATED_STREAMS,
            "thetas": THETAS,
            "gate_leverages": GATE_LEVERAGES,
            "transition_dd_radius_days": TRANSITION_DD_RADIUS,
            "drag_bps": NET_DRAG_BPS,
        },
        "baseline": {
            "n_days": len(base_pooled),
            "gross": base_gross,
            "net": base_net,
            "transition_post_dd_pct_total": round(base_trans_dd, 3),
            "n_transition_events": len(base_evts),
        },
        "sweep": sweep,
        "best": best,
        "best_top_events": top_events_payload,
        "best_metrics_vs_baseline": {
            "delta_gross_sharpe": round(sr_lift_g, 4),
            "delta_net_sharpe": round(sr_lift_n, 4),
            "delta_max_dd_pct": round(dd_delta, 4),
            "delta_transition_dd_pct": round(gated_trans_dd - base_trans_dd, 4),
            "transition_dd_reduction_relative_pct": round(
                (1 - gated_trans_dd / base_trans_dd) * 100
                if base_trans_dd > 1e-9 else 0.0, 3,
            ),
        },
        "comparison_to_exp3303_portfolio_gate": {
            "exp3303_best_delta_gross_sharpe": -0.042,
            "exp3303_best_delta_max_dd_pct": -2.05,
            "note": "EXP-3303 portfolio gate at θ=2.5 / gate=0.50 over the same window.",
        },
        "verdict": verdict,
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\n[report] → {REPORT_JSON}")

    REPORT_HTML.write_text(build_html(payload), encoding="utf-8")
    print(f"[report] → {REPORT_HTML}")


# ── HTML ─────────────────────────────────────────────────────────────


def build_html(p: Dict) -> str:
    cfg = p["config"]
    base = p["baseline"]
    best = p["best"]
    cmp_ = p["best_metrics_vs_baseline"]

    color = {
        "IN_LIT_BAND":     "#16a34a",
        "POSITIVE_BUT_BELOW_LIT_BAND": "#16a34a",
        "FLAT_WITH_DD_BENEFIT": "#f59e0b",
        "NO_LIFT":         "#dc2626",
    }.get(p["verdict"], "#64748b")

    sweep_rows = ""
    for s in p["sweep"]:
        sg = s["gross"]
        sn = s["net"]
        is_best = (s["theta"] == best["theta"]
                   and s["gate_leverage"] == best["gate_leverage"])
        css = "best" if is_best else ""
        sweep_rows += (
            f"<tr class='{css}'>"
            f"<td>{s['theta']:.1f}</td>"
            f"<td>{s['gate_leverage']:.2f}</td>"
            f"<td>{sg['sharpe']:.3f}</td>"
            f"<td>{sn['sharpe']:.3f}</td>"
            f"<td>{sn['cagr_pct']:+.1f}%</td>"
            f"<td>{sg['max_dd_pct']:.2f}%</td>"
            f"<td>{s['transition_post_dd_pct_total']:.2f}%</td>"
            f"<td>{s['per_stream']['exp1220']['pct_gated']:.2f}%</td>"
            f"<td>{s['per_stream']['qqq_cs']['pct_gated']:.2f}%</td>"
            f"<td>{s['transition_events']}</td>"
            f"</tr>"
        )

    # Per-stream gated days under best
    ps_rows = ""
    for c, st in best["per_stream"].items():
        gated = "YES" if c in cfg["gated_streams"] else "no"
        ps_rows += (
            f"<tr><td>{c}</td><td>{gated}</td>"
            f"<td>{st['days_gated']}</td>"
            f"<td>{st['days_full_off']}</td>"
            f"<td>{st['pct_gated']:.2f}%</td></tr>"
        )

    event_rows = ""
    for e in p["best_top_events"]:
        delta = e["gated_post_dd_pct"] - e["baseline_post_dd_pct"]
        ec = "#16a34a" if delta < -0.01 else ("#dc2626" if delta > 0.01 else "#64748b")
        event_rows += (
            f"<tr><td>{e['date']}</td>"
            f"<td>{e['composite']:.2f}</td>"
            f"<td>{e['baseline_post_dd_pct']:.2f}%</td>"
            f"<td>{e['gated_post_dd_pct']:.2f}%</td>"
            f"<td style='color:{ec};font-weight:700'>{delta:+.2f}%</td>"
            f"</tr>"
        )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>EXP-3303b — Per-stream regime gate</title>
<style>
body{{font-family:-apple-system,sans-serif;max-width:1280px;margin:0 auto;padding:28px;background:#fff;color:#1e293b;}}
h1{{font-size:1.7em;color:#0f172a;}}
h2{{margin-top:2em;border-bottom:2px solid #e2e8f0;padding-bottom:8px;color:#334155;}}
.muted{{color:#64748b;font-size:0.85em;}}
.caveat{{background:#fef3c7;border:1px solid #f59e0b;border-radius:8px;padding:14px;margin:16px 0;font-size:0.9rem;line-height:1.55;}}
.sources{{background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:14px;font-size:0.84rem;line-height:1.6;}}
.verdict{{background:#fff;border:2px solid {color};border-radius:8px;padding:18px;margin:18px 0;}}
.verdict .badge{{display:inline-block;padding:5px 14px;border-radius:14px;color:#fff;background:{color};font-weight:700;font-size:0.86rem;}}
table{{width:100%;border-collapse:collapse;margin:12px 0;font-size:0.85em;}}
th{{background:#f1f5f9;padding:8px 9px;text-align:right;border-bottom:2px solid #cbd5e1;font-size:0.7em;text-transform:uppercase;}}
th:first-child{{text-align:left;}}
td{{padding:7px 9px;text-align:right;border-bottom:1px solid #e2e8f0;}}
td:first-child{{text-align:left;font-weight:600;color:#475569;}}
tr.best{{background:#ecfdf5;font-weight:600;}}
.kv{{display:grid;grid-template-columns:repeat(2,1fr);gap:6px 18px;font-size:0.9em;margin:10px 0;}}
.kv b{{color:#475569;}}
</style></head><body>

<h1>EXP-3303b — Per-stream selective regime gate (v8a)</h1>
<p class="muted">Gate active only on {", ".join(cfg['gated_streams'])} —
the two SPX-VRP-sensitive streams from EXP-3151. Other 6 streams
unchanged. {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<div class="sources">
<strong>Rule Zero.</strong> Same v8a cube and composite stress score as
EXP-3303 (real IronVault + Yahoo). Walk-forward LW risk-parity unchanged
from EXP-2600; per-stream leverage matrix L applied to the OOS test
slice only (training data unmodified, so LW weights match baseline
exactly). Gate uses composite_stress[t-1] (no look-ahead).
</div>

<div class="verdict">
<span class="badge">{p['verdict']}</span>
<div class="kv" style="margin-top:14px">
<div><b>Δ gross Sharpe</b></div><div>{cmp_['delta_gross_sharpe']:+.3f}</div>
<div><b>Δ net Sharpe</b></div><div>{cmp_['delta_net_sharpe']:+.3f}</div>
<div><b>Δ max DD</b></div><div>{cmp_['delta_max_dd_pct']:+.2f}%</div>
<div><b>Δ transition ΣDD</b></div><div>{cmp_['delta_transition_dd_pct']:+.2f}%
({cmp_['transition_dd_reduction_relative_pct']:+.1f}% rel.)</div>
<div><b>Best config</b></div>
<div>θ = {best['theta']:.1f}, gate_leverage = {best['gate_leverage']:.2f}</div>
<div><b>Baseline gross / best gross</b></div>
<div>{base['gross']['sharpe']:.3f} / {best['gross']['sharpe']:.3f}</div>
<div><b>vs EXP-3303 portfolio gate</b></div>
<div>per-stream Δ gross SR {cmp_['delta_gross_sharpe']:+.3f}
vs portfolio gate -0.042</div>
</div>
</div>

<h2>1. Gate sweep</h2>
<table>
<thead><tr>
<th>θ</th><th>gate lev</th>
<th>Gross SR</th><th>Net SR</th><th>Net CAGR</th><th>Max DD</th>
<th>Σ trans DD</th>
<th>exp1220 gated</th><th>qqq_cs gated</th><th># events</th>
</tr></thead>
<tbody>{sweep_rows}</tbody>
</table>
<p class="muted">"gated" % is fraction of OOS days where that stream's
leverage was reduced. The other 6 streams are always at full leverage.</p>

<h2>2. Per-stream gated-day count (best config)</h2>
<table>
<thead><tr>
<th>Stream</th><th>Gated</th><th>Days reduced</th><th>Days fully off</th><th>% of OOS</th>
</tr></thead>
<tbody>{ps_rows}</tbody>
</table>

<h2>3. Top-10 transition events (best gate vs baseline)</h2>
<table>
<thead><tr>
<th>Up-cross date</th><th>composite</th>
<th>baseline post-DD</th><th>gated post-DD</th><th>Δ</th>
</tr></thead>
<tbody>{event_rows}</tbody>
</table>

<p style="margin-top:3em;color:#94a3b8;font-size:0.78em;text-align:center">
compass/exp3303b_per_stream_gate.py · Rule Zero · real Yahoo + IronVault data
</p>
</body></html>"""


if __name__ == "__main__":
    main()
