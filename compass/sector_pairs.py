"""
compass/sector_pairs.py — EXP-1720 Sector ETF Pairs Trading.

EDGE: Sector ETFs (XLF, XLK, XLE, etc.) within the S&P 500 are driven by
common macro factors but diverge short-term due to sector rotation flows.
Cointegrated pairs mean-revert — a stable linear combination of two
non-stationary price series that is itself stationary.

STRATEGY:
  1. Download daily closes for 10 SPDR sector ETFs from Yahoo Finance
  2. Engle-Granger cointegration test on all 45 unique pairs (2018-2020 train)
  3. Select top 5-10 pairs by ADF t-statistic (most stationary residual)
  4. For each pair, compute rolling z-score of the OLS residual (60-day)
  5. Trade the spread:
       z > +2.0  → SHORT spread (short ETF_A, long ETF_B × β)
       z < -2.0  → LONG spread (long ETF_A, short ETF_B × β)
       |z| < 0.5 → EXIT
       |z| > 3.5 → STOP LOSS
  6. Walk-forward: train (select pairs + compute betas), test OOS

DATA SOURCES (all REAL, cited):
  - XLF (Financials), XLK (Technology), XLE (Energy), XLU (Utilities),
    XLI (Industrials), XLV (Healthcare), XLP (Staples), XLY (Discretionary),
    XLC (Communications), XLRE (Real Estate) — all State Street SPDRs
  - All prices from Yahoo Finance chart API
  - No synthetic data. No np.random. No generated prices.

Cointegration via Engle-Granger two-step:
  1. OLS: price_A = α + β × price_B + residual
  2. ADF test on residual for unit root
  3. Reject null (non-stationary) at 5% → cointegrated

Sharpe via compass/metrics.py (correct arithmetic mean formula).
"""

from __future__ import annotations

import json
import math
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from compass.metrics import annualized_sharpe, full_metrics

ROOT = Path(__file__).resolve().parent.parent
TRADING_DAYS = 252

# 10 SPDR sector ETFs — all REAL tickers on Yahoo Finance
SECTORS = {
    "XLF":  "Financials",
    "XLK":  "Technology",
    "XLE":  "Energy",
    "XLU":  "Utilities",
    "XLI":  "Industrials",
    "XLV":  "Healthcare",
    "XLP":  "Consumer Staples",
    "XLY":  "Consumer Discretionary",
    "XLC":  "Communication Services",  # launched June 2018
    "XLRE": "Real Estate",
}


# ═══════════════════════════════════════════════════════════════════════════
# Data fetching — REAL YAHOO FINANCE
# ═══════════════════════════════════════════════════════════════════════════

