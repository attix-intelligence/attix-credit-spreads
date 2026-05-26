"""EXP-3280 — Sector dealer-GEX proxy + gate for v8a xlf_cs / xli_cs.

Hypothesis (H2 from research/DEALER_GEX_LITERATURE.md §6):
  "Sector-ETF dealer GEX is materially more negative than SPX, and
   predicts forward 5-day realized vol."

Anchor: Barbon-Buraschi 2020 (illiquidity × gamma → momentum) +
literature gap on sector ETFs (Adams-Dim 2024 CBOE methodology never
applied to XLF/XLI).

Test plan
---------
(a) Two-sample t-test on daily proxy GEX means:
       mean(GEX_XLF) − mean(GEX_SPY) < 0
       mean(GEX_XLI) − mean(GEX_SPY) < 0
(b) Panel regression on sector tickers (XLF, XLI):
       RV_{t,t+5} = α + β·1{GEX_t < 10th-pctile} + γ·VIX_t + ε
       Pre-registered prediction: β > 0, t-stat > 2.
(c) v8a gating proposal: scale xlf_cs / xli_cs stream leverage by
    daily GEX percentile bucket; backtest pooled v8a OOS vs gated.

⚠ DATA-LIMITATION PROXY (flagged in report)
-------------------------------------------
IronVault `option_daily.open_interest` is uniformly NULL across XLF /
XLI / SPY (verified 2026-05). yfinance returns OI for current snapshot
only — no history. CBOE DataShop free sample requires manual download.

We substitute IronVault per-contract DAILY VOLUME for OI, applying the
same GPP-style sign rule (calls positive, puts negative, gamma-weighted
under a BS gamma with σ = 30d realised vol of the underlier). This is
a *flow* proxy, not a *stock* proxy:
  - True OI-GEX measures standing dealer inventory bias.
  - Volume-GEX measures one-day flow pressure (∂OI / ∂t with sign).
The H2 mechanism (heavy put-flow → dealers absorbing → more-negative
gamma → predicts RV) is signed the same way under both definitions,
so a directional test remains valid. Effect sizes will likely be
*smaller* than a true OI-GEX (volume is noisier than the integrated
OI signal). Conclusions stating "validated" must be re-checked once
OI history is sourced (~ $50 CBOE DataShop annual feed).

Method details
--------------
For each (ticker, date):
  1. Pull spot S from Yahoo daily close.
  2. σ = trailing 30-day realised vol of S (lower-cap 5%, upper-cap 100%).
  3. For each (contract, OI-day-row) with vol ≥ MIN_VOL:
       - DTE = (expiration − date).days, require 0 < DTE ≤ 90.
       - Moneyness filter: K ∈ [0.85·S, 1.15·S].
       - Black-Scholes gamma:
           d1 = (ln(S/K) + 0.5·σ²·T) / (σ·√T)
           γ  = φ(d1) / (S·σ·√T)
       - sign = +1 for call, −1 for put
       - contribution = sign · γ · VOLUME · S² · 100
  4. GEX_raw[t] = Σ contributions
     GEX_norm[t] = GEX_raw[t] / max(1, Σ |contribution|)   (∈ [−1, +1])

We report and test on **GEX_norm** because the raw scale is
non-comparable across tickers (different OI universes); the norm is
the gamma-weighted call-vs-put flow imbalance fraction.

Forward 5-day realized vol:
  RV_{t,t+5} = sqrt(252) · sqrt( Σ_{u=t+1}^{t+5} log_return(S_u)² / 5 )

VIX series fetched from Yahoo (^VIX).

Backtest
--------
Apply gate to v8a OOS daily series, but only to the XLF/XLI-attributed
component of the pooled return. Since v8a's LW walk-forward returns
a single pooled series, we instead gate the stream-level cube **before**
LW fitting and re-run walk-forward to get a clean comparison:
  - Baseline: standard v8a walk-forward (no gate)
  - Gated:    multiply xlf_cs[t] and xli_cs[t] by gate_factor(GEX_t)
              before walk-forward
  - Gate function:
        low_pctile (GEX ≤ 10th): factor = 0.0 (skip)
        high_pctile (GEX ≥ 90th): factor = 1.5
        otherwise: factor = 1.0
  Note: applying the gate to the cube changes the LW covariance estimate
  inside the training window, so the gated weights are different from
  baseline — this is the production behaviour we want to measure
  (gate produces a different portfolio, not just a leverage tweak).

Outputs
  compass/reports/exp3280_sector_gex_gate.json
  compass/reports/exp3280_sector_gex_gate.html
  compass/cache/exp3280_gex_series.pkl  (cached GEX series, ticker → DataFrame)
"""

from __future__ import annotations

import json
import math
import sqlite3
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

REPORT_JSON = ROOT / "compass" / "reports" / "exp3280_sector_gex_gate.json"
REPORT_HTML = ROOT / "compass" / "reports" / "exp3280_sector_gex_gate.html"
GEX_CACHE = ROOT / "compass" / "cache" / "exp3280_gex_series.pkl"
SPOT_CACHE = ROOT / "compass" / "cache" / "exp3280_spot_prices.pkl"
VIX_CACHE = ROOT / "compass" / "cache" / "exp3280_vix.pkl"
IV_DB = ROOT / "data" / "options_cache.db"

