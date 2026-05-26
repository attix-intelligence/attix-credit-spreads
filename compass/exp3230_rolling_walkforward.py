"""EXP-3230 — Rolling Walk-Forward Robustness (1-month step).

Motivation
----------
EXP-2280 ran a 20-fold yearly walk-forward on v6 (equal_risk_15%).
EXP-3230 tests temporal stability of the v8a portfolio at MONTHLY
granularity rather than yearly: 12-month train / 3-month test, rolling
forward by 1 month. This produces ~57 overlapping folds across the
available 2020-2025 window.

Goal
----
Determine whether v8a edge is stable at 3-month resolution, identify
specific calendar windows (vol regime shifts, market structure breaks)
where it degrades, and propose targeted fixes if any are found.

DATA-RANGE LIMITATION
---------------------
The v8a cube (compass.exp2600_north_star_v8.build_cubes) draws from
the same EXP-2080 stream cache and EXP-2250 QQQ trade tape used by
EXP-2600 / EXP-3150 — both span 2020-01-01..2025-12-31 only. There is
no pre-2020 history in this repository. The original EXP-3230 spec
asked for 2018-2024 coverage; we run on the available 2020-2025 window
and document the limitation. Same caveat as EXP-3150.

Methodology
-----------
1. Reuse the v8a cube exactly as in EXP-2600 (8 streams).
2. Rolling Ledoit-Wolf risk-parity walk-forward at the EXP-2600 winning
   target_vol = 0.18:
       train_days = 252 (12m)
       test_days  = 63  (3m)
       step_days  = 21  (1m)
3. For each fold record:
       - Train + Test Sharpe (gross & net), DD, vol, CAGR
       - Risk-parity weights (drift over time)
       - Train-window 8x8 stream correlation matrix
       - Trade days = n_test, plus per-stream nonzero-day count
4. Aggregate:
       - % positive net-Sharpe folds
       - Train-vs-test Sharpe gap distribution
       - Weights drift between consecutive folds (L1 distance)
       - Correlation matrix stability (Frobenius norm between folds)
5. Flag folds with:
       - net Sharpe < 0
       - net Sharpe < 10th percentile
       - large weight shift (L1 > 0.20)
       - large correlation regime break (Frobenius > 1.0)
6. Group flagged folds by calendar period; propose remediation
   if a structural pattern is visible.

Rule Zero: same real IronVault + Yahoo cube as EXP-2600 / EXP-3150.
No synthetic data. Slicing only.

Outputs:
  compass/reports/exp3230_rolling_walkforward.json
  compass/reports/exp3230_rolling_walkforward.html
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
    TRADING_DAYS,
)
from compass.exp2360_robust_cov import (  # noqa: E402
    cov_ledoit_wolf,
    risk_parity_weights,
)

REPORT_JSON = ROOT / "compass" / "reports" / "exp3230_rolling_walkforward.json"
REPORT_HTML = ROOT / "compass" / "reports" / "exp3230_rolling_walkforward.html"

# v8a winning config from EXP-2600 / EXP-3150
V8A_TARGET_VOL = 0.18

# Rolling window config — finer than EXP-2280 (which used 63-day step)
TRAIN_DAYS = 252  # 12 months
TEST_DAYS = 63    # 3 months
STEP_DAYS = 21    # 1 month  ← key difference vs EXP-2280
SCALE_CAP = 20.0

# Flagging thresholds
WEIGHT_DRIFT_FLAG = 0.20      # L1 distance between consecutive weight vectors
CORR_BREAK_FLAG = 1.0         # Frobenius norm between consecutive train corr matrices
TRAIN_TEST_GAP_FLAG = 2.0     # Sharpe gap (train - test)


# ─── Rolling walk-forward (1-month step) ─────────────────────────────


def rolling_walk_forward(
    cube: pd.DataFrame, target_vol: float,
    train_days: int = TRAIN_DAYS, test_days: int = TEST_DAYS,
    step_days: int = STEP_DAYS, scale_cap: float = SCALE_CAP,
) -> Tuple[pd.Series, List[Dict]]:
    """1-month-step rolling Ledoit-Wolf risk-parity walk-forward.

    Returns
    -------
    pooled : pd.Series
        OOS daily returns concatenated across folds. NOTE: with overlapping
        folds (step < test_days) the same calendar day appears in multiple
        folds. The pooled series uses the LATEST fold's value for any
        repeated date so the pooled timeline equals the calendar.
    folds  : list[dict]
        Per-fold metrics. Each fold's `test_start`/`test_end` give the
        3-month evaluation window.
    """
    cols = list(cube.columns)
    n = len(cube)
    fold_rows: List[Dict] = []
    pooled_map: Dict[pd.Timestamp, float] = {}

    i = train_days
    fold_ix = 0
    prev_w: np.ndarray | None = None
    prev_corr: np.ndarray | None = None

    while i + test_days <= n:
        train = cube.iloc[i - train_days:i]
        test = cube.iloc[i:i + test_days]

        Sigma = cov_ledoit_wolf(train.values)
        w = risk_parity_weights(Sigma)
        train_port = train.values @ w
        train_vol = float(np.std(train_port, ddof=1)) * math.sqrt(TRADING_DAYS)
        scale = target_vol / train_vol if train_vol > 1e-10 else 1.0
        scale = float(np.clip(scale, 0.1, scale_cap))

        train_oos = pd.Series(train_port * scale, index=train.index)
        test_oos = pd.Series(test.values @ w * scale, index=test.index)

        # Train-window stream correlation matrix
        corr = pd.DataFrame(train.values, columns=cols).corr().fillna(0.0).values

        weight_drift = (
            float(np.abs(w - prev_w).sum()) if prev_w is not None else 0.0
        )
        corr_break = (
            float(np.linalg.norm(corr - prev_corr, ord="fro"))
            if prev_corr is not None else 0.0
        )

        gross_train = fold_metrics(train_oos)
        gross_test = fold_metrics(test_oos)
        net_test = fold_metrics(apply_net_drag(test_oos))
        net_train = fold_metrics(apply_net_drag(train_oos))

        train_test_gap = gross_train["sharpe"] - gross_test["sharpe"]

        notes: List[str] = []
        if net_test["sharpe"] < 0:
            notes.append("net_sharpe_negative")
        if gross_test["sharpe"] < 0:
            notes.append("gross_sharpe_negative")
        if abs(train_test_gap) > TRAIN_TEST_GAP_FLAG:
            notes.append("large_train_test_gap")
        if weight_drift > WEIGHT_DRIFT_FLAG:
            notes.append("large_weight_drift")
        if corr_break > CORR_BREAK_FLAG:
            notes.append("corr_regime_break")

        fold_rows.append({
            "fold": fold_ix,
            "train_start": str(train.index[0].date()),
            "train_end": str(train.index[-1].date()),
            "test_start": str(test.index[0].date()),
            "test_end": str(test.index[-1].date()),
            "vol_scale": round(scale, 4),
            "weights": {cols[j]: round(float(w[j]), 4) for j in range(len(cols))},
            "weight_drift_l1": round(weight_drift, 4),
            "corr_frobenius_break": round(corr_break, 4),
            "avg_pairwise_corr_train": round(
                float(corr[np.triu_indices_from(corr, k=1)].mean()), 4
            ),
            "n_test_days": int(len(test)),
            "n_test_active_stream_days": int((test.values != 0).sum()),
            "gross_train": gross_train,
            "gross_test": gross_test,
            "net_train": net_train,
            "net_test": net_test,
            "train_test_sharpe_gap": round(train_test_gap, 4),
            "notes": notes,
        })

        # Pooled OOS — latest fold wins on overlap
        for ts, val in test_oos.items():
            pooled_map[ts] = float(val)

        prev_w = w
        prev_corr = corr
        i += step_days
        fold_ix += 1

    pooled = pd.Series(pooled_map).sort_index()
    return pooled, fold_rows


# ─── Aggregate analytics ─────────────────────────────────────────────


def _summary(xs: List[float]) -> Dict[str, float]:
    if not xs:
        return {}
    arr = np.array(xs, dtype=float)
    return {
        "mean": round(float(arr.mean()), 4),
        "median": round(float(np.median(arr)), 4),
        "stdev": round(float(arr.std(ddof=1)) if len(arr) > 1 else 0.0, 4),
        "min": round(float(arr.min()), 4),
        "p10": round(float(np.quantile(arr, 0.10)), 4),
        "p90": round(float(np.quantile(arr, 0.90)), 4),
        "max": round(float(arr.max()), 4),
    }


def aggregate(folds: List[Dict]) -> Dict:
    n = len(folds)
    gross_test_sr = [f["gross_test"]["sharpe"] for f in folds]
    net_test_sr = [f["net_test"]["sharpe"] for f in folds]
    gross_train_sr = [f["gross_train"]["sharpe"] for f in folds]
    test_dd = [f["gross_test"]["max_dd_pct"] for f in folds]
    test_cagr = [f["gross_test"]["cagr_pct"] for f in folds]
    gaps = [f["train_test_sharpe_gap"] for f in folds]
    drifts = [f["weight_drift_l1"] for f in folds][1:]   # skip first
    corr_breaks = [f["corr_frobenius_break"] for f in folds][1:]
    avg_corr = [f["avg_pairwise_corr_train"] for f in folds]

    pos_gross = sum(1 for s in gross_test_sr if s > 0)
    pos_net = sum(1 for s in net_test_sr if s > 0)

    flagged = [f for f in folds if f["notes"]]

    # Calendar grouping of flagged folds (by year-quarter of test_start)
    period_counts: Dict[str, int] = {}
    for f in flagged:
        d = pd.Timestamp(f["test_start"])
        key = f"{d.year}Q{(d.month - 1) // 3 + 1}"
        period_counts[key] = period_counts.get(key, 0) + 1

    return {
        "n_folds": n,
        "windows_positive_gross_sharpe": pos_gross,
        "windows_positive_net_sharpe": pos_net,
        "pct_positive_gross": round(pos_gross / n, 4) if n else 0,
        "pct_positive_net": round(pos_net / n, 4) if n else 0,
        "gross_test_sharpe_summary": _summary(gross_test_sr),
        "net_test_sharpe_summary": _summary(net_test_sr),
        "gross_train_sharpe_summary": _summary(gross_train_sr),
        "test_max_dd_pct_summary": _summary(test_dd),
        "test_cagr_pct_summary": _summary(test_cagr),
        "train_test_sharpe_gap_summary": _summary(gaps),
        "weight_drift_l1_summary": _summary(drifts),
        "corr_frobenius_break_summary": _summary(corr_breaks),
        "avg_pairwise_corr_train_summary": _summary(avg_corr),
        "n_flagged_folds": len(flagged),
        "flagged_period_counts": dict(sorted(period_counts.items())),
        "flagged_folds": [
            {
                "fold": f["fold"],
                "test_start": f["test_start"],
                "test_end": f["test_end"],
                "gross_sharpe": f["gross_test"]["sharpe"],
                "net_sharpe": f["net_test"]["sharpe"],
                "max_dd_pct": f["gross_test"]["max_dd_pct"],
                "weight_drift_l1": f["weight_drift_l1"],
                "corr_frobenius_break": f["corr_frobenius_break"],
                "notes": f["notes"],
            }
            for f in flagged
        ],
    }


# ─── Pooled CI ────────────────────────────────────────────────────────


def pooled_metrics(pooled: pd.Series) -> Dict[str, Dict]:
    return {
        "gross": fold_metrics(pooled),
        "net": fold_metrics(apply_net_drag(pooled)),
    }


# ─── Main ─────────────────────────────────────────────────────────────


def main() -> None:
    print("=" * 72)
    print("EXP-3230 — Rolling Walk-Forward Robustness (1-month step)")
    print("=" * 72)

    print("\n[1/3] Building v8a cube …")
    cubes = build_cubes()
    v8a = cubes["v8a_add_qqq"]
    print(f"      v8a shape: {v8a.shape}")
    print(f"      data range: {v8a.index[0].date()} .. {v8a.index[-1].date()}")
    print(f"      streams: {list(v8a.columns)}")

    print(
        f"\n[2/3] Rolling walk-forward "
        f"(train={TRAIN_DAYS}d / test={TEST_DAYS}d / step={STEP_DAYS}d, "
        f"target_vol={V8A_TARGET_VOL}) …"
    )
    pooled, folds = rolling_walk_forward(v8a, V8A_TARGET_VOL)
    print(f"      generated {len(folds)} rolling folds")
    print(f"      pooled OOS days: {len(pooled)}")

    pm = pooled_metrics(pooled)
    print(
        f"      pooled gross  CAGR {pm['gross']['cagr_pct']:+7.1f}%  "
        f"SR {pm['gross']['sharpe']:5.2f}  "
        f"DD {pm['gross']['max_dd_pct']:5.1f}%"
    )
    print(
        f"      pooled net    CAGR {pm['net']['cagr_pct']:+7.1f}%  "
        f"SR {pm['net']['sharpe']:5.2f}  "
        f"DD {pm['net']['max_dd_pct']:5.1f}%"
    )

    agg = aggregate(folds)
    print(
        f"\n      net+: {agg['windows_positive_net_sharpe']}/{agg['n_folds']} "
        f"({agg['pct_positive_net']:.0%})  "
        f"gross+: {agg['windows_positive_gross_sharpe']}/{agg['n_folds']} "
        f"({agg['pct_positive_gross']:.0%})"
    )
    print(
        f"      gross test SR: mean {agg['gross_test_sharpe_summary']['mean']:.2f}  "
        f"median {agg['gross_test_sharpe_summary']['median']:.2f}  "
        f"min {agg['gross_test_sharpe_summary']['min']:.2f}  "
        f"max {agg['gross_test_sharpe_summary']['max']:.2f}"
    )
    print(
        f"      train-test gap: mean {agg['train_test_sharpe_gap_summary']['mean']:.2f}  "
        f"p90 {agg['train_test_sharpe_gap_summary']['p90']:.2f}"
    )
    print(
        f"      weight drift L1: mean {agg['weight_drift_l1_summary']['mean']:.3f}  "
        f"max {agg['weight_drift_l1_summary']['max']:.3f}"
    )
    print(
        f"      corr Frobenius:  mean {agg['corr_frobenius_break_summary']['mean']:.3f}  "
        f"max {agg['corr_frobenius_break_summary']['max']:.3f}"
    )
    print(f"      flagged folds:   {agg['n_flagged_folds']}/{agg['n_folds']}")
    print(f"      flagged periods: {agg['flagged_period_counts']}")

    print("\n[3/3] Writing reports …")
    payload = {
        "experiment": "EXP-3230",
        "title": "Rolling Walk-Forward Robustness (1-month step) — v8a",
        "generated": datetime.now().isoformat(timespec="seconds"),
        "rule_zero": True,
        "data_range_caveat": (
            "v8a cube spans 2020-01-01..2025-12-31 only. The original "
            "EXP-3230 brief asked for 2018-2024 coverage; we run on the "
            "available 2020-2025 window. No pre-2020 IronVault history "
            "exists in this repository — same constraint documented in "
            "EXP-3150."
        ),
        "config": {
            "strategy": "v8a_add_qqq",
            "target_vol": V8A_TARGET_VOL,
            "train_days": TRAIN_DAYS,
            "test_days": TEST_DAYS,
            "step_days": STEP_DAYS,
            "scale_cap": SCALE_CAP,
            "net_drag_bps": NET_DRAG_BPS,
            "net_drag_pct": NET_DRAG_PCT,
            "flag_thresholds": {
                "weight_drift_l1": WEIGHT_DRIFT_FLAG,
                "corr_frobenius": CORR_BREAK_FLAG,
                "train_test_sharpe_gap": TRAIN_TEST_GAP_FLAG,
            },
        },
        "sources": {
            "cube_builder": "compass.exp2600_north_star_v8.build_cubes (v8a_add_qqq)",
            "stream_cache": "compass/cache/exp2080_streams.pkl (real IronVault + Yahoo)",
            "qqq_trades": "compass/cache/exp2250_qqq_trades.pkl (real IronVault QQQ chains)",
            "drag_rate": f"EXP-2570 {NET_DRAG_BPS:.1f} bps",
            "comparable": "EXP-2280 (20-fold yearly), EXP-3150 (post-2020 retest)",
        },
        "data_range": {
            "start": str(v8a.index[0].date()),
            "end": str(v8a.index[-1].date()),
            "n_obs": int(len(v8a)),
            "streams": list(v8a.columns),
        },
        "pooled": pm,
        "aggregate": agg,
        "folds": folds,
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(payload, indent=2, default=str))
    print(f"      JSON: {REPORT_JSON}")

    REPORT_HTML.write_text(build_html(payload), encoding="utf-8")
    print(f"      HTML: {REPORT_HTML}")
    print("\nDone.")


# ─── HTML ─────────────────────────────────────────────────────────────


def build_html(p: Dict) -> str:
    folds = p["folds"]
    agg = p["aggregate"]
    cfg = p["config"]
    pooled = p["pooled"]

    def srcolor(s: float) -> str:
        if s >= 2.0:
            return "#16a34a"
        if s >= 1.0:
            return "#65a30d"
        if s >= 0:
            return "#ca8a04"
        return "#dc2626"

    # fold rows
    fold_rows = []
    for f in folds:
        gt = f["gross_test"]["sharpe"]
        nt = f["net_test"]["sharpe"]
        tr = f["gross_train"]["sharpe"]
        gap = f["train_test_sharpe_gap"]
        notes_html = " ".join(
            f'<span class="pill">{n}</span>' for n in f["notes"]
        )
        gap_cls = "neg" if abs(gap) > TRAIN_TEST_GAP_FLAG else ""
        drift = f["weight_drift_l1"]
        drift_cls = "neg" if drift > WEIGHT_DRIFT_FLAG else ""
        cb = f["corr_frobenius_break"]
        cb_cls = "neg" if cb > CORR_BREAK_FLAG else ""
        fold_rows.append(
            f"<tr>"
            f"<td>{f['fold']}</td>"
            f"<td>{f['train_start']} → {f['train_end']}</td>"
            f"<td>{f['test_start']} → {f['test_end']}</td>"
            f"<td>{tr:.2f}</td>"
            f'<td style="color:{srcolor(gt)};font-weight:600">{gt:+.2f}</td>'
            f'<td style="color:{srcolor(nt)};font-weight:600">{nt:+.2f}</td>'
            f'<td class="{gap_cls}">{gap:+.2f}</td>'
            f"<td>{f['gross_test']['max_dd_pct']:.1f}%</td>"
            f"<td>{f['vol_scale']:.2f}</td>"
            f'<td class="{drift_cls}">{drift:.3f}</td>'
            f'<td class="{cb_cls}">{cb:.3f}</td>'
            f"<td>{notes_html}</td>"
            f"</tr>"
        )

    # sparkline
    max_abs_sr = max((abs(f["net_test"]["sharpe"]) for f in folds), default=1)
    spark_rows = []
    for f in folds:
        s = f["net_test"]["sharpe"]
        w = int(abs(s) / max(max_abs_sr, 0.01) * 220)
        spark_rows.append(
            f"<tr><td>{f['fold']}</td><td>{f['test_end']}</td>"
            f'<td style="color:{srcolor(s)}">{s:+.2f}</td>'
            f'<td><span class="bar" style="width:{w}px;background:{srcolor(s)}"></span></td></tr>'
        )

    # weight evolution
    streams = list(folds[0]["weights"].keys())
    weight_rows = []
    for f in folds:
        cells = "".join(
            f"<td>{f['weights'][s]:.3f}</td>" for s in streams
        )
        weight_rows.append(
            f"<tr><td>{f['test_end']}</td>{cells}</tr>"
        )

    # flagged folds detail
    flagged_html = ""
    if agg["flagged_folds"]:
        rows = []
        for fw in agg["flagged_folds"]:
            notes = " ".join(f'<span class="pill">{n}</span>' for n in fw["notes"])
            rows.append(
                f"<tr><td>{fw['fold']}</td>"
                f"<td>{fw['test_start']} → {fw['test_end']}</td>"
                f'<td style="color:{srcolor(fw["gross_sharpe"])}">{fw["gross_sharpe"]:+.2f}</td>'
                f'<td style="color:{srcolor(fw["net_sharpe"])}">{fw["net_sharpe"]:+.2f}</td>'
                f"<td>{fw['max_dd_pct']:.1f}%</td>"
                f"<td>{fw['weight_drift_l1']:.3f}</td>"
                f"<td>{fw['corr_frobenius_break']:.3f}</td>"
                f"<td>{notes}</td></tr>"
            )
        flagged_html = (
            '<h2>Flagged folds</h2>'
            '<table><thead><tr>'
            '<th>Fold</th><th>Test window</th><th>Gross SR</th>'
            '<th>Net SR</th><th>Max DD</th><th>Wt drift</th>'
            '<th>Corr break</th><th>Notes</th></tr></thead><tbody>'
            + "".join(rows) + "</tbody></table>"
        )
        if agg["flagged_period_counts"]:
            pcs = "  ".join(
                f"<strong>{k}</strong>: {v}"
                for k, v in agg["flagged_period_counts"].items()
            )
            flagged_html += (
                f'<p class="muted">Calendar clustering of flagged folds — {pcs}</p>'
            )

    # diagnosis & remediation
    diagnoses = []
    if agg["pct_positive_net"] < 0.85:
        diagnoses.append(
            f"Net Sharpe is positive in only {agg['pct_positive_net']:.0%} of "
            f"folds — edge has noticeable monthly-granularity instability."
        )
    if agg["train_test_sharpe_gap_summary"]["mean"] > 1.5:
        diagnoses.append(
            f"Mean train-test Sharpe gap is "
            f"{agg['train_test_sharpe_gap_summary']['mean']:.2f} — "
            f"risk-parity weights may overfit the most-recent 12-month vol."
        )
    if agg["weight_drift_l1_summary"]["max"] > WEIGHT_DRIFT_FLAG * 2:
        diagnoses.append(
            f"Max weight drift L1 is "
            f"{agg['weight_drift_l1_summary']['max']:.2f} — "
            f"single-month allocation jumps that large will create real "
            f"turnover cost beyond the EXP-2570 drag."
        )
    if agg["corr_frobenius_break_summary"]["max"] > CORR_BREAK_FLAG * 1.5:
        diagnoses.append(
            f"Max correlation-matrix Frobenius break is "
            f"{agg['corr_frobenius_break_summary']['max']:.2f} — "
            f"a regime shift in the underlying stream covariance is "
            f"present. Identify the calendar window and consider gating "
            f"during such transitions."
        )
    if not diagnoses:
        diagnoses.append(
            "No major degradation pattern detected at monthly granularity. "
            "Edge appears temporally stable on the 2020-2025 window."
        )

    proposals = [
        ("If pct_positive_net < 0.80",
         "Stretch test window to 6 months (smaller-sample noise) or "
         "require a minimum confidence on the realised train-window vol "
         "before deploying."),
        ("If train_test gap mean > 1.5",
         "Apply L2 shrinkage on weights toward the prior fold's vector, "
         "or use a longer (504-day) train window so fold weights stop "
         "tracking the latest 12-month vol shock too eagerly."),
        ("If weight drift L1 large in specific months",
         "Cap monthly turnover (max change per stream = 5%) and absorb "
         "the residual via a transaction-cost-aware optimiser."),
        ("If correlation Frobenius break clusters in one period",
         "Add an explicit covariance-regime gate: when latest 21-day "
         "correlation differs from 252-day baseline by > threshold, "
         "force flat (or last-known-good) weights."),
        ("If a single stream dominates flagged folds",
         "Cap that stream's weight (e.g. ≤ 30% book) regardless of "
         "risk-parity output."),
    ]
    diag_html = "".join(f"<li>{d}</li>" for d in diagnoses)
    prop_html = "".join(
        f"<li><strong>{c}:</strong> {f}</li>" for c, f in proposals
    )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>EXP-3230 — Rolling Walk-Forward Robustness</title>
<style>
body {{ font-family:-apple-system,sans-serif;max-width:1280px;margin:0 auto;padding:28px;background:#fafafa;color:#1e293b }}
h1 {{ font-size:1.8em;color:#0f172a }}
h2 {{ margin-top:2em;border-bottom:2px solid #e2e8f0;padding-bottom:8px;color:#334155 }}
h3 {{ color:#475569;margin-top:1.2em }}
.muted {{ color:#64748b;font-size:.85em }}
.cards {{ display:flex;gap:1em;flex-wrap:wrap;margin:1em 0 }}
.card {{ background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:.9em 1em;min-width:170px;flex:1;text-align:center }}
.card h4 {{ margin:0 0 .3em;color:#64748b;font-size:.78em;text-transform:uppercase;letter-spacing:.04em }}
.card .big {{ font-size:1.6em;font-weight:700 }}
.caveat {{ background:#fef3c7;border:1px solid #f59e0b;border-radius:8px;padding:14px;margin:16px 0;font-size:.92rem;line-height:1.55 }}
.sources {{ background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:14px;font-size:.86rem;line-height:1.55 }}
table {{ width:100%;border-collapse:collapse;margin:12px 0;font-size:.86em }}
th {{ background:#f1f5f9;padding:8px 10px;text-align:right;border-bottom:2px solid #cbd5e1;font-size:.74em;text-transform:uppercase }}
th:first-child,td:first-child {{ text-align:left }}
td {{ padding:7px 10px;text-align:right;border-bottom:1px solid #e2e8f0 }}
.pill {{ display:inline-block;padding:1px 7px;border-radius:9px;font-size:.74em;background:#fee2e2;color:#991b1b;margin-right:3px }}
.bar {{ height:12px;display:inline-block;border-radius:3px;vertical-align:middle }}
.neg {{ color:#dc2626;font-weight:600 }}
.scroll {{ max-height:520px;overflow:auto;border:1px solid #e2e8f0;border-radius:6px }}
.scroll th {{ position:sticky;top:0;z-index:1 }}
</style></head><body>

<h1>EXP-3230 — Rolling Walk-Forward Robustness (1-month step)</h1>
<p class="muted">12m train / 3m test / 1m step rolling Ledoit-Wolf risk-parity walk-forward on v8a.
Generated {p['generated']}.</p>

<div class="caveat">
<strong>⚠ Data-range caveat.</strong> The original EXP-3230 brief asked
for 2018–2024 coverage. The v8a cube spans
<strong>{p['data_range']['start']} → {p['data_range']['end']}</strong> only —
no pre-2020 IronVault history exists in this repository. We run on the
available window and document this. Same constraint as EXP-3150.
</div>

<div class="sources">
<strong>Rule Zero.</strong> Same v8a cube as EXP-2600 / EXP-3150 — 8 streams
({", ".join(p['data_range']['streams'])}). target_vol = {cfg['target_vol']}.
train_days = {cfg['train_days']}, test_days = {cfg['test_days']},
step_days = {cfg['step_days']}. Net = gross − {cfg['net_drag_bps']:.1f} bps drag (EXP-2570).
Comparable to EXP-2280 (20 yearly folds, v6 baseline) at finer resolution.
</div>

<div class="cards">
  <div class="card"><h4>Folds</h4><div class="big">{agg['n_folds']}</div></div>
  <div class="card"><h4>Pooled Gross SR</h4><div class="big">{pooled['gross']['sharpe']:.2f}</div>
    <div class="muted">CAGR {pooled['gross']['cagr_pct']:+.1f}% · DD {pooled['gross']['max_dd_pct']:.1f}%</div></div>
  <div class="card"><h4>Pooled Net SR</h4><div class="big">{pooled['net']['sharpe']:.2f}</div>
    <div class="muted">CAGR {pooled['net']['cagr_pct']:+.1f}% · DD {pooled['net']['max_dd_pct']:.1f}%</div></div>
  <div class="card"><h4>% Positive Net SR</h4><div class="big">{agg['pct_positive_net']:.0%}</div>
    <div class="muted">{agg['windows_positive_net_sharpe']} / {agg['n_folds']}</div></div>
  <div class="card"><h4>Mean Test SR (gross)</h4><div class="big">{agg['gross_test_sharpe_summary']['mean']:.2f}</div>
    <div class="muted">median {agg['gross_test_sharpe_summary']['median']:.2f}</div></div>
  <div class="card"><h4>Train-Test Gap</h4><div class="big">{agg['train_test_sharpe_gap_summary']['mean']:.2f}</div>
    <div class="muted">p90 {agg['train_test_sharpe_gap_summary']['p90']:.2f}</div></div>
  <div class="card"><h4>Flagged Folds</h4><div class="big">{agg['n_flagged_folds']}</div></div>
</div>

<h2>Distribution summary</h2>
<table><thead><tr>
<th>Metric</th><th>Mean</th><th>Median</th><th>Stdev</th>
<th>Min</th><th>p10</th><th>p90</th><th>Max</th></tr></thead><tbody>
{"".join(
    f"<tr><td>{label}</td>"
    + "".join(f"<td>{agg[key][k]:.3f}</td>"
              for k in ["mean", "median", "stdev", "min", "p10", "p90", "max"])
    + "</tr>"
    for label, key in [
        ("Gross train Sharpe", "gross_train_sharpe_summary"),
        ("Gross test Sharpe", "gross_test_sharpe_summary"),
        ("Net test Sharpe", "net_test_sharpe_summary"),
        ("Train-Test Sharpe gap", "train_test_sharpe_gap_summary"),
        ("Test max DD (%)", "test_max_dd_pct_summary"),
        ("Test CAGR (%)", "test_cagr_pct_summary"),
        ("Weight drift L1 (fold-to-fold)", "weight_drift_l1_summary"),
        ("Corr Frobenius break (fold-to-fold)", "corr_frobenius_break_summary"),
        ("Avg pairwise corr (train)", "avg_pairwise_corr_train_summary"),
    ]
)}
</tbody></table>

<h2>Net-Sharpe sparkline (test window per fold)</h2>
<div class="scroll"><table><thead><tr>
<th>Fold</th><th>Test end</th><th>Net SR</th><th>Visual</th></tr></thead><tbody>
{"".join(spark_rows)}
</tbody></table></div>

<h2>Per-fold detail</h2>
<div class="scroll"><table><thead><tr>
<th>#</th><th>Train</th><th>Test</th><th>Train SR</th><th>Gross SR</th><th>Net SR</th>
<th>Gap</th><th>Max DD</th><th>Scale</th><th>Wt drift L1</th><th>Corr Frob</th><th>Notes</th>
</tr></thead><tbody>
{"".join(fold_rows)}
</tbody></table></div>

{flagged_html}

<h2>Risk-parity weight evolution</h2>
<div class="scroll"><table><thead><tr>
<th>Test end</th>{"".join(f"<th>{s}</th>" for s in streams)}
</tr></thead><tbody>
{"".join(weight_rows)}
</tbody></table></div>

<h2>Diagnosis</h2>
<ol>{diag_html}</ol>

<h3>Remediation playbook (apply where the flagged-folds pattern fits)</h3>
<ul>{prop_html}</ul>

<p style="margin-top:3em;color:#94a3b8;font-size:.78em;text-align:center">
compass/exp3230_rolling_walkforward.py · Rule Zero · real data only
</p>
</body></html>"""


if __name__ == "__main__":
    main()
