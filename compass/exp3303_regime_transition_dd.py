"""EXP-3303 — Regime-transition drawdown filter for v8a.

Spec source: compass/reports/exp3300_literature_review_may2026.md §Paper 2,
"Improving S&P 500 Volatility Forecasting through Regime-Switching
Methods" (arXiv 2510.03236, Oct 2025). The paper's central empirical
finding is that VIX-threshold rules lag regime changes by 3-7 days,
while detectors using term structure + VVIX + put/call IV-skew lag
0-2 days. EXP-3300 ranks this as the highest-priority follow-up
(2-day effort, expected gross Sharpe lift +0.2-0.4, low risk).

Mechanic
--------
Augment v8a's regime-detection feature set with three Yahoo-sourced
indices:
  ^VIX           — short-dated SPX implied vol
  ^VIX3M         — 3-month SPX implied vol
  ^VVIX          — vol-of-VIX (vol-of-vol)
  ^SKEW          — CBOE Skew Index, the standardised proxy
                   for SPX 25Δ put/call IV skew

Derived features (no look-ahead — all rolling stats use trailing window):
  term_spread     = VIX3M - VIX      (positive = contango = calm)
  term_spread_z63 = rolling z-score, 63-day trailing window
  vvix_z63        = rolling z-score of VVIX, 63d
  skew_z63        = rolling z-score of SKEW, 63d
  composite_stress = -term_spread_z63 + vvix_z63 + skew_z63
                     (higher = more stress, by construction)

Gate:
  leverage[t] = 1.0                       if composite_stress[t-1] ≤ θ
                gate_leverage             otherwise
  applied multiplicatively on the v8a daily portfolio return.
  t-1 lag is mandatory to avoid look-ahead — the gate decision uses only
  information observable at the close of t-1.

Comparison
----------
Run the EXP-2600 v8a walk-forward (LW risk-parity, target_vol = 0.18)
once; this gives the pooled OOS daily return series. Apply the gate to
this series for several (θ, gate_leverage) combinations. Compare:

  1. Full-period gross + net Sharpe
  2. Full-period max DD
  3. Regime-transition DD: pooled DD attributed to the ±30-day window
     around composite_stress up-crossings of θ
  4. Trade-count impact: fraction of days at reduced leverage

Rule Zero: real v8a cube (EXP-2600). Regime features fetched live from
Yahoo Finance. No synthetic features.

Outputs
  compass/reports/exp3303_regime_transition_dd.json
  compass/reports/exp3303_regime_transition_dd.html
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
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
    walk_forward_lw,
    fold_metrics,
    apply_net_drag,
    NET_DRAG_BPS,
    NET_DRAG_PCT,
    TRADING_DAYS,
)

REPORT_JSON = ROOT / "compass" / "reports" / "exp3303_regime_transition_dd.json"
REPORT_HTML = ROOT / "compass" / "reports" / "exp3303_regime_transition_dd.html"
FEATURES_CACHE = ROOT / "compass" / "cache" / "exp3303_regime_features.pkl"

# v8a winner config from EXP-2600
V8A_TARGET_VOL = 0.18

# Feature engineering config
ZSCORE_WINDOW = 63          # 3-month trailing window
TRANSITION_DD_RADIUS = 30   # ±30 days around an up-crossing event

# Gate sweep
THETAS = [1.0, 1.5, 2.0, 2.5]
GATE_LEVERAGES = [0.0, 0.3, 0.5]

# Indices to fetch
TICKERS = ["^VIX", "^VIX3M", "^VVIX", "^SKEW"]


# ── Feature loading ──────────────────────────────────────────────────


def fetch_regime_features(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Fetch the four regime indices from Yahoo, ffill, restrict to [start, end]."""
    if FEATURES_CACHE.exists():
        df = pd.read_pickle(FEATURES_CACHE)
        if df.index.min() <= start and df.index.max() >= end:
            print(f"[regime] cache hit {FEATURES_CACHE}: "
                  f"{df.index.min().date()}..{df.index.max().date()}")
            return df.loc[(df.index >= start) & (df.index <= end)].copy()

    import yfinance as yf
    print(f"[regime] fetching {TICKERS} from Yahoo "
          f"{start.date()}..{end.date()}+30d…")
    raw = yf.download(
        TICKERS, start=(start - pd.Timedelta(days=120)).date(),
        end=(end + pd.Timedelta(days=30)).date(),
        progress=False, auto_adjust=False,
    )["Close"]
    raw = raw.rename(columns={"^VIX": "vix", "^VIX3M": "vix3m",
                              "^VVIX": "vvix", "^SKEW": "skew"})
    raw = raw.ffill().dropna()
    FEATURES_CACHE.parent.mkdir(parents=True, exist_ok=True)
    raw.to_pickle(FEATURES_CACHE)
    print(f"[regime] cached → {FEATURES_CACHE}")
    return raw.loc[(raw.index >= start) & (raw.index <= end)].copy()