# H2 window — anchored to lit review §H2 (2022–2026)
START_DATE = pd.Timestamp("2022-01-01")
END_DATE = pd.Timestamp("2025-12-31")

TICKERS_SECTOR = ["XLF", "XLI"]
TICKER_BENCHMARK = "SPY"
ALL_TICKERS = TICKERS_SECTOR + [TICKER_BENCHMARK]

# Filtering for liquid contracts
MIN_VOLUME = 10
MAX_DTE = 90
MIN_DTE = 1
MONEYNESS_BAND = 0.15           # ±15% of spot

# Realized vol window for gamma
RV_WINDOW = 30
RV_FLOOR = 0.05
RV_CEIL = 1.00

# Forward RV window for H2
FORWARD_RV_DAYS = 5

# Gate thresholds (percentile of own series)
GATE_LOW_PCTILE = 10
GATE_HIGH_PCTILE = 90
GATE_LOW_FACTOR = 0.0
GATE_HIGH_FACTOR = 1.5
GATE_MID_FACTOR = 1.0

V8A_TARGET_VOL = 0.18


# ── Utilities ────────────────────────────────────────────────────────


def norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_gamma(S: float, K: float, T_years: float, sigma: float) -> float:
    """Black-Scholes gamma (per share, zero rates/div for simplicity)."""
    if T_years <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T_years) / (sigma * math.sqrt(T_years))
    return norm_pdf(d1) / (S * sigma * math.sqrt(T_years))


def fetch_spot_history(tickers: List[str]) -> Dict[str, pd.Series]:
    """Fetch daily close prices via Yahoo with cache."""
    if SPOT_CACHE.exists():
        cached = pd.read_pickle(SPOT_CACHE)
        if all(t in cached for t in tickers) and \
                all(cached[t].index.min() <= START_DATE - pd.Timedelta(days=RV_WINDOW + 5)
                    for t in tickers):
            return cached
    import yfinance as yf
    print(f"[spot] fetching {tickers} via Yahoo…")
    out: Dict[str, pd.Series] = {}
    for t in tickers + ["^VIX"]:
        raw = yf.download(
            t,
            start=(START_DATE - pd.Timedelta(days=RV_WINDOW + 30)).date(),
            end=(END_DATE + pd.Timedelta(days=FORWARD_RV_DAYS + 5)).date(),
            progress=False, auto_adjust=True,
        )["Close"]
        if isinstance(raw, pd.DataFrame):
            raw = raw.iloc[:, 0]
        out[t] = raw
    SPOT_CACHE.parent.mkdir(parents=True, exist_ok=True)
    pd.to_pickle(out, SPOT_CACHE)
    return out


def compute_realised_vol(close: pd.Series, window: int = RV_WINDOW) -> pd.Series:
    """Trailing annualised log-return RV, clipped."""
    lr = np.log(close).diff()
    rv = lr.rolling(window).std(ddof=1) * math.sqrt(TRADING_DAYS)
    return rv.clip(lower=RV_FLOOR, upper=RV_CEIL)


# ── GEX construction ─────────────────────────────────────────────────


