"""EXP-3310 — VIX term structure + options order-flow imbalance alpha.

Spec source: compass/reports/exp3300_literature_review_may2026.md §EXP-3310.

Tests two modes for combining VIX-term-structure slope with an options
order-flow imbalance proxy on the v8a (8-stream) portfolio:

  Mode 1 — ENTRY FILTER
    Use composite alpha signal as a leverage gate on the v8a pooled
    OOS daily return: leverage[t] = 1.0 when α[t-1] ≥ θ_low,
    gate_leverage otherwise. Mirrors EXP-3303 mechanics so the only
    moving piece is the feature set.

  Mode 2 — STANDALONE ALPHA STREAM
    Synthesize a 9th return series by sizing daily SPY exposure with
    sign(α[t-1]). Standalone_return[t] = signal[t-1] · SPY_logret[t].
    Add as 9th column to v8a cube; rerun LW walk-forward; compare
    Sharpe / CAGR / DD / correlations.

PROXY SUBSTITUTION (flagged prominently in report):
  Direct CBOE put/call volume series (^CPC, ^CPCE, ^CPCI) all return
  Yahoo 404 in May 2026. We substitute two documented surrogates:
    • ^SKEW         → tail-bias proxy for P/C IV skew (CBOE's published
                       OTM-put vs OTM-call standardised pricing index)
    • ΔVIX / VIX    → panic-flow proxy (intraday-level vol jumps as a
                       coarse stand-in for short-term P/C imbalance)
  See report caveat box for limitations.

Features (no look-ahead, all rolling stats trailing 63d):
  ts_slope        = (VIX3M - VIX) / VIX             — relative term spread
  ts_slope_z63    = trailing z-score
  skew_z63        = trailing z-score of ^SKEW
  dvix_z63        = trailing z-score of ΔVIX / VIX
  composite_alpha = ( ts_slope_z - skew_z - dvix_z ) / sqrt(3)
                    high = favorable for short-vol harvest
                    low  = unfavorable

Rule Zero: real v8a cube (EXP-2600), real Yahoo features, real SPY
prices for the standalone stream. No synthetic data.

Outputs
  compass/reports/exp3310_term_structure_order_flow.json
  compass/reports/exp3310_term_structure_order_flow.html
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
    walk_forward_lw,
    fold_metrics,
    apply_net_drag,
    NET_DRAG_BPS,
    TRADING_DAYS,
)
from compass.exp3303_regime_transition_dd import (  # noqa: E402
    fetch_regime_features,
    ZSCORE_WINDOW,
)

REPORT_JSON = ROOT / "compass" / "reports" / "exp3310_term_structure_order_flow.json"
REPORT_HTML = ROOT / "compass" / "reports" / "exp3310_term_structure_order_flow.html"
SPY_CACHE = ROOT / "compass" / "cache" / "exp3310_spy.pkl"

V8A_TARGET_VOL = 0.18

# Mode 1 sweep — leverage gate when alpha < θ_low
ALPHA_LOW_THETAS = [-0.5, -1.0, -1.5]
GATE_LEVERAGES = [0.0, 0.3, 0.5]

# Mode 2 — standalone stream sizing
STANDALONE_SIGNAL_THRESHOLD = 0.5     # |α| > 0.5 → ±1, else 0
STANDALONE_VOL_TARGET = 0.10          # rescale standalone series to 10% ann vol


# ── Feature engineering ──────────────────────────────────────────────


def build_composite_alpha(features: pd.DataFrame) -> pd.DataFrame:
    """Compute TS slope + skew + ΔVIX/VIX z-scores → composite alpha.

    High composite_alpha = favorable for short-vol harvest:
      ts_slope high (positive)  = strong contango = calm = bullish
      skew     high             = elevated tail-fear pricing = bearish
      ΔVIX/VIX high             = vol spiking = bearish

      α = ( ts_slope_z  -  skew_z  -  dvix_z ) / sqrt(3)
    """
    f = features.copy()
    f["ts_slope"] = (f["vix3m"] - f["vix"]) / f["vix"]
    f["dvix_pct"] = f["vix"].diff() / f["vix"].shift(1)

    for col in ["ts_slope", "skew", "dvix_pct"]:
        roll = f[col].rolling(ZSCORE_WINDOW, min_periods=ZSCORE_WINDOW)
        f[f"{col}_z"] = (f[col] - roll.mean()) / roll.std(ddof=1)

    f["composite_alpha"] = (
        f["ts_slope_z"] - f["skew_z"] - f["dvix_pct_z"]
    ) / math.sqrt(3.0)
    return f


# ── Mode 1: entry filter ─────────────────────────────────────────────


def apply_alpha_filter(
    pooled: pd.Series, alpha: pd.Series,
    theta_low: float, gate_leverage: float,
) -> Tuple[pd.Series, pd.Series]:
    """Gate v8a leverage when α[t-1] < θ_low. Warm-up days → leverage 1.0."""
    a_lag = alpha.shift(1).reindex(pooled.index)
    leverage = np.where(a_lag.values < theta_low, gate_leverage, 1.0)
    leverage = pd.Series(leverage, index=pooled.index)
    leverage = leverage.where(~a_lag.isna(), 1.0)
    return pooled * leverage, leverage


def fraction_gated(leverage: pd.Series) -> Dict[str, float]:
    n = len(leverage)
    n_gated = int((leverage < 1.0 - 1e-9).sum())
    return {
        "days_total": n,
        "days_gated": n_gated,
        "pct_gated": round(100 * n_gated / n, 3),
    }


# ── Mode 2: standalone alpha stream ──────────────────────────────────


def fetch_spy(start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """SPY close prices from Yahoo (cached). Returns daily log returns aligned."""
    if SPY_CACHE.exists():
        s = pd.read_pickle(SPY_CACHE)
        if s.index.min() <= start and s.index.max() >= end:
            return s.loc[(s.index >= start) & (s.index <= end)].copy()

    import yfinance as yf
    print(f"[spy] fetching SPY from Yahoo "
          f"{start.date()}..{end.date()}+30d…")
    raw = yf.download(
        "SPY", start=(start - pd.Timedelta(days=30)).date(),
        end=(end + pd.Timedelta(days=30)).date(),
        progress=False, auto_adjust=True,
    )["Close"]
    if isinstance(raw, pd.DataFrame):
        raw = raw.iloc[:, 0]
    SPY_CACHE.parent.mkdir(parents=True, exist_ok=True)
    raw.to_pickle(SPY_CACHE)
    print(f"[spy] cached → {SPY_CACHE}")
    return raw.loc[(raw.index >= start) & (raw.index <= end)].copy()


def build_standalone_stream(
    alpha: pd.Series, spy_close: pd.Series, index: pd.DatetimeIndex,
    threshold: float = STANDALONE_SIGNAL_THRESHOLD,
    target_vol: float = STANDALONE_VOL_TARGET,
) -> pd.Series:
    """signal[t] = sign(α[t-1]) when |α[t-1]| > threshold, else 0.
    standalone_return[t] = signal[t] * SPY_logret[t]. Rescaled to target_vol.
    """
    spy_lr = np.log(spy_close).diff().reindex(index).fillna(0.0)
    a_lag = alpha.shift(1).reindex(index)
    sig = np.where(a_lag.values > threshold, 1.0,
                   np.where(a_lag.values < -threshold, -1.0, 0.0))
    sig = pd.Series(sig, index=index)
    sig = sig.where(~a_lag.isna(), 0.0)
    raw = sig * spy_lr
    realised_vol = float(raw.std(ddof=1)) * math.sqrt(TRADING_DAYS)
    if realised_vol > 1e-9:
        raw = raw * (target_vol / realised_vol)
    return raw.rename("ts_of_alpha")


# ── Main ─────────────────────────────────────────────────────────────


def main() -> None:
    print("=" * 72)
    print("EXP-3310 — VIX term structure + order-flow alpha enhancement")
    print("=" * 72)

    # 1. v8a baseline ---------------------------------------------------
    print("\n[1/6] Building v8a cube + walk-forward LW (target_vol=0.18)…")
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

    # 2. Features (^VIX, ^VIX3M, ^SKEW reused from EXP-3303 cache) ----
    print("\n[2/6] Fetching regime features (^VIX, ^VIX3M, ^VVIX, ^SKEW)…")
    feats_raw = fetch_regime_features(pooled.index[0], pooled.index[-1])
    feats = build_composite_alpha(feats_raw)
    feats_aligned = feats.reindex(pooled.index).ffill()
    alpha = feats_aligned["composite_alpha"]
    print(f"      composite α percentiles "
          f"p05={alpha.quantile(0.05):.2f}  "
          f"p50={alpha.quantile(0.50):.2f}  "
          f"p95={alpha.quantile(0.95):.2f}")
    print(f"      α range [{alpha.min():.2f}, {alpha.max():.2f}]")

    # 3. Mode 1: entry filter sweep -----------------------------------
    print("\n[3/6] Mode 1 — entry filter sweep (θ_low × gate_leverage)…")
    print(f"{'θ_low':>6}  {'gate':>5}  "
          f"{'gross_SR':>9}  {'net_SR':>7}  {'CAGR':>7}  {'DD':>6}  "
          f"{'gated%':>7}")
    mode1_sweep: List[Dict] = []
    for theta in ALPHA_LOW_THETAS:
        for g in GATE_LEVERAGES:
            gated, lev = apply_alpha_filter(pooled, alpha, theta, g)
            g_gross = fold_metrics(gated)
            g_net = fold_metrics(apply_net_drag(gated))
            stats = fraction_gated(lev)
            mode1_sweep.append({
                "theta_low": theta, "gate_leverage": g,
                "gross": g_gross, "net": g_net,
                "trade_impact": stats,
            })
            print(f"{theta:>6.1f}  {g:>5.2f}  "
                  f"{g_gross['sharpe']:>9.3f}  {g_net['sharpe']:>7.3f}  "
                  f"{g_net['cagr_pct']:>6.1f}%  "
                  f"{g_gross['max_dd_pct']:>5.2f}%  "
                  f"{stats['pct_gated']:>6.2f}%")

    base_dd = abs(base_gross_m["max_dd_pct"])
    candidates = [s for s in mode1_sweep
                  if abs(s["gross"]["max_dd_pct"]) <= base_dd]
    best_filter = max(candidates if candidates else mode1_sweep,
                      key=lambda s: s["net"]["sharpe"])
    print(f"\n      Best filter: θ_low={best_filter['theta_low']:.1f}  "
          f"gate={best_filter['gate_leverage']:.2f}  "
          f"net SR {best_filter['net']['sharpe']:.3f}  "
          f"DD {best_filter['gross']['max_dd_pct']:.2f}%")

    # 4. Mode 2: standalone alpha stream --------------------------------
    print("\n[4/6] Mode 2 — standalone alpha stream (SPY-timed by α)…")
    spy_close = fetch_spy(pooled.index[0], pooled.index[-1])
    standalone = build_standalone_stream(alpha, spy_close, v8a.index)
    sa_full = standalone.reindex(pooled.index).fillna(0.0)
    sa_metrics = fold_metrics(sa_full)
    print(f"      standalone Sharpe (full series): {sa_metrics['sharpe']:.3f}")
    print(f"      standalone vol: {sa_metrics['vol_pct']:.2f}%  "
          f"DD: {sa_metrics['max_dd_pct']:.2f}%")

    # Correlation to existing 8 streams
    corrs = {}
    for col in v8a.columns:
        c = float(np.corrcoef(
            v8a[col].reindex(pooled.index).fillna(0.0).values,
            sa_full.values,
        )[0, 1])
        corrs[col] = round(c, 4)
    print(f"      correlation to v8a streams: "
          + ", ".join(f"{k}={v:+.2f}" for k, v in corrs.items()))

    # Add as 9th stream and re-walk-forward
    v8a_plus = v8a.copy()
    v8a_plus["ts_of_alpha"] = standalone.reindex(v8a.index).fillna(0.0)
    pooled9, folds9 = walk_forward_lw(v8a_plus, target_vol=V8A_TARGET_VOL)
    pooled9 = pooled9.dropna()
    enh_gross_m = fold_metrics(pooled9)
    enh_net_m = fold_metrics(apply_net_drag(pooled9))
    print(f"      9-stream gross: SR {enh_gross_m['sharpe']:.3f}  "
          f"CAGR {enh_gross_m['cagr_pct']:.1f}%  "
          f"DD {enh_gross_m['max_dd_pct']:.2f}%")
    print(f"      9-stream net  : SR {enh_net_m['sharpe']:.3f}  "
          f"CAGR {enh_net_m['cagr_pct']:.1f}%  "
          f"DD {enh_net_m['max_dd_pct']:.2f}%")

    # 5. Verdict --------------------------------------------------------
    print("\n[5/6] Verdict")
    print("-" * 72)
    filter_lift_gross = best_filter["gross"]["sharpe"] - base_gross_m["sharpe"]
    filter_lift_net = best_filter["net"]["sharpe"] - base_net_m["sharpe"]
    standalone_lift_gross = enh_gross_m["sharpe"] - base_gross_m["sharpe"]
    standalone_lift_net = enh_net_m["sharpe"] - base_net_m["sharpe"]
    print(f"  Mode 1 (filter)     Δ gross SR: {filter_lift_gross:+.3f}  "
          f"Δ net SR: {filter_lift_net:+.3f}")
    print(f"  Mode 2 (standalone) Δ gross SR: {standalone_lift_gross:+.3f}  "
          f"Δ net SR: {standalone_lift_net:+.3f}")
    max_corr = max(abs(c) for c in corrs.values())
    print(f"  Standalone max |corr| to existing streams: {max_corr:.3f}")

    if max(filter_lift_gross, standalone_lift_gross) >= 0.20:
        verdict = "MATERIAL_LIFT"
    elif max(filter_lift_gross, standalone_lift_gross) >= 0.05:
        verdict = "MARGINAL_LIFT"
    elif max(filter_lift_gross, standalone_lift_gross) >= 0.0:
        verdict = "FLAT"
    else:
        verdict = "NEGATIVE"
    print(f"  Verdict: {verdict}")

    # 6. Persist --------------------------------------------------------
    print("\n[6/6] Writing reports…")
    payload = {
        "experiment": "EXP-3310",
        "title": "VIX term structure + order-flow imbalance alpha (v8a)",
        "generated": datetime.now().isoformat(timespec="seconds"),
        "rule_zero": True,
        "spec_source": "compass/reports/exp3300_literature_review_may2026.md §EXP-3310",
        "data_caveat": (
            "PROXY SUBSTITUTION: Direct CBOE put/call volume series "
            "(^CPC, ^CPCE, ^CPCI) all return Yahoo 404 as of May 2026. "
            "We substitute (a) ^SKEW as a tail-bias / P-C IV-skew proxy, "
            "and (b) ΔVIX/VIX as a panic-flow proxy. ^SKEW is the CBOE "
            "standardised pricing of OTM puts vs OTM calls and is a "
            "documented surrogate for option-flow asymmetry; ΔVIX/VIX "
            "captures intraday vol-jump pressure. These are not direct "
            "P/C volume measures and the experiment SHOULD be re-run "
            "with true P/C imbalance data once a feed is available "
            "(IBKR, CBOE DataShop, or polygon.io)."
        ),
        "config": {
            "v8a_target_vol": V8A_TARGET_VOL,
            "zscore_window": ZSCORE_WINDOW,
            "alpha_low_thetas": ALPHA_LOW_THETAS,
            "gate_leverages": GATE_LEVERAGES,
            "standalone_signal_threshold": STANDALONE_SIGNAL_THRESHOLD,
            "standalone_vol_target": STANDALONE_VOL_TARGET,
            "drag_bps": NET_DRAG_BPS,
            "tickers": ["^VIX", "^VIX3M", "^VVIX", "^SKEW", "SPY"],
        },
        "baseline": {
            "gross": base_gross_m,
            "net": base_net_m,
        },
        "feature_summary": {
            "n_obs": int(len(feats_aligned.dropna())),
            "alpha_p05": float(alpha.quantile(0.05)),
            "alpha_p50": float(alpha.quantile(0.50)),
            "alpha_p95": float(alpha.quantile(0.95)),
            "alpha_min": float(alpha.min()),
            "alpha_max": float(alpha.max()),
        },
        "mode1_filter": {
            "sweep": mode1_sweep,
            "best": best_filter,
            "delta_gross_sharpe": round(filter_lift_gross, 4),
            "delta_net_sharpe": round(filter_lift_net, 4),
            "delta_max_dd_pct": round(
                best_filter["gross"]["max_dd_pct"] - base_gross_m["max_dd_pct"], 4
            ),
        },
        "mode2_standalone": {
            "standalone_metrics": sa_metrics,
            "correlations_to_streams": corrs,
            "max_abs_corr": round(max_corr, 4),
            "enhanced_gross": enh_gross_m,
            "enhanced_net": enh_net_m,
            "delta_gross_sharpe": round(standalone_lift_gross, 4),
            "delta_net_sharpe": round(standalone_lift_net, 4),
            "delta_max_dd_pct": round(
                enh_gross_m["max_dd_pct"] - base_gross_m["max_dd_pct"], 4
            ),
            "delta_cagr_pct": round(
                enh_gross_m["cagr_pct"] - base_gross_m["cagr_pct"], 4
            ),
        },
        "verdict": {
            "code": verdict,
            "best_delta_gross_sharpe": round(
                max(filter_lift_gross, standalone_lift_gross), 4
            ),
            "best_mode": "filter" if filter_lift_gross >= standalone_lift_gross
                         else "standalone",
        },
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(payload, indent=2, default=str))
    print(f"[report] → {REPORT_JSON}")

    REPORT_HTML.write_text(build_html(payload), encoding="utf-8")
    print(f"[report] → {REPORT_HTML}")


# ── HTML ─────────────────────────────────────────────────────────────


def build_html(p: Dict) -> str:
    cfg = p["config"]
    base = p["baseline"]
    m1 = p["mode1_filter"]
    m2 = p["mode2_standalone"]
    v = p["verdict"]
    best_filter = m1["best"]

    color = {
        "MATERIAL_LIFT":  "#16a34a",
        "MARGINAL_LIFT":  "#65a30d",
        "FLAT":           "#f59e0b",
        "NEGATIVE":       "#dc2626",
    }.get(v["code"], "#64748b")

    sweep_rows = ""
    for s in m1["sweep"]:
        sg = s["gross"]
        sn = s["net"]
        is_best = (s["theta_low"] == best_filter["theta_low"]
                   and s["gate_leverage"] == best_filter["gate_leverage"])
        css = "best" if is_best else ""
        sweep_rows += (
            f"<tr class='{css}'>"
            f"<td>{s['theta_low']:.1f}</td>"
            f"<td>{s['gate_leverage']:.2f}</td>"
            f"<td>{sg['sharpe']:.3f}</td>"
            f"<td>{sn['sharpe']:.3f}</td>"
            f"<td>{sn['cagr_pct']:+.1f}%</td>"
            f"<td>{sg['max_dd_pct']:.2f}%</td>"
            f"<td>{s['trade_impact']['pct_gated']:.2f}%</td>"
            f"</tr>"
        )

    corr_rows = ""
    for k, c in m2["correlations_to_streams"].items():
        cc = "#dc2626" if abs(c) > 0.5 else (
            "#f59e0b" if abs(c) > 0.3 else "#16a34a")
        corr_rows += (
            f"<tr><td>{k}</td>"
            f"<td style='color:{cc};font-weight:700'>{c:+.4f}</td></tr>"
        )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>EXP-3310 — TS + Order-Flow Alpha</title>
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
tr.best{{background:#ecfdf5;font-weight:600;}}
.kv{{display:grid;grid-template-columns:repeat(2,1fr);gap:6px 18px;font-size:0.9em;margin:10px 0;}}
.kv b{{color:#475569;}}
</style></head><body>

<h1>EXP-3310 — VIX term structure + order-flow alpha</h1>
<p class="muted">Spec: literature review §EXP-3310. Combines VIX
term-structure slope with options order-flow imbalance proxy. Tests
both as entry filter and as standalone alpha stream on v8a.
{datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<div class="caveat">
<strong>⚠ PROXY SUBSTITUTION.</strong> Direct CBOE put/call volume
tickers (^CPC, ^CPCE, ^CPCI) all return Yahoo 404 as of May 2026.
We substitute <code>^SKEW</code> as a tail-bias proxy for P-C IV
skew (CBOE's published OTM-put vs OTM-call standardised pricing) and
<code>ΔVIX/VIX</code> as a panic-flow proxy for intraday vol-jump
pressure. These are documented surrogates — not direct P/C volume —
so this experiment SHOULD be re-run with true P/C imbalance data
once a feed is available (IBKR, CBOE DataShop, polygon.io).
</div>

<div class="sources">
<strong>Rule Zero.</strong> v8a cube from EXP-2600 (real IronVault +
Yahoo). Features ^VIX / ^VIX3M / ^SKEW fetched live from Yahoo. SPY
fetched live from Yahoo for standalone-stream timing trade. All gate /
sizing decisions use α[t-1] (no look-ahead). Walk-forward LW
risk-parity, target_vol = {cfg['v8a_target_vol']:.2f}; net SR includes
EXP-2570 {cfg['drag_bps']:.1f} bps drag.
</div>

<div class="verdict">
<span class="badge">{v['code']}</span>
<div class="kv" style="margin-top:14px">
<div><b>Best Δ gross Sharpe</b></div>
<div>{v['best_delta_gross_sharpe']:+.3f} (mode: {v['best_mode']})</div>
<div><b>Mode 1 (filter) Δ gross SR</b></div>
<div>{m1['delta_gross_sharpe']:+.3f}</div>
<div><b>Mode 2 (standalone) Δ gross SR</b></div>
<div>{m2['delta_gross_sharpe']:+.3f}</div>
<div><b>Standalone Sharpe</b></div>
<div>{m2['standalone_metrics']['sharpe']:.3f}</div>
<div><b>Standalone max |ρ| to streams</b></div>
<div>{m2['max_abs_corr']:.3f}</div>
<div><b>Baseline gross SR</b></div><div>{base['gross']['sharpe']:.3f}</div>
</div>
</div>

<h2>1. Mode 1 — Entry filter sweep</h2>
<p class="muted">Gate leverage when α[t-1] &lt; θ<sub>low</sub>. Best
row highlighted: max net SR among configs with DD ≤ baseline
{base['gross']['max_dd_pct']:.2f}%.</p>
<table>
<thead><tr>
<th>θ<sub>low</sub></th><th>gate lev</th>
<th>Gross SR</th><th>Net SR</th><th>Net CAGR</th><th>Max DD</th>
<th>Days gated</th>
</tr></thead>
<tbody>{sweep_rows}</tbody>
</table>

<h2>2. Mode 2 — Standalone alpha stream</h2>
<p class="muted">Standalone synthesis: signal[t] = sign(α[t-1]) when
|α[t-1]| &gt; {cfg['standalone_signal_threshold']:.1f}, else 0;
return = signal · SPY log-return; rescaled to
{cfg['standalone_vol_target']*100:.0f}% annualised vol.</p>

<div class="kv">
<div><b>Standalone Sharpe</b></div>
<div>{m2['standalone_metrics']['sharpe']:.3f}</div>
<div><b>Standalone CAGR</b></div>
<div>{m2['standalone_metrics']['cagr_pct']:+.2f}%</div>
<div><b>Standalone vol</b></div>
<div>{m2['standalone_metrics']['vol_pct']:.2f}%</div>
<div><b>Standalone max DD</b></div>
<div>{m2['standalone_metrics']['max_dd_pct']:.2f}%</div>
<div><b>9-stream gross SR</b></div>
<div>{m2['enhanced_gross']['sharpe']:.3f}
(Δ {m2['delta_gross_sharpe']:+.3f})</div>
<div><b>9-stream net SR</b></div>
<div>{m2['enhanced_net']['sharpe']:.3f}
(Δ {m2['delta_net_sharpe']:+.3f})</div>
<div><b>9-stream CAGR</b></div>
<div>{m2['enhanced_gross']['cagr_pct']:+.2f}%
(Δ {m2['delta_cagr_pct']:+.2f}%)</div>
<div><b>9-stream max DD</b></div>
<div>{m2['enhanced_gross']['max_dd_pct']:.2f}%
(Δ {m2['delta_max_dd_pct']:+.2f}%)</div>
</div>

<h3>2a. Correlation of standalone return to v8a streams</h3>
<table>
<thead><tr><th>Stream</th><th>ρ</th></tr></thead>
<tbody>{corr_rows}</tbody>
</table>
<p class="muted">|ρ| &gt; 0.5 red, 0.3-0.5 amber, &lt; 0.3 green —
signals near-orthogonality is desirable for portfolio addition.</p>

<h2>3. Composite alpha distribution</h2>
<table>
<thead><tr><th>Stat</th><th>Value</th></tr></thead>
<tbody>
<tr><td>n observations</td><td>{p['feature_summary']['n_obs']}</td></tr>
<tr><td>p05</td><td>{p['feature_summary']['alpha_p05']:.3f}</td></tr>
<tr><td>p50</td><td>{p['feature_summary']['alpha_p50']:.3f}</td></tr>
<tr><td>p95</td><td>{p['feature_summary']['alpha_p95']:.3f}</td></tr>
<tr><td>min</td><td>{p['feature_summary']['alpha_min']:.3f}</td></tr>
<tr><td>max</td><td>{p['feature_summary']['alpha_max']:.3f}</td></tr>
</tbody>
</table>

<p style="margin-top:3em;color:#94a3b8;font-size:0.78em;text-align:center">
compass/exp3310_term_structure_order_flow.py · Rule Zero · real Yahoo + IronVault data
</p>
</body></html>"""


if __name__ == "__main__":
    main()