def build_composite_stress(features: pd.DataFrame) -> pd.DataFrame:
    """Add term spread + trailing z-scores + composite stress score."""
    f = features.copy()
    f["term_spread"] = f["vix3m"] - f["vix"]
    for col, neg in [("term_spread", True), ("vvix", False), ("skew", False)]:
        roll = f[col].rolling(ZSCORE_WINDOW, min_periods=ZSCORE_WINDOW)
        z = (f[col] - roll.mean()) / roll.std(ddof=1)
        f[f"{col}_z"] = z if not neg else -z   # term_spread negated so high z = stress
    f["composite_stress"] = (
        f["term_spread_z"] + f["vvix_z"] + f["skew_z"]
    ) / math.sqrt(3.0)   # variance-normalise so composite has unit-ish scale
    return f


# ── Gate application ─────────────────────────────────────────────────


def apply_regime_gate(
    pooled: pd.Series, composite: pd.Series,
    theta: float, gate_leverage: float,
) -> Tuple[pd.Series, pd.Series]:
    """Return (gated_pooled, leverage_series) with composite[t-1] driving gate[t].

    Aligned on pooled.index. Days with NaN composite[t-1] (warm-up) get
    leverage = 1.0 — i.e. the gate is conservative-off until features
    are ready, since flagging during warm-up would introduce a structural
    bias.
    """
    comp_lag = composite.shift(1).reindex(pooled.index)
    leverage = np.where(comp_lag.values > theta, gate_leverage, 1.0)
    leverage = pd.Series(leverage, index=pooled.index)
    leverage = leverage.where(~comp_lag.isna(), 1.0)
    return pooled * leverage, leverage


# ── Regime transition diagnostics ────────────────────────────────────


@dataclass
class TransitionEvent:
    date: pd.Timestamp
    composite_at: float
    pre_drawdown_pct: float       # baseline DD inside [-radius, 0]
    post_drawdown_pct: float      # baseline DD inside [0, +radius]


def find_upcrossings(composite: pd.Series, theta: float) -> List[pd.Timestamp]:
    """Days where composite crosses from ≤ θ to > θ."""
    s = composite.dropna()
    prev = s.shift(1)
    mask = (s > theta) & (prev <= theta)
    return list(s.index[mask.fillna(False)])


def compute_transition_dd(
    pooled: pd.Series, composite: pd.Series, theta: float,
) -> Tuple[List[TransitionEvent], float]:
    """Identify up-crossings of θ; for each, compute the worst DD over
    [t - radius, t + radius]. Return events and the sum of |worst DD|s.
    """
    events: List[TransitionEvent] = []
    eq = (1 + pooled.fillna(0)).cumprod()
    cmax = eq.cummax()
    dd = (cmax - eq) / cmax    # positive numbers
    for d in find_upcrossings(composite, theta):
        if d not in pooled.index:
            continue
        i = pooled.index.get_loc(d)
        lo = max(0, i - TRANSITION_DD_RADIUS)
        hi = min(len(pooled), i + TRANSITION_DD_RADIUS + 1)
        pre = float(dd.iloc[lo:i + 1].max()) if i >= lo else 0.0
        post = float(dd.iloc[i:hi].max()) if hi > i else 0.0
        events.append(TransitionEvent(
            date=d, composite_at=float(composite.loc[d]),
            pre_drawdown_pct=pre * 100, post_drawdown_pct=post * 100,
        ))
    total_post_dd = float(sum(e.post_drawdown_pct for e in events))
    return events, total_post_dd