def build_gex_series_for_ticker(
    ticker: str, close: pd.Series, rv: pd.Series,
) -> pd.DataFrame:
    """Pull IronVault option-day rows; compute daily gamma-weighted
    flow-imbalance proxy."""
    if not IV_DB.exists():
        raise FileNotFoundError(f"options_cache.db missing: {IV_DB}")
    print(f"[gex] querying IronVault for {ticker}…")
    conn = sqlite3.connect(str(IV_DB))
    try:
        rows = conn.execute("""
            SELECT od.date,
                   oc.expiration,
                   oc.strike,
                   oc.option_type,
                   od.volume
            FROM option_daily od
            JOIN option_contracts oc ON od.contract_symbol = oc.contract_symbol
            WHERE oc.ticker = ?
              AND od.date >= ?
              AND od.date <= ?
              AND od.volume >= ?
        """, (ticker, str(START_DATE.date()),
              str((END_DATE + pd.Timedelta(days=FORWARD_RV_DAYS + 5)).date()),
              MIN_VOLUME)).fetchall()
    finally:
        conn.close()
    print(f"[gex] {ticker}: {len(rows):,} rows pulled (volume ≥ {MIN_VOLUME})")
    if not rows:
        return pd.DataFrame(columns=["gex_raw", "gex_norm", "n_contracts",
                                     "call_vol", "put_vol"])

    df = pd.DataFrame(rows,
                      columns=["date", "expiration", "strike",
                               "option_type", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    df["expiration"] = pd.to_datetime(df["expiration"])
    df["dte"] = (df["expiration"] - df["date"]).dt.days
    df = df[(df["dte"] >= MIN_DTE) & (df["dte"] <= MAX_DTE)].copy()

    # Spot + σ join
    df["spot"] = df["date"].map(close)
    df["sigma"] = df["date"].map(rv)
    df = df.dropna(subset=["spot", "sigma"]).copy()
    df = df[abs(df["strike"] / df["spot"] - 1.0) <= MONEYNESS_BAND].copy()

    # BS gamma — vectorised
    S = df["spot"].values
    K = df["strike"].values
    T = (df["dte"].values / 365.0).astype(float)
    σ = df["sigma"].values
    sqrtT = np.sqrt(T)
    safe = (T > 0) & (σ > 0) & (S > 0) & (K > 0)
    d1 = np.zeros_like(S)
    d1[safe] = (np.log(S[safe] / K[safe]) + 0.5 * σ[safe] ** 2 * T[safe]) / (σ[safe] * sqrtT[safe])
    pdf = np.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
    gamma = np.zeros_like(S)
    gamma[safe] = pdf[safe] / (S[safe] * σ[safe] * sqrtT[safe])
    sign = np.where(df["option_type"].values == "C", 1.0, -1.0)
    # Contribution (signed, gamma × volume × S² × 100)
    df["contrib"] = sign * gamma * df["volume"].values * (S ** 2) * 100.0
    df["abs_contrib"] = np.abs(gamma * df["volume"].values * (S ** 2) * 100.0)
    df["call_vol"] = np.where(sign > 0, df["volume"].values, 0)
    df["put_vol"] = np.where(sign < 0, df["volume"].values, 0)

    daily = df.groupby("date").agg(
        gex_raw=("contrib", "sum"),
        total_abs=("abs_contrib", "sum"),
        n_contracts=("strike", "count"),
        call_vol=("call_vol", "sum"),
        put_vol=("put_vol", "sum"),
    )
    daily["gex_norm"] = daily["gex_raw"] / daily["total_abs"].clip(lower=1.0)
    daily = daily.drop(columns=["total_abs"])
    return daily


def build_all_gex(spots: Dict[str, pd.Series]) -> Dict[str, pd.DataFrame]:
    if GEX_CACHE.exists():
        cached = pd.read_pickle(GEX_CACHE)
        if all(t in cached for t in ALL_TICKERS):
            print(f"[gex] cache hit {GEX_CACHE}")
            return cached
    gex: Dict[str, pd.DataFrame] = {}
    for t in ALL_TICKERS:
        rv = compute_realised_vol(spots[t])
        gex[t] = build_gex_series_for_ticker(t, spots[t], rv)
        print(f"[gex] {t}: {len(gex[t])} daily obs, "
              f"mean gex_norm = {gex[t]['gex_norm'].mean():+.4f}")
    GEX_CACHE.parent.mkdir(parents=True, exist_ok=True)
    pd.to_pickle(gex, GEX_CACHE)
    print(f"[gex] cached → {GEX_CACHE}")
    return gex


# ── Statistical tests ────────────────────────────────────────────────


def two_sample_test(a: pd.Series, b: pd.Series, label_a: str, label_b: str) -> Dict:
    """Welch t-test for mean(a) − mean(b) < 0."""
    a = a.dropna().values
    b = b.dropna().values
    ma, mb = float(np.mean(a)), float(np.mean(b))
    va, vb = float(np.var(a, ddof=1)), float(np.var(b, ddof=1))
    se = math.sqrt(va / len(a) + vb / len(b))
    t = (ma - mb) / se if se > 1e-12 else 0.0
    # df ≈ Welch-Satterthwaite
    dfn = (va / len(a) + vb / len(b)) ** 2
    dfd = ((va / len(a)) ** 2 / (len(a) - 1) +
           (vb / len(b)) ** 2 / (len(b) - 1))
    df = dfn / dfd if dfd > 1e-12 else len(a) + len(b) - 2
    # one-sided p-value (H1: ma < mb)
    from math import erf, sqrt
    # Use normal approx (df is large)
    p_onesided = 0.5 * (1 + erf(t / sqrt(2.0)))  # P(T < t)
    return {
        "label_a": label_a, "label_b": label_b,
        "mean_a": round(ma, 6), "mean_b": round(mb, 6),
        "delta": round(ma - mb, 6),
        "n_a": len(a), "n_b": len(b),
        "t_stat": round(t, 3),
        "df": round(df, 1),
        "p_value_onesided_less": round(p_onesided, 4),
    }


def panel_regression(
    gex_by_ticker: Dict[str, pd.DataFrame],
    spots: Dict[str, pd.Series],
    vix: pd.Series,
    sector_tickers: List[str],
) -> Dict:
    """RV_{t,t+5} = α + β·1{GEX_t in bottom-10th-pctile} + γ·VIX_t + ε

    Stacked across sector tickers (XLF, XLI) with pooled coefficient.
    Standard errors are HC0 (heteroskedasticity-robust). No clustering
    by ticker.
    """
    rows = []
    for tk in sector_tickers:
        g = gex_by_ticker[tk].copy()
        close = spots[tk]
        # Forward 5-day realized vol from t+1 to t+FORWARD_RV_DAYS
        lr = np.log(close).diff()
        fwd_rv = (lr.shift(-1).rolling(FORWARD_RV_DAYS).std(ddof=1)
                  * math.sqrt(TRADING_DAYS))
        # Bottom decile indicator (per-ticker percentile)
        g["low_gex"] = (g["gex_norm"] <= g["gex_norm"].quantile(GATE_LOW_PCTILE / 100)).astype(int)
        g["fwd_rv"] = fwd_rv.reindex(g.index)
        g["vix"] = vix.reindex(g.index)
        g["ticker"] = tk
        rows.append(g[["fwd_rv", "low_gex", "vix", "ticker"]].dropna())
    panel = pd.concat(rows)
    if len(panel) < 30:
        return {"error": f"panel too small ({len(panel)} rows)"}

    y = panel["fwd_rv"].values.astype(float)
    X = np.column_stack([
        np.ones(len(panel)),
        panel["low_gex"].values.astype(float),
        panel["vix"].values.astype(float),
    ])
    XtX_inv = np.linalg.inv(X.T @ X)
    β = XtX_inv @ X.T @ y
    resid = y - X @ β
    # HC0 robust covariance
    S = X.T @ np.diag(resid ** 2) @ X
    cov_hc0 = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.diag(cov_hc0))
    t = β / se
    n = len(panel)
    from math import erf, sqrt
    p_twosided = [2 * (1 - 0.5 * (1 + erf(abs(ti) / sqrt(2.0)))) for ti in t]
    p_low_gex_onesided_greater = 1 - 0.5 * (1 + erf(t[1] / sqrt(2.0)))

    return {
        "n_obs": int(n),
        "n_by_ticker": {tk: int((panel["ticker"] == tk).sum())
                        for tk in sector_tickers},
        "alpha": round(float(β[0]), 6),
        "beta_low_gex": round(float(β[1]), 6),
        "gamma_vix": round(float(β[2]), 6),
        "se_alpha": round(float(se[0]), 6),
        "se_beta_low_gex": round(float(se[1]), 6),
        "se_gamma_vix": round(float(se[2]), 6),
        "t_alpha": round(float(t[0]), 3),
        "t_beta_low_gex": round(float(t[1]), 3),
        "t_gamma_vix": round(float(t[2]), 3),
        "p_two_sided": {
            "alpha": round(p_twosided[0], 4),
            "beta_low_gex": round(p_twosided[1], 4),
            "gamma_vix": round(p_twosided[2], 4),
        },
        "p_beta_low_gex_onesided_greater": round(p_low_gex_onesided_greater, 4),
        "decision": (
            "H2 confirmed (β > 0, t > 2)" if (β[1] > 0 and t[1] > 2.0)
            else "H2 not confirmed at α=0.025 one-sided"
        ),
    }


# ── Gating backtest ──────────────────────────────────────────────────


def apply_gate_to_cube(
    cube: pd.DataFrame,
    gex_by_ticker: Dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Scale xlf_cs and xli_cs columns by gate factor based on each
    ticker's own GEX percentile (using only data up to t-1)."""
    gated = cube.copy()
    for col, tk in [("xlf_cs", "XLF"), ("xli_cs", "XLI")]:
        if col not in gated.columns or tk not in gex_by_ticker:
            continue
        g = gex_by_ticker[tk]["gex_norm"].copy()
        # Expanding percentiles using ONLY past data (no look-ahead).
        # Use a 252-day trailing window for percentile estimation.
        roll = g.rolling(252, min_periods=63)
        low_thr = roll.quantile(GATE_LOW_PCTILE / 100.0)
        high_thr = roll.quantile(GATE_HIGH_PCTILE / 100.0)
        # Lag by one day — signal[t-1] decides position on t
        g_lag = g.shift(1)
        low_thr = low_thr.shift(1)
        high_thr = high_thr.shift(1)
        factor = pd.Series(GATE_MID_FACTOR, index=g.index)
        factor = factor.where(~(g_lag <= low_thr), GATE_LOW_FACTOR)
        factor = factor.where(~(g_lag >= high_thr), GATE_HIGH_FACTOR)
        # Reindex onto cube index (forward-fill missing days = mid factor)
        factor = factor.reindex(cube.index).fillna(GATE_MID_FACTOR)
        gated[col] = cube[col].values * factor.values
    return gated


# ── Main ─────────────────────────────────────────────────────────────


def main() -> None:
    print("=" * 72)
    print("EXP-3280 — Sector dealer-GEX proxy + gate for v8a xlf/xli streams")
    print("=" * 72)

    print("\n[1/6] Fetching spot prices + VIX (Yahoo, cached)…")
    spots = fetch_spot_history(ALL_TICKERS)
    vix = spots["^VIX"]

    print("\n[2/6] Building IronVault volume-based GEX series per ticker…")
    print("      (⚠ OI uniformly NULL in IronVault — using gamma-weighted")
    print("       volume imbalance as documented flow proxy)")
    gex_by_ticker = build_all_gex(spots)
    summary = {}
    for tk, g in gex_by_ticker.items():
        gn = g["gex_norm"].dropna()
        summary[tk] = {
            "n_obs": int(len(gn)),
            "mean": round(float(gn.mean()), 6),
            "std": round(float(gn.std(ddof=1)), 6),
            "p10": round(float(gn.quantile(0.10)), 6),
            "p50": round(float(gn.median()), 6),
            "p90": round(float(gn.quantile(0.90)), 6),
            "min": round(float(gn.min()), 6),
            "max": round(float(gn.max()), 6),
            "mean_call_vol": int(g["call_vol"].mean()),
            "mean_put_vol": int(g["put_vol"].mean()),
        }
        print(f"      {tk}: mean GEX_norm {summary[tk]['mean']:+.4f}  "
              f"(p10 {summary[tk]['p10']:+.3f}, p90 {summary[tk]['p90']:+.3f})  "
              f"n={summary[tk]['n_obs']}  "
              f"avg call/put vol={summary[tk]['mean_call_vol']:,}/"
              f"{summary[tk]['mean_put_vol']:,}")

    print("\n[3/6] Two-sample tests: H2 leg (a) — sector vs SPY benchmark")
    bench = gex_by_ticker[TICKER_BENCHMARK]["gex_norm"]
    two_sample_results = {}
    for tk in TICKERS_SECTOR:
        res = two_sample_test(
            gex_by_ticker[tk]["gex_norm"], bench,
            label_a=tk, label_b=TICKER_BENCHMARK,
        )
        two_sample_results[tk] = res
        print(f"      mean({tk}) − mean(SPY) = {res['delta']:+.4f}  "
              f"t={res['t_stat']:+.2f}  p₁(less)={res['p_value_onesided_less']:.4f}  "
              f"verdict={'< 0 ✓' if res['delta'] < 0 and res['p_value_onesided_less'] < 0.05 else 'inconclusive'}")

    print("\n[4/6] Panel regression: H2 leg (b)")
    print("      RV_{t,t+5} = α + β·1{GEX < 10th-pctile} + γ·VIX + ε  (sector pool)")
    reg = panel_regression(gex_by_ticker, spots, vix, TICKERS_SECTOR)
    if "error" in reg:
        print(f"      ✗ {reg['error']}")
    else:
        print(f"      n_obs={reg['n_obs']} "
              f"({', '.join(f'{tk}={n}' for tk,n in reg['n_by_ticker'].items())})")
        print(f"      α        = {reg['alpha']:+.4f}  "
              f"(SE {reg['se_alpha']:.4f}, t {reg['t_alpha']:+.2f})")
        print(f"      β_lowGEX = {reg['beta_low_gex']:+.4f}  "
              f"(SE {reg['se_beta_low_gex']:.4f}, t {reg['t_beta_low_gex']:+.2f}, "
              f"p₁>0={reg['p_beta_low_gex_onesided_greater']:.4f})")
        print(f"      γ_VIX    = {reg['gamma_vix']:+.4f}  "
              f"(SE {reg['se_gamma_vix']:.4f}, t {reg['t_gamma_vix']:+.2f})")
        print(f"      → {reg['decision']}")

    print("\n[5/6] Gating backtest — v8a baseline vs gated xlf_cs/xli_cs")
    cubes = build_cubes()
    v8a = cubes["v8a_add_qqq"]
    print(f"      v8a cube: {v8a.shape}  ({v8a.index[0].date()}..{v8a.index[-1].date()})")
    pooled_base, _ = walk_forward_lw(v8a, target_vol=V8A_TARGET_VOL)
    pooled_base = pooled_base.dropna()
    base_gross = fold_metrics(pooled_base)
    base_net = fold_metrics(apply_net_drag(pooled_base))
    print(f"      baseline gross: SR {base_gross['sharpe']:.3f}  "
          f"CAGR {base_gross['cagr_pct']:.1f}%  DD {base_gross['max_dd_pct']:.2f}%")

    v8a_gated = apply_gate_to_cube(v8a, gex_by_ticker)
    pooled_gated, _ = walk_forward_lw(v8a_gated, target_vol=V8A_TARGET_VOL)
    pooled_gated = pooled_gated.dropna()
    g_gross = fold_metrics(pooled_gated)
    g_net = fold_metrics(apply_net_drag(pooled_gated))
    print(f"      gated    gross: SR {g_gross['sharpe']:.3f}  "
          f"CAGR {g_gross['cagr_pct']:.1f}%  DD {g_gross['max_dd_pct']:.2f}%")

    delta_gross = g_gross["sharpe"] - base_gross["sharpe"]
    delta_net = g_net["sharpe"] - base_net["sharpe"]
    delta_dd = g_gross["max_dd_pct"] - base_gross["max_dd_pct"]
    print(f"      Δ gross SR: {delta_gross:+.3f}  "
          f"Δ net SR: {delta_net:+.3f}  Δ DD: {delta_dd:+.2f}%")

    # Gate impact diagnostics
    flat_days = {}
    upsize_days = {}
    for col, tk in [("xlf_cs", "XLF"), ("xli_cs", "XLI")]:
        diff = v8a_gated[col].values - v8a[col].values
        flat_days[tk] = int(((v8a_gated[col].values == 0) &
                             (v8a[col].values != 0)).sum())
        upsize_days[tk] = int((v8a_gated[col].values > v8a[col].values + 1e-9).sum())
    print(f"      gate impact: xlf flat={flat_days['XLF']}, "
          f"upsize={upsize_days['XLF']}; "
          f"xli flat={flat_days['XLI']}, upsize={upsize_days['XLI']}")

    # 6. Verdict + persist
    print("\n[6/6] Verdict")
    h2a_pass = all(r["delta"] < 0 and r["p_value_onesided_less"] < 0.05
                   for r in two_sample_results.values())
    h2b_pass = (reg.get("beta_low_gex", 0) > 0 and reg.get("t_beta_low_gex", 0) > 2.0)
    gate_helps = delta_gross > 0

    if h2a_pass and h2b_pass and gate_helps:
        verdict = "FULL_VALIDATION"
    elif h2a_pass and h2b_pass:
        verdict = "H2_VALIDATED_GATE_NEUTRAL_OR_NEGATIVE"
    elif h2a_pass or h2b_pass:
        verdict = "PARTIAL_VALIDATION"
    else:
        verdict = "H2_REJECTED_ON_THIS_PROXY"

    print(f"  H2(a) sector GEX < SPY: {'PASS' if h2a_pass else 'FAIL'}")
    print(f"  H2(b) β_lowGEX > 0, t > 2: {'PASS' if h2b_pass else 'FAIL'}")
    print(f"  Gate lifts v8a gross SR: {'YES' if gate_helps else 'NO'}")
    print(f"  Overall: {verdict}")

    payload = {
        "experiment": "EXP-3280",
        "title": "Sector dealer-GEX proxy + gate for v8a xlf_cs/xli_cs",
        "generated": datetime.now().isoformat(timespec="seconds"),
        "rule_zero": True,
        "spec_source": "research/DEALER_GEX_LITERATURE.md §6 — H2",
        "data_caveat": (
            "⚠ DATA-LIMITATION PROXY. IronVault `option_daily.open_interest` "
            "is uniformly NULL across XLF / XLI / SPY (verified 2026-05). "
            "yfinance returns OI for current snapshot only; CBOE DataShop "
            "free sample requires manual download. We substitute IronVault "
            "per-contract DAILY VOLUME for OI, applying GPP-style sign rule "
            "+ BS gamma weighting. This is a *flow* proxy not a *stock* "
            "proxy; H2 conclusions stating 'validated' must be re-checked "
            "against true OI history (~$50 CBOE DataShop annual). The "
            "mechanism (heavy put-flow → dealers absorbing → more-negative "
            "gamma → predicts RV) is signed the same way under both "
            "definitions, so a directional test remains valid."
        ),
        "config": {
            "start_date": str(START_DATE.date()),
            "end_date": str(END_DATE.date()),
            "tickers_sector": TICKERS_SECTOR,
            "ticker_benchmark": TICKER_BENCHMARK,
            "min_volume": MIN_VOLUME,
            "max_dte": MAX_DTE,
            "moneyness_band_pct": MONEYNESS_BAND * 100,
            "rv_window": RV_WINDOW,
            "forward_rv_days": FORWARD_RV_DAYS,
            "gate_low_pctile": GATE_LOW_PCTILE,
            "gate_high_pctile": GATE_HIGH_PCTILE,
            "gate_low_factor": GATE_LOW_FACTOR,
            "gate_high_factor": GATE_HIGH_FACTOR,
            "v8a_target_vol": V8A_TARGET_VOL,
            "drag_bps": NET_DRAG_BPS,
        },
        "gex_summary_by_ticker": summary,
        "h2a_two_sample": two_sample_results,
        "h2b_panel_regression": reg,
        "gating_backtest": {
            "baseline_gross": base_gross,
            "baseline_net": base_net,
            "gated_gross": g_gross,
            "gated_net": g_net,
            "delta_gross_sharpe": round(delta_gross, 4),
            "delta_net_sharpe": round(delta_net, 4),
            "delta_max_dd_pct": round(delta_dd, 4),
            "gate_flat_days": flat_days,
            "gate_upsize_days": upsize_days,
        },
        "verdict": {
            "code": verdict,
            "h2a_passed": h2a_pass,
            "h2b_passed": h2b_pass,
            "gate_helps": gate_helps,
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
    s = p["gex_summary_by_ticker"]
    bt = p["gating_backtest"]
    reg = p["h2b_panel_regression"]
    v = p["verdict"]

    color = {
        "FULL_VALIDATION":                        "#16a34a",
        "H2_VALIDATED_GATE_NEUTRAL_OR_NEGATIVE":  "#65a30d",
        "PARTIAL_VALIDATION":                     "#f59e0b",
        "H2_REJECTED_ON_THIS_PROXY":              "#dc2626",
    }.get(v["code"], "#64748b")

    sum_rows = ""
    for tk in ALL_TICKERS:
        t = s[tk]
        sum_rows += (
            f"<tr><td>{tk}</td>"
            f"<td>{t['n_obs']}</td>"
            f"<td>{t['mean']:+.4f}</td>"
            f"<td>{t['p10']:+.3f}</td>"
            f"<td>{t['p50']:+.3f}</td>"
            f"<td>{t['p90']:+.3f}</td>"
            f"<td>{t['mean_call_vol']:,}</td>"
            f"<td>{t['mean_put_vol']:,}</td>"
            f"</tr>"
        )

    ts_rows = ""
    for tk, r in p["h2a_two_sample"].items():
        col = "#16a34a" if (r["delta"] < 0 and r["p_value_onesided_less"] < 0.05) else "#dc2626"
        ts_rows += (
            f"<tr><td>{tk} − SPY</td>"
            f"<td>{r['mean_a']:+.4f}</td>"
            f"<td>{r['mean_b']:+.4f}</td>"
            f"<td style='color:{col};font-weight:700'>{r['delta']:+.4f}</td>"
            f"<td>{r['t_stat']:+.2f}</td>"
            f"<td>{r['p_value_onesided_less']:.4f}</td>"
            f"<td>n_a={r['n_a']}, n_b={r['n_b']}</td>"
            f"</tr>"
        )

    if "error" in reg:
        reg_block = f"<p>Panel regression failed: {reg['error']}</p>"
    else:
        b_col = "#16a34a" if (reg["beta_low_gex"] > 0 and reg["t_beta_low_gex"] > 2.0) else "#dc2626"
        reg_block = f"""
<table>
<thead><tr><th>Coef</th><th>Estimate</th><th>SE (HC0)</th><th>t-stat</th><th>p (2-sided)</th></tr></thead>
<tbody>
<tr><td>α (intercept)</td><td>{reg['alpha']:+.4f}</td><td>{reg['se_alpha']:.4f}</td>
<td>{reg['t_alpha']:+.2f}</td><td>{reg['p_two_sided']['alpha']:.4f}</td></tr>
<tr><td>β · 1{{GEX ≤ p10}}</td>
<td style='color:{b_col};font-weight:700'>{reg['beta_low_gex']:+.4f}</td>
<td>{reg['se_beta_low_gex']:.4f}</td>
<td style='color:{b_col};font-weight:700'>{reg['t_beta_low_gex']:+.2f}</td>
<td>{reg['p_two_sided']['beta_low_gex']:.4f}</td></tr>
<tr><td>γ · VIX</td><td>{reg['gamma_vix']:+.4f}</td><td>{reg['se_gamma_vix']:.4f}</td>
<td>{reg['t_gamma_vix']:+.2f}</td><td>{reg['p_two_sided']['gamma_vix']:.4f}</td></tr>
</tbody>
</table>
<p class="muted">n = {reg['n_obs']} (XLF {reg['n_by_ticker'].get('XLF',0)},
XLI {reg['n_by_ticker'].get('XLI',0)}). One-sided p for β > 0:
<strong>{reg['p_beta_low_gex_onesided_greater']:.4f}</strong>.
Decision: <strong>{reg['decision']}</strong>.</p>"""

    bg = bt["baseline_gross"]
    gg = bt["gated_gross"]
    bn = bt["baseline_net"]
    gn = bt["gated_net"]

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>EXP-3280 — Sector dealer-GEX gate for v8a</title>
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
.kv{{display:grid;grid-template-columns:repeat(2,1fr);gap:6px 18px;font-size:0.9em;margin:10px 0;}}
.kv b{{color:#475569;}}
</style></head><body>

<h1>EXP-3280 — Sector dealer-GEX proxy + gate for v8a</h1>
<p class="muted">Tests H2 from
<code>research/DEALER_GEX_LITERATURE.md</code>: sector-ETF dealer GEX
materially more negative than SPX-proxy and predicts forward 5-day
realised vol. Builds a daily gamma-weighted flow-imbalance proxy
from IronVault per-contract volume (OI history unavailable in cache).
{datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

<div class="caveat">
<strong>⚠ DATA-LIMITATION PROXY.</strong> IronVault
<code>option_daily.open_interest</code> is uniformly NULL across
XLF / XLI / SPY (verified 2026-05). yfinance returns OI for
current snapshot only; CBOE DataShop free sample requires manual
download. We substitute IronVault per-contract DAILY VOLUME for
OI, applying GPP-style sign rule + BS gamma weighting. This is a
<em>flow</em> proxy not a <em>stock</em> proxy. The dealer-pressure
mechanism is signed the same way under both definitions, so a
directional test remains valid, but effect sizes will be noisier
than under true OI. Conclusions stating "validated" must be
re-checked against true OI history (~$50 CBOE DataShop annual).
</div>

<div class="sources">
<strong>Rule Zero.</strong> Real IronVault per-contract daily volume
({cfg['start_date']}..{cfg['end_date']}); ATM filter ±{cfg['moneyness_band_pct']:.0f}%
of spot, DTE ≤ {cfg['max_dte']}, vol ≥ {cfg['min_volume']}. BS gamma
with σ = {cfg['rv_window']}d realized vol of underlier. Yahoo
spot + ^VIX series. v8a cube from EXP-2600 (real IronVault + Yahoo);
walk-forward LW @ target_vol = {cfg['v8a_target_vol']}.
</div>

<div class="verdict">
<span class="badge">{v['code']}</span>
<div class="kv" style="margin-top:14px">
<div><b>H2(a) sector GEX &lt; SPY</b></div>
<div>{'PASS' if v['h2a_passed'] else 'FAIL'}</div>
<div><b>H2(b) β &gt; 0, t &gt; 2 (panel reg.)</b></div>
<div>{'PASS' if v['h2b_passed'] else 'FAIL'}</div>
<div><b>Gate lifts v8a gross SR</b></div>
<div>{'YES' if v['gate_helps'] else 'NO'}
(Δ gross {bt['delta_gross_sharpe']:+.3f}, Δ net {bt['delta_net_sharpe']:+.3f},
Δ DD {bt['delta_max_dd_pct']:+.2f}%)</div>
</div>
</div>

<h2>1. Proxy GEX summary by ticker</h2>
<p class="muted">GEX_norm = gamma-weighted volume imbalance ∈ [−1, +1].
Negative values = put-flow dominant (dealers absorbing → more short
gamma). Positive = call-flow dominant.</p>
<table>
<thead><tr>
<th>Ticker</th><th>n</th><th>Mean</th><th>p10</th><th>p50</th><th>p90</th>
<th>Avg call vol</th><th>Avg put vol</th>
</tr></thead>
<tbody>{sum_rows}</tbody>
</table>

<h2>2. H2(a) — Two-sample test: sector vs SPY benchmark</h2>
<p class="muted">Welch t-test, one-sided H₁: mean(sector) − mean(SPY)
&lt; 0. Significance threshold p₁ &lt; 0.05.</p>
<table>
<thead><tr>
<th>Comparison</th><th>mean A</th><th>mean B</th><th>Δ (A−B)</th>
<th>t-stat</th><th>p₁ (less)</th><th>n</th>
</tr></thead>
<tbody>{ts_rows}</tbody>
</table>

<h2>3. H2(b) — Panel regression</h2>
<p class="muted">RV<sub>t,t+5</sub> = α + β·1{{GEX<sub>t</sub> ≤ 10th pctile}}
+ γ·VIX<sub>t</sub> + ε, pooled XLF + XLI, HC0 robust SEs.</p>
{reg_block}

<h2>4. v8a gating backtest</h2>
<table>
<thead><tr>
<th>Variant</th><th>Gross SR</th><th>Gross CAGR</th><th>Max DD</th>
<th>Net SR</th><th>Net CAGR</th>
</tr></thead>
<tbody>
<tr><td>baseline</td>
<td>{bg['sharpe']:.3f}</td><td>{bg['cagr_pct']:.1f}%</td><td>{bg['max_dd_pct']:.2f}%</td>
<td>{bn['sharpe']:.3f}</td><td>{bn['cagr_pct']:.1f}%</td></tr>
<tr><td>gated (xlf/xli)</td>
<td>{gg['sharpe']:.3f}</td><td>{gg['cagr_pct']:.1f}%</td><td>{gg['max_dd_pct']:.2f}%</td>
<td>{gn['sharpe']:.3f}</td><td>{gn['cagr_pct']:.1f}%</td></tr>
<tr style="font-weight:700;background:#f8fafc">
<td>Δ</td>
<td>{bt['delta_gross_sharpe']:+.3f}</td>
<td>{gg['cagr_pct']-bg['cagr_pct']:+.1f}%</td>
<td>{bt['delta_max_dd_pct']:+.2f}%</td>
<td>{bt['delta_net_sharpe']:+.3f}</td>
<td>{gn['cagr_pct']-bn['cagr_pct']:+.1f}%</td>
</tr>
</tbody>
</table>
<p class="muted">Gate factor: 0× when GEX<sub>t-1</sub> ≤ trailing 10th pctile
(skip entry); 1.5× when ≥ 90th pctile (upsize); 1.0× otherwise.
Trailing percentile uses 252d rolling window with 63d min — no
look-ahead. Days flattened:
XLF {bt['gate_flat_days']['XLF']}, XLI {bt['gate_flat_days']['XLI']}.
Days upsized:
XLF {bt['gate_upsize_days']['XLF']}, XLI {bt['gate_upsize_days']['XLI']}.</p>

<h2>5. Production recommendation</h2>
<p class="muted">If H2(b) and gate-backtest agree (full validation),
add GEX gate to the v8a production sizing layer for XLF/XLI streams.
If H2 validates statistically but gate adds no net SR, the signal
is real but already priced into LW risk-parity weights — consider
using it for off-cycle de-risking only (don't change cube). If H2
fails on this volume proxy, defer the decision until OI history is
available; the volume proxy is intrinsically noisier than OI so a
null result is weaker evidence against H2 than a properly-powered
OI test would be.</p>

<p style="margin-top:3em;color:#94a3b8;font-size:0.78em;text-align:center">
compass/exp3280_sector_gex_gate.py · Rule Zero · IronVault volume + Yahoo
</p>
</body></html>"""


if __name__ == "__main__":
    main()