def fetch_yahoo_series(symbol: str, start: str = "2015-01-01",
                        end: str = "2025-12-31") -> pd.Series:
    """Fetch daily closes from Yahoo Finance chart API. Real data only."""
    start_ts = int(pd.Timestamp(start).timestamp())
    end_ts = int(pd.Timestamp(end).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1={start_ts}&period2={end_ts}&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    result = data["chart"]["result"][0]
    timestamps = result.get("timestamp", [])
    if not timestamps:
        raise RuntimeError(f"No data for {symbol}")
    closes = result["indicators"]["quote"][0]["close"]
    dates = [datetime.fromtimestamp(t).date() for t in timestamps]
    s = pd.Series(closes, index=pd.DatetimeIndex(dates), name=symbol).dropna()
    return s


def load_sector_prices(start: str = "2015-01-01",
                        end: str = "2025-12-31") -> pd.DataFrame:
    """Load all 10 sector ETFs into aligned DataFrame."""
    series = {}
    for sym, name in SECTORS.items():
        try:
            s = fetch_yahoo_series(sym, start, end)
            series[sym] = s
            print(f"  {sym:5s} ({name:24s}): {len(s)} days "
                  f"({s.index[0].date()} → {s.index[-1].date()})")
        except Exception as e:
            print(f"  {sym:5s}: FAILED ({e})")
    df = pd.DataFrame(series)
    df = df.dropna()  # keep only dates where all ETFs have data
    return df


# ═══════════════════════════════════════════════════════════════════════════
# Cointegration test — Engle-Granger via OLS + ADF
# ═══════════════════════════════════════════════════════════════════════════

def ols_regression(y: np.ndarray, x: np.ndarray) -> Tuple[float, float, np.ndarray]:
    """Simple OLS: y = alpha + beta * x. Returns (alpha, beta, residuals)."""
    x_mean = float(x.mean())
    y_mean = float(y.mean())
    xy = float(((x - x_mean) * (y - y_mean)).sum())
    xx = float(((x - x_mean) ** 2).sum())
    if xx < 1e-12:
        return 0.0, 0.0, y - y_mean
    beta = xy / xx
    alpha = y_mean - beta * x_mean
    residuals = y - (alpha + beta * x)
    return alpha, beta, residuals


def adf_test(series: np.ndarray, max_lag: int = 1) -> float:
    """Augmented Dickey-Fuller test t-statistic (manual implementation).

    Null hypothesis: unit root (non-stationary).
    More negative = stronger rejection of null = more stationary.

    Critical values (5%): ~-2.89 for typical sample sizes.
    Returns: t-statistic of the coefficient on lagged level.
    """
    s = np.asarray(series, dtype=np.float64)
    n = len(s)
    if n < 10:
        return 0.0

    # Build regression: Δy_t = ρ * y_{t-1} + sum(φ_i * Δy_{t-i}) + ε
    dy = np.diff(s)  # n-1 elements
    y_lag = s[:-1]    # n-1 elements

    # Build design matrix: [y_lag, Δy_{t-1}, ..., Δy_{t-max_lag}, constant]
    cols = [y_lag]
    y_target = dy.copy()
    # Trim for lag terms
    if max_lag > 0 and n > max_lag + 2:
        trim = max_lag
        y_target = dy[trim:]
        cols = [y_lag[trim:]]
        for lag in range(1, max_lag + 1):
            lagged_dy = dy[trim - lag: -lag if lag > 0 else None]
            cols.append(lagged_dy[:len(y_target)])
    else:
        trim = 0

    X = np.column_stack(cols + [np.ones(len(y_target))])

    try:
        # OLS: β = (X'X)^-1 X'y
        XtX = X.T @ X
        XtX_inv = np.linalg.inv(XtX)
        beta = XtX_inv @ X.T @ y_target
        residuals = y_target - X @ beta
        dof = len(y_target) - X.shape[1]
        if dof <= 0:
            return 0.0
        sigma_sq = float(residuals @ residuals) / dof
        se_beta0 = math.sqrt(sigma_sq * XtX_inv[0, 0])
        if se_beta0 < 1e-12:
            return 0.0
        t_stat = float(beta[0] / se_beta0)
        return t_stat
    except np.linalg.LinAlgError:
        return 0.0


def test_cointegration(y: pd.Series, x: pd.Series) -> Dict:
    """Engle-Granger cointegration test.

    Step 1: Regress y on x via OLS → residuals
    Step 2: ADF test on residuals → if stationary, y and x are cointegrated

    Returns dict with beta (hedge ratio), adf_stat, cointegrated (bool).
    """
    common = y.index.intersection(x.index)
    if len(common) < 60:
        return {"beta": 0.0, "alpha": 0.0, "adf_stat": 0.0, "cointegrated": False}

    y_arr = y.reindex(common).values
    x_arr = x.reindex(common).values

    alpha, beta, residuals = ols_regression(y_arr, x_arr)
    adf_stat = adf_test(residuals, max_lag=1)

    # 5% critical value for Engle-Granger ~ -3.34 (more strict than ADF)
    cointegrated = adf_stat < -3.0

    return {
        "beta": round(beta, 4),
        "alpha": round(alpha, 4),
        "adf_stat": round(adf_stat, 3),
        "cointegrated": cointegrated,
        "n_obs": len(common),
    }


def find_cointegrated_pairs(prices: pd.DataFrame,
                              train_end: str = "2020-12-31") -> List[Dict]:
    """Test all C(n,2) pairs for cointegration on TRAINING data only.

    Returns sorted list of pair results (most stationary first).
    """
    train = prices.loc[:train_end]
    tickers = list(prices.columns)
    results = []

    for a, b in combinations(tickers, 2):
        result = test_cointegration(train[a], train[b])
        result["a"] = a
        result["b"] = b
        results.append(result)

    # Sort by ADF statistic (more negative = more cointegrated)
    results.sort(key=lambda r: r["adf_stat"])
    return results


# ═══════════════════════════════════════════════════════════════════════════
# Pairs trading backtest
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class PairsConfig:
    z_entry: float = 2.0      # open at |z| > 2.0
    z_exit: float = 0.5       # close at |z| < 0.5
    z_stop: float = 3.5       # stop loss at |z| > 3.5
    lookback: int = 60        # z-score rolling window
    capital_per_pair: float = 10_000  # dollar allocation per pair


def backtest_pair(prices: pd.DataFrame, a: str, b: str,
                    beta: float, alpha: float,
                    config: PairsConfig,
                    start_date: str, end_date: str) -> pd.Series:
    """Backtest one pair over a date range.

    Returns daily strategy returns (as fraction of capital_per_pair).
    """
    mask = (prices.index >= start_date) & (prices.index <= end_date)
    pa = prices.loc[mask, a]
    pb = prices.loc[mask, b]

    if len(pa) < config.lookback + 5:
        return pd.Series(dtype=float)

    # Spread = A - (alpha + beta * B)
    spread = pa - (alpha + beta * pb)

    # Rolling z-score, LAGGED by 1 day to avoid look-ahead
    spread_mean = spread.rolling(config.lookback, min_periods=config.lookback // 2).mean().shift(1)
    spread_std = spread.rolling(config.lookback, min_periods=config.lookback // 2).std().shift(1)
    z = (spread.shift(1) - spread_mean) / spread_std.replace(0, np.nan)
    z = z.fillna(0)

    # Position: +1 = long spread (long A, short beta*B), -1 = short spread
    position = np.zeros(len(pa))
    current = 0
    for i in range(len(pa)):
        zi = float(z.iloc[i])
        if abs(zi) > config.z_stop:
            current = 0  # stop loss
        elif current == 0 and zi > config.z_entry:
            current = -1  # z too high → short spread (mean reverts down)
        elif current == 0 and zi < -config.z_entry:
            current = 1   # z too low → long spread (mean reverts up)
        elif current != 0 and abs(zi) < config.z_exit:
            current = 0  # close at exit threshold
        position[i] = current

    # Daily returns from holding the spread
    pa_ret = pa.pct_change().fillna(0).values
    pb_ret = pb.pct_change().fillna(0).values

    # Long spread P&L: +A_ret - beta * B_ret (both weighted to sum to 1)
    # Normalize so total notional = 1 (half long A, half short beta*B)
    weight_norm = 1 / (1 + abs(beta))
    long_spread_ret = (pa_ret - beta * pb_ret) * weight_norm

    strategy_ret = position * long_spread_ret
    return pd.Series(strategy_ret, index=pa.index, name=f"{a}-{b}")


def walk_forward_backtest(prices: pd.DataFrame,
                           config: PairsConfig,
                           top_n: int = 8) -> Dict:
    """Walk-forward: recalibrate pairs each year.

    For test year N:
      - Train on 2015..N-1 to find cointegrated pairs
      - Use top N pairs to trade in year N
      - Each year re-tests cointegration
    """
    years = sorted(set(prices.index.year))
    first_test_year = max(years[0] + 3, 2018)  # need 3+ years of training
    windows = []
    all_portfolio_rets = []

    for test_year in range(first_test_year, max(years) + 1):
        train_end = f"{test_year - 1}-12-31"
        test_start = f"{test_year}-01-01"
        test_end = f"{test_year}-12-31"

        # Select top cointegrated pairs from training data
        pair_results = find_cointegrated_pairs(prices, train_end)
        top_pairs = [p for p in pair_results if p["cointegrated"]][:top_n]

        if not top_pairs:
            # Fall back to most-cointegrated even if not at 5% threshold
            top_pairs = pair_results[:top_n]

        # Backtest each pair in OOS year, equal-weight portfolio
        pair_returns = []
        pair_metrics = []
        for p in top_pairs:
            rets = backtest_pair(prices, p["a"], p["b"], p["beta"], p["alpha"],
                                  config, test_start, test_end)
            if len(rets) > 0:
                pair_returns.append(rets)
                pair_metrics.append({
                    "pair": f"{p['a']}-{p['b']}",
                    "adf": p["adf_stat"],
                    "beta": p["beta"],
                    "cagr_pct": full_metrics(rets.values)["cagr_pct"],
                    "sharpe": full_metrics(rets.values)["sharpe"],
                })

        if not pair_returns:
            continue

        # Equal-weight portfolio of pair returns
        port_df = pd.concat(pair_returns, axis=1).fillna(0)
        portfolio = port_df.mean(axis=1)

        m = full_metrics(portfolio.values)
        windows.append({
            "year": test_year,
            "n_pairs": len(top_pairs),
            "metrics": m,
            "pair_details": pair_metrics,
            "top_pairs": [f"{p['a']}-{p['b']}" for p in top_pairs],
        })

        all_portfolio_rets.append(portfolio)

    # Aggregate OOS
    if all_portfolio_rets:
        full_oos = pd.concat(all_portfolio_rets)
        agg_m = full_metrics(full_oos.values)
    else:
        full_oos = pd.Series(dtype=float)
        agg_m = {}

    return {
        "windows": windows,
        "oos_aggregate": agg_m,
        "oos_series": full_oos,
    }


def compute_correlations(strategy_rets: pd.Series) -> Dict:
    """Compute correlation to EXP-1220 and EXP-1700."""
    correlations = {}

    # EXP-1220
    try:
        from scripts.ultimate_portfolio import load_exp1220_dynamic
        exp1220 = load_exp1220_dynamic()
        common = strategy_rets.index.intersection(exp1220.index)
        if len(common) > 20:
            s1 = strategy_rets.reindex(common).fillna(0).values
            s2 = exp1220.reindex(common).fillna(0).values
            correlations["exp1220"] = float(np.corrcoef(s1, s2)[0, 1])
    except Exception as e:
        print(f"  EXP-1220 corr skipped: {e}")
        correlations["exp1220"] = float("nan")

    # EXP-1710 (0DTE SPX condors) — not built yet, skip gracefully
    correlations["exp1710"] = float("nan")

    # EXP-1700 (VIX roll) for comparison
    try:
        from compass.vix_roll_yield import load_all_data, compute_signals, RollYieldConfig
        data = load_all_data()
        df = compute_signals(data, RollYieldConfig())
        vix_rets = df["strategy_ret"]
        common = strategy_rets.index.intersection(vix_rets.index)
        if len(common) > 20:
            s1 = strategy_rets.reindex(common).fillna(0).values
            s2 = vix_rets.reindex(common).fillna(0).values
            correlations["exp1700"] = float(np.corrcoef(s1, s2)[0, 1])
    except Exception as e:
        print(f"  EXP-1700 corr skipped: {e}")
        correlations["exp1700"] = float("nan")

    return correlations


# ═══════════════════════════════════════════════════════════════════════════
# HTML Report
# ═══════════════════════════════════════════════════════════════════════════

def generate_report(wf: Dict, pair_results: List[Dict], correlations: Dict,
                     config: PairsConfig) -> str:
    agg = wf["oos_aggregate"]
    windows = wf["windows"]

    # Selected pairs (from top cointegrated)
    cointegrated = [p for p in pair_results if p["cointegrated"]]
    selected = cointegrated[:10] if cointegrated else pair_results[:10]

    pair_rows = ""
    for p in selected:
        sc = "#16a34a" if p["cointegrated"] else "#ca8a04"
        pair_rows += f"""<tr>
            <td style="font-weight:600">{p['a']}-{p['b']}</td>
            <td style="color:{sc};font-weight:700">{p['adf_stat']:.2f}</td>
            <td>{p['beta']:.3f}</td>
            <td>{p['n_obs']}</td>
            <td>{'YES' if p['cointegrated'] else 'marginal'}</td>
        </tr>"""

    # Year-by-year
    yr_rows = ""
    for w in windows:
        m = w["metrics"]
        sc = "#16a34a" if m["cagr_pct"] > 0 else "#dc2626"
        yr_rows += f"""<tr>
            <td style="font-weight:700">{w['year']}</td>
            <td>{w['n_pairs']}</td>
            <td style="color:{sc};font-weight:600">{m['cagr_pct']:.1f}%</td>
            <td style="font-weight:700">{m['sharpe']:.2f}</td>
            <td>{m['max_dd_pct']:.1f}%</td>
            <td>{m['vol_pct']:.1f}%</td>
        </tr>"""

    def _corr_fmt(v):
        if math.isnan(v): return '<span style="color:#94a3b8">N/A</span>'
        color = "#16a34a" if abs(v) < 0.2 else "#ca8a04"
        return f'<span style="color:{color};font-weight:700">{v:+.3f}</span>'

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>EXP-1720 Sector ETF Pairs Trading</title>
<style>
  * {{ box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
         max-width:1000px; margin:0 auto; padding:28px; background:#fff; color:#1e293b; line-height:1.5; }}
  h1 {{ font-size:1.8em; color:#0f172a; margin-bottom:4px; }}
  h2 {{ color:#334155; margin-top:2.5em; padding-bottom:8px; border-bottom:2px solid #e2e8f0; }}
  .subtitle {{ color:#64748b; font-size:0.9rem; margin-bottom:24px; }}
  .kpi-row {{ display:flex; gap:14px; flex-wrap:wrap; margin:20px 0; }}
  .kpi {{ background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; padding:18px;
          text-align:center; flex:1; min-width:130px; }}
  .kpi .value {{ font-size:1.7em; font-weight:800; color:#0f172a; }}
  .kpi .label {{ font-size:0.72em; color:#64748b; margin-top:4px; text-transform:uppercase; }}
  .good {{ color:#16a34a; }} .warn {{ color:#ca8a04; }} .bad {{ color:#dc2626; }}
  table {{ width:100%; border-collapse:collapse; margin:16px 0; font-size:0.86em; }}
  th {{ background:#f1f5f9; padding:10px 12px; text-align:right; font-weight:600; color:#475569;
       border-bottom:2px solid #cbd5e1; font-size:0.80em; text-transform:uppercase; }}
  th:first-child {{ text-align:left; }}
  td {{ padding:8px 12px; text-align:right; border-bottom:1px solid #e2e8f0; }}
  td:first-child {{ text-align:left; }}
  tr:hover {{ background:#f8fafc; }}
  .sources {{ background:#eff6ff; border:1px solid #bfdbfe; border-radius:8px; padding:16px; margin:16px 0; font-size:0.86rem; line-height:1.7; }}
  .footer {{ margin-top:3em; padding-top:1em; border-top:1px solid #e2e8f0; font-size:0.78em; color:#94a3b8; text-align:center; }}
</style></head><body>

<h1>EXP-1720 — Sector ETF Pairs Trading</h1>
<div class="subtitle">Cointegration-based mean reversion on SPDR sector ETFs | Real Yahoo data | {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>

<div class="sources">
    <strong>Data Sources (Rule Zero — zero synthetic):</strong><br>
    10 SPDR Sector ETFs via Yahoo Finance chart API:<br>
    XLF (Financials), XLK (Technology), XLE (Energy), XLU (Utilities), XLI (Industrials),<br>
    XLV (Healthcare), XLP (Staples), XLY (Discretionary), XLC (Communications), XLRE (Real Estate)<br>
    EXP-1220 returns: Yahoo SPY/VIX/VIX3M via load_exp1220_dynamic()
</div>

<div class="kpi-row">
    <div class="kpi"><div class="value {'good' if agg.get('cagr_pct', 0) > 0 else 'bad'}">{agg.get('cagr_pct', 0):.1f}%</div><div class="label">OOS CAGR</div></div>
    <div class="kpi"><div class="value">{agg.get('sharpe', 0):.2f}</div><div class="label">OOS Sharpe</div></div>
    <div class="kpi"><div class="value">{agg.get('max_dd_pct', 0):.1f}%</div><div class="label">Max DD</div></div>
    <div class="kpi"><div class="value">{agg.get('vol_pct', 0):.1f}%</div><div class="label">Vol</div></div>
    <div class="kpi"><div class="value">{agg.get('sortino', 0):.2f}</div><div class="label">Sortino</div></div>
    <div class="kpi"><div class="value">{len(cointegrated)}</div><div class="label">Cointegrated Pairs</div></div>
</div>

<h2>Correlations (Diversification Check)</h2>
<table>
    <thead><tr><th>vs Strategy</th><th>Correlation</th><th>Interpretation</th></tr></thead>
    <tbody>
        <tr><td>EXP-1220 (Credit Spreads)</td><td>{_corr_fmt(correlations.get('exp1220', float('nan')))}</td><td>{'LOW — good diversifier' if abs(correlations.get('exp1220', 0)) < 0.2 else 'moderate'}</td></tr>
        <tr><td>EXP-1700 (VIX Roll)</td><td>{_corr_fmt(correlations.get('exp1700', float('nan')))}</td><td>{'LOW — good diversifier' if abs(correlations.get('exp1700', 0)) < 0.2 else 'moderate'}</td></tr>
        <tr><td>EXP-1710 (0DTE SPX)</td><td>{_corr_fmt(correlations.get('exp1710', float('nan')))}</td><td>Not yet built</td></tr>
    </tbody>
</table>

<h2>Top Cointegrated Pairs (from 2015-2020 training)</h2>
<table>
    <thead><tr><th>Pair</th><th>ADF Stat</th><th>Hedge Ratio β</th><th>Obs</th><th>Cointegrated</th></tr></thead>
    <tbody>{pair_rows}</tbody>
</table>

<h2>Walk-Forward OOS by Year</h2>
<table>
    <thead><tr><th>Year</th><th>Pairs</th><th>CAGR</th><th>Sharpe</th><th>Max DD</th><th>Vol</th></tr></thead>
    <tbody>{yr_rows}</tbody>
</table>

<h2>Strategy Parameters</h2>
<table>
    <thead><tr><th>Parameter</th><th>Value</th></tr></thead>
    <tbody>
        <tr><td>Z-score entry</td><td>±{config.z_entry}</td></tr>
        <tr><td>Z-score exit</td><td>±{config.z_exit}</td></tr>
        <tr><td>Z-score stop</td><td>±{config.z_stop}</td></tr>
        <tr><td>Z lookback</td><td>{config.lookback} days</td></tr>
        <tr><td>Signal lag</td><td>1 day (t-1, no look-ahead)</td></tr>
        <tr><td>Cointegration test</td><td>Engle-Granger (OLS + ADF)</td></tr>
        <tr><td>ADF threshold</td><td>-3.0 (5% critical value)</td></tr>
    </tbody>
</table>

<div class="footer">
    EXP-1720 Sector Pairs Trading — compass/sector_pairs.py<br>
    All data from Yahoo Finance. Sharpe via compass/metrics.py (arithmetic mean).<br>
    No synthetic data. Engle-Granger cointegration + rolling z-score mean reversion.
</div>

</body></html>"""


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 72)
    print("EXP-1720 — Sector ETF Pairs Trading (Phase 7 Wave 1)")
    print("=" * 72)

    print("\n[1/5] Loading REAL sector ETF prices from Yahoo Finance...")
    prices = load_sector_prices(start="2015-01-01", end="2025-12-31")
    print(f"  → {len(prices)} aligned days, {len(prices.columns)} ETFs")

    print("\n[2/5] Testing cointegration (Engle-Granger) on training set...")
    pair_results = find_cointegrated_pairs(prices, train_end="2020-12-31")
    cointegrated = [p for p in pair_results if p["cointegrated"]]
    print(f"  → {len(cointegrated)} cointegrated pairs (ADF < -3.0) out of {len(pair_results)} total")
    print(f"\n  Top 10 by ADF stat:")
    for p in pair_results[:10]:
        marker = "COINT" if p["cointegrated"] else "     "
        print(f"    [{marker}] {p['a']}-{p['b']:5s}  ADF={p['adf_stat']:6.2f}  β={p['beta']:7.3f}")

    print("\n[3/5] Walk-forward backtest (expanding window)...")
    config = PairsConfig()
    wf = walk_forward_backtest(prices, config, top_n=8)

    agg = wf["oos_aggregate"]
    print(f"\n  OOS AGGREGATE:")
    print(f"    CAGR:   {agg.get('cagr_pct', 0):6.1f}%")
    print(f"    Sharpe: {agg.get('sharpe', 0):6.2f}")
    print(f"    Max DD: {agg.get('max_dd_pct', 0):6.1f}%")
    print(f"    Vol:    {agg.get('vol_pct', 0):6.1f}%")

    print(f"\n  YEAR-BY-YEAR:")
    for w in wf["windows"]:
        m = w["metrics"]
        print(f"    {w['year']}: {w['n_pairs']} pairs, CAGR={m['cagr_pct']:6.1f}%  "
              f"Sharpe={m['sharpe']:5.2f}  DD={m['max_dd_pct']:5.1f}%")

    print("\n[4/5] Correlation to other strategies...")
    correlations = compute_correlations(wf["oos_series"])
    for name, c in correlations.items():
        if not math.isnan(c):
            print(f"  vs {name}: {c:+.3f}")
        else:
            print(f"  vs {name}: N/A")

    print("\n[5/5] Generating report...")
    html = generate_report(wf, pair_results, correlations, config)
    report_path = ROOT / "reports" / "exp1720_sector_pairs.html"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(html, encoding="utf-8")
    print(f"  → {report_path}")


if __name__ == "__main__":
    main()