def fraction_gated(leverage: pd.Series) -> Dict[str, float]:
    n = len(leverage)
    n_gated = int((leverage < 1.0 - 1e-9).sum())
    n_full_off = int((leverage < 1e-9).sum())
    return {
        "days_total": n,
        "days_gated": n_gated,
        "days_full_off": n_full_off,
        "pct_gated": round(100 * n_gated / n, 3),
        "pct_full_off": round(100 * n_full_off / n, 3),
    }


# ── Main ─────────────────────────────────────────────────────────────


def main() -> None:
    print("=" * 72)
    print("EXP-3303 — Regime-transition DD filter for v8a")
    print("=" * 72)

    print("\n[1/5] Building v8a cube + walk-forward LW pooled OOS series…")
    cubes = build_cubes()
    v8a = cubes["v8a_add_qqq"]
    pooled, folds = walk_forward_lw(v8a, target_vol=V8A_TARGET_VOL)
    pooled = pooled.dropna()
    base_gross_m = fold_metrics(pooled)
    base_net_m = fold_metrics(apply_net_drag(pooled))
    print(f"      pooled OOS: {pooled.index[0].date()}..{pooled.index[-1].date()}  "
          f"({len(pooled)} days, {len(folds)} folds)")
    print(f"      baseline gross: SR {base_gross_m['sharpe']:.3f}  "
          f"CAGR {base_gross_m['cagr_pct']:.1f}%  "
          f"DD {base_gross_m['max_dd_pct']:.2f}%")
    print(f"      baseline net  : SR {base_net_m['sharpe']:.3f}  "
          f"CAGR {base_net_m['cagr_pct']:.1f}%  "
          f"DD {base_net_m['max_dd_pct']:.2f}%")

    print("\n[2/5] Fetching regime features (^VIX, ^VIX3M, ^VVIX, ^SKEW)…")
    feats_raw = fetch_regime_features(pooled.index[0], pooled.index[-1])
    feats = build_composite_stress(feats_raw)
    feats_aligned = feats.reindex(pooled.index).ffill()
    composite = feats_aligned["composite_stress"]
    print(f"      features shape: {feats_aligned.shape}")
    print(f"      composite stress percentiles "
          f"p50={composite.quantile(0.50):.2f}  "
          f"p90={composite.quantile(0.90):.2f}  "
          f"p95={composite.quantile(0.95):.2f}  "
          f"p99={composite.quantile(0.99):.2f}")
    print(f"      max composite stress: {composite.max():.2f} on "
          f"{composite.idxmax().date() if pd.notna(composite.idxmax()) else 'N/A'}")

    # ── Sweep θ × gate_leverage ──
    print("\n[3/5] Gate sweep (θ × gate_leverage)…")
    print(f"{'θ':>5}  {'gate':>5}  "
          f"{'gross_SR':>9}  {'net_SR':>7}  {'CAGR':>7}  {'DD':>6}  "
          f"{'trans_DD':>9}  {'gated%':>7}  {'n_events':>9}")
    sweep: List[Dict] = []
    for theta in THETAS:
        for g in GATE_LEVERAGES:
            gated, lev = apply_regime_gate(pooled, composite, theta, g)
            g_gross = fold_metrics(gated)
            g_net = fold_metrics(apply_net_drag(gated))
            events, total_trans_dd = compute_transition_dd(gated, composite, theta)
            base_events, base_trans_dd = compute_transition_dd(pooled, composite, theta)
            stats = fraction_gated(lev)
            sweep.append({
                "theta": theta,
                "gate_leverage": g,
                "gross": g_gross,
                "net": g_net,
                "transition_post_dd_pct_total": round(total_trans_dd, 3),
                "baseline_transition_post_dd_pct_total": round(base_trans_dd, 3),
                "transition_events": len(events),
                "trade_impact": stats,
            })
            print(f"{theta:>5.1f}  {g:>5.2f}  "
                  f"{g_gross['sharpe']:>9.3f}  {g_net['sharpe']:>7.3f}  "
                  f"{g_net['cagr_pct']:>6.1f}%  "
                  f"{g_gross['max_dd_pct']:>5.2f}%  "
                  f"{total_trans_dd:>8.2f}%  {stats['pct_gated']:>6.2f}%  "
                  f"{len(events):>9d}")

    # ── Pick best by net Sharpe (with DD ≤ baseline) ──
    base_dd = abs(base_gross_m["max_dd_pct"])
    candidates = [
        s for s in sweep
        if abs(s["gross"]["max_dd_pct"]) <= base_dd
    ]
    best = max(
        candidates if candidates else sweep,
        key=lambda s: s["net"]["sharpe"],
    )
    print(f"\n      Best gate (net SR, DD ≤ baseline): "
          f"θ={best['theta']:.1f}  gate={best['gate_leverage']:.2f}  "
          f"net SR {best['net']['sharpe']:.3f}  "
          f"DD {best['gross']['max_dd_pct']:.2f}%")

    # ── Detailed transition-event analysis under best gate ──
    print(f"\n[4/5] Transition events (θ={best['theta']:.1f}) — baseline vs gated…")
    base_events_full, base_dd_total = compute_transition_dd(
        pooled, composite, best["theta"]
    )
    gated_best, lev_best = apply_regime_gate(
        pooled, composite, best["theta"], best["gate_leverage"]
    )
    gated_events_full, gated_dd_total = compute_transition_dd(
        gated_best, composite, best["theta"]
    )
    print(f"      n_events: {len(base_events_full)}")
    print(f"      baseline ΣDD post-transition: {base_dd_total:.2f}%")
    print(f"      gated     ΣDD post-transition: {gated_dd_total:.2f}%")
    print(f"      reduction: {(base_dd_total - gated_dd_total):+.2f}% absolute, "
          f"{(1 - gated_dd_total / base_dd_total) * 100 if base_dd_total > 1e-9 else 0:+.1f}% relative")
    print("      Top-10 events by baseline post-DD:")
    top = sorted(base_events_full, key=lambda e: -e.post_drawdown_pct)[:10]
    for e in top:
        i = pooled.index.get_loc(e.date)
        # Find matching gated event
        post_g = 0.0
        for ge in gated_events_full:
            if ge.date == e.date:
                post_g = ge.post_drawdown_pct
                break
        print(f"        {e.date.date()}  composite={e.composite_at:5.2f}  "
              f"baseline post-DD {e.post_drawdown_pct:5.2f}%  "
              f"→ gated {post_g:5.2f}%  "
              f"Δ {(post_g - e.post_drawdown_pct):+5.2f}%")

    # ── Verdict + summary ──
    print("\n[5/5] Verdict")
    print("-" * 72)
    sr_lift_gross = best["gross"]["sharpe"] - base_gross_m["sharpe"]
    sr_lift_net = best["net"]["sharpe"] - base_net_m["sharpe"]
    dd_delta = best["gross"]["max_dd_pct"] - base_gross_m["max_dd_pct"]
    transition_dd_reduction = base_dd_total - gated_dd_total
    print(f"  Δ gross SR:     {sr_lift_gross:+.3f}  "
          f"(lit. predicted +0.2 to +0.4)")
    print(f"  Δ net SR:       {sr_lift_net:+.3f}")
    print(f"  Δ max DD:       {dd_delta:+.2f}%  "
          f"(negative = improvement)")
    print(f"  Δ transition ΣDD: {-transition_dd_reduction:+.2f}%  "
          f"(negative = improvement)")
    print(f"  Days flattened: {best['trade_impact']['pct_gated']:.1f}% of all OOS days")

    in_lit_band = 0.20 <= sr_lift_gross <= 0.40
    if sr_lift_gross >= 0.20:
        verdict = "IN_LIT_BAND" if in_lit_band else "BEATS_LIT_BAND"
        print(f"  ✓ gate produces ≥+0.20 gross SR lift — confirms literature.")
    elif sr_lift_gross >= 0.0:
        verdict = "POSITIVE_BUT_BELOW_LIT_BAND"
        print(f"  ◐ gate produces small positive lift but below literature band.")
    else:
        verdict = "NO_LIFT"
        print(f"  ✗ gate does not improve gross SR — feature lacks signal "
              f"on this dataset.")

    payload = {
        "experiment": "EXP-3303",
        "title": "Regime-transition drawdown filter for v8a (VVIX + Skew + term-spread)",
        "generated": datetime.now().isoformat(timespec="seconds"),
        "rule_zero": True,
        "spec_source": "compass/reports/exp3300_literature_review_may2026.md §Paper 2",
        "data_caveat": (
            "Regime features fetched live from Yahoo (^VIX, ^VIX3M, ^VVIX, "
            "^SKEW). v8a cube via EXP-2600 build_cubes (real IronVault + "
            "Yahoo). Gate decision uses composite_stress[t-1] to avoid "
            "look-ahead. Walk-forward LW risk-parity from EXP-2600 with "
            "target_vol=0.18; gate is multiplicative leverage on pooled "
            "OOS daily series — same as production v8a sizing layer."
        ),
        "config": {
            "v8a_target_vol": V8A_TARGET_VOL,
            "zscore_window": ZSCORE_WINDOW,
            "transition_dd_radius_days": TRANSITION_DD_RADIUS,
            "thetas": THETAS,
            "gate_leverages": GATE_LEVERAGES,
            "tickers": TICKERS,
            "drag_bps": NET_DRAG_BPS,
        },
        "baseline": {
            "gross": base_gross_m,
            "net": base_net_m,
            "transition_post_dd_pct_total": round(base_dd_total, 3),
            "n_transition_events": len(base_events_full),
        },
        "feature_summary": {
            "n_obs": int(len(feats_aligned.dropna())),
            "composite_p50": float(composite.quantile(0.50)),
            "composite_p90": float(composite.quantile(0.90)),
            "composite_p95": float(composite.quantile(0.95)),
            "composite_p99": float(composite.quantile(0.99)),
            "composite_max": float(composite.max()),
            "composite_max_date": str(composite.idxmax().date())
                                  if pd.notna(composite.idxmax()) else None,
        },
        "sweep": sweep,
        "best": best,
        "best_events_top10": [
            {
                "date": str(e.date.date()),
                "composite": e.composite_at,
                "baseline_post_dd_pct": e.post_drawdown_pct,
                "gated_post_dd_pct": next(
                    (ge.post_drawdown_pct for ge in gated_events_full
                     if ge.date == e.date), 0.0,
                ),
            }
            for e in sorted(base_events_full,
                            key=lambda x: -x.post_drawdown_pct)[:10]
        ],
        "verdict": {
            "code": verdict,
            "delta_gross_sharpe": round(sr_lift_gross, 4),
            "delta_net_sharpe": round(sr_lift_net, 4),
            "delta_max_dd_pct": round(dd_delta, 4),
            "transition_dd_reduction_pct_abs": round(transition_dd_reduction, 4),
            "lit_band_low": 0.20,
            "lit_band_high": 0.40,
            "lit_predicted": "+0.2 to +0.4 gross Sharpe (EXP-3300 ranking table)",
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
    base = p["baseline"]
    best = p["best"]
    v = p["verdict"]

    color = {
        "IN_LIT_BAND":     "#16a34a",
        "BEATS_LIT_BAND":  "#16a34a",
        "POSITIVE_BUT_BELOW_LIT_BAND": "#f59e0b",
        "NO_LIFT":         "#dc2626",
    }.get(v["code"], "#64748b")

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
            f"<td>{s['trade_impact']['pct_gated']:.2f}%</td>"
            f"<td>{s['transition_events']}</td>"
            f"</tr>"
        )

    event_rows = ""
    for e in p["best_events_top10"]:
        delta = e["gated_post_dd_pct"] - e["baseline_post_dd_pct"]
        ec = "#16a34a" if delta < 0 else ("#dc2626" if delta > 0.5 else "#64748b")
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
<title>EXP-3303 — Regime-Transition DD Filter</title>
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

<h1>EXP-3303 — Regime-transition drawdown filter (v8a)</h1>
<p class="muted">Spec: literature review §Paper 2
(<a href="https://arxiv.org/html/2510.03236v1">arXiv 2510.03236</a>).
Adds VVIX + SPX skew + VIX term-structure to the v8a regime detector and
gates leverage on a composite stress score. {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<div class="sources">
<strong>Rule Zero.</strong> v8a cube from EXP-2600 (real IronVault +
Yahoo). Regime features ^VIX, ^VIX3M, ^VVIX, ^SKEW fetched live from
Yahoo. Gate uses composite_stress[t-1] (no look-ahead). Walk-forward
LW risk-parity, target_vol = {cfg['v8a_target_vol']:.2f}; gate is
multiplicative leverage on pooled OOS daily returns. Net SR includes
EXP-2570 {cfg['drag_bps']:.1f} bps drag.
</div>

<div class="verdict">
<span class="badge">{v['code']}</span>
<div class="kv" style="margin-top:14px">
<div><b>Δ gross Sharpe</b></div><div>{v['delta_gross_sharpe']:+.3f}
(lit. band: +{v['lit_band_low']:.2f} to +{v['lit_band_high']:.2f})</div>
<div><b>Δ net Sharpe</b></div><div>{v['delta_net_sharpe']:+.3f}</div>
<div><b>Δ max DD</b></div><div>{v['delta_max_dd_pct']:+.2f}%</div>
<div><b>Transition-DD reduction (Σ post-event)</b></div>
<div>{v['transition_dd_reduction_pct_abs']:+.2f}%</div>
<div><b>Best config</b></div>
<div>θ = {best['theta']:.1f}, gate_leverage = {best['gate_leverage']:.2f}
({best['trade_impact']['pct_gated']:.1f}% days gated)</div>
<div><b>Baseline gross SR</b></div><div>{base['gross']['sharpe']:.3f}</div>
<div><b>Best gross SR</b></div><div>{best['gross']['sharpe']:.3f}</div>
</div>
</div>

<h2>1. Gate sweep (θ × gate_leverage)</h2>
<table>
<thead><tr>
<th>θ</th><th>gate lev</th>
<th>Gross SR</th><th>Net SR</th><th>Net CAGR</th><th>Max DD</th>
<th>Σ transition DD</th><th>Days gated</th><th># events</th>
</tr></thead>
<tbody>{sweep_rows}</tbody>
</table>
<p class="muted">Best row highlighted (max net SR among configs with
DD ≤ baseline {base['gross']['max_dd_pct']:.2f}%).</p>

<h2>2. Top-10 transition events (best gate vs baseline)</h2>
<table>
<thead><tr>
<th>Up-cross date</th><th>composite</th>
<th>baseline post-DD</th><th>gated post-DD</th><th>Δ</th>
</tr></thead>
<tbody>{event_rows}</tbody>
</table>
<p class="muted">Up-crossings of composite_stress through θ = {best['theta']:.1f}.
Post-DD = max DD over the [t, t+{cfg['transition_dd_radius_days']}] window
attributed to the transition. Negative Δ = gate reduced DD.</p>

<h2>3. Composite stress feature distribution</h2>
<table>
<thead><tr><th>Stat</th><th>Value</th></tr></thead>
<tbody>
<tr><td>n observations</td><td>{p['feature_summary']['n_obs']}</td></tr>
<tr><td>p50</td><td>{p['feature_summary']['composite_p50']:.3f}</td></tr>
<tr><td>p90</td><td>{p['feature_summary']['composite_p90']:.3f}</td></tr>
<tr><td>p95</td><td>{p['feature_summary']['composite_p95']:.3f}</td></tr>
<tr><td>p99</td><td>{p['feature_summary']['composite_p99']:.3f}</td></tr>
<tr><td>max</td><td>{p['feature_summary']['composite_max']:.3f}
on {p['feature_summary']['composite_max_date']}</td></tr>
</tbody>
</table>

<p style="margin-top:3em;color:#94a3b8;font-size:0.78em;text-align:center">
compass/exp3303_regime_transition_dd.py · Rule Zero · real Yahoo + IronVault data
</p>
</body></html>"""


if __name__ == "__main__":
    main()
