"""
EXP-1270-real — Adaptive Stop-Loss with REAL IronVault data.

Uses only real SPY option prices from options_cache.db. No synthetic data,
no np.random for prices/returns.

Strategy: Monthly SPY put credit spreads, 30-45 DTE, $5-wide, exit at
50% profit / variable stop / 7 DTE. Then run AdaptiveStopOptimizer on
the real trade dataset.
"""

from __future__ import annotations

import json
import logging
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from shared.iron_vault import IronVault
from compass.adaptive_stops import (
    AdaptiveStopOptimizer,
    STOP_STRATEGIES,
    backtest_strategy,
)

logger = logging.getLogger(__name__)
OUTPUT_DIR = Path(__file__).resolve().parent / "results"

# ── Configuration ────────────────────────────────────────────────────────

TICKER = "SPY"
SPREAD_WIDTH = 5          # $5 wide spreads
TARGET_DTE_MIN = 30
TARGET_DTE_MAX = 45
PROFIT_TARGET_PCT = 0.50  # close at 50% of credit received
STOP_LOSS_MULT = 3.5      # baseline stop: 3.5× credit
MIN_DTE_EXIT = 7          # close at 7 DTE if still open
STARTING_CAPITAL = 100_000
MAX_CONTRACTS = 2
ENTRY_INTERVAL_DAYS = 20  # new trade roughly monthly


def _get_spy_underlying_prices() -> pd.DataFrame:
    """Get SPY daily OHLCV from yfinance (underlying prices, not options)."""
    import yfinance as yf
    df = yf.download("SPY", start="2019-12-01", end="2026-01-01", progress=False)
    # Flatten multi-level columns from yfinance
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index)
    return df


def _get_vix_data() -> pd.Series:
    """Get VIX daily close from yfinance."""
    import yfinance as yf
    vix = yf.download("^VIX", start="2019-12-01", end="2026-01-01", progress=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    return vix["Close"]


def _classify_regime(vix: float, spy_ret_20d: float) -> str:
    """Simple regime classification from VIX + 20-day return."""
    if vix > 35:
        return "crash"
    if vix > 25:
        return "high_vol"
    if vix < 15:
        return "low_vol"
    if spy_ret_20d < -0.05:
        return "bear"
    if spy_ret_20d > 0.03:
        return "bull"
    return "neutral"


def _find_monthly_expirations(hd: IronVault, start: str, end: str) -> List[str]:
    """Find available SPY put expirations in the DB that are monthly-ish."""
    import sqlite3
    conn = sqlite3.connect(hd._db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT expiration FROM option_contracts
        WHERE ticker='SPY' AND option_type='P'
        AND expiration BETWEEN ? AND ?
        ORDER BY expiration
    """, (start, end))
    all_exps = [r[0] for r in cur.fetchall()]
    conn.close()

    # Pick roughly monthly expirations (prefer 3rd-Friday monthly)
    monthly = []
    last_month = ""
    for exp in all_exps:
        ym = exp[:7]  # YYYY-MM
        day = int(exp[8:10])
        # Prefer 3rd Friday (15-21 range)
        if ym != last_month:
            if 15 <= day <= 21:
                monthly.append(exp)
                last_month = ym
    return monthly


def _exp_dt(exp_str: str) -> datetime:
    """Convert expiration string to datetime (required by IronVault API)."""
    return datetime.strptime(exp_str, "%Y-%m-%d")


def _find_otm_spread(
    hd: IronVault,
    expiration: str,
    trade_date: str,
    spy_price: float,
) -> Optional[Dict]:
    """Find a ~10-delta OTM put credit spread with real prices."""
    strikes = hd.get_available_strikes(TICKER, expiration, trade_date, "P")
    if not strikes:
        return None

    exp_as_dt = _exp_dt(expiration)

    # Target short strike: ~5-8% OTM
    target_short = spy_price * 0.93
    candidates = sorted(strikes, key=lambda k: abs(k - target_short))

    for short_k in candidates[:10]:
        long_k = short_k - SPREAD_WIDTH
        if long_k not in strikes:
            continue
        prices = hd.get_spread_prices(TICKER, exp_as_dt, short_k, long_k, "P", trade_date)
        if prices is None:
            continue
        credit = prices["short_close"] - prices["long_close"]
        if credit > 0.20:  # minimum viable credit
            return {
                "short_strike": short_k,
                "long_strike": long_k,
                "entry_credit": round(credit, 2),
                "max_loss": round(SPREAD_WIDTH - credit, 2),
            }
    return None


def _run_backtest(hd: IronVault) -> pd.DataFrame:
    """Run full backtest using real IronVault data. Returns trades DataFrame."""
    spy_df = _get_spy_underlying_prices()
    vix_series = _get_vix_data()

    # Compute 20-day return and realized vol for regime/stops
    spy_close = spy_df["Close"]
    spy_ret_20d = spy_close.pct_change(20)
    spy_rvol_20d = spy_close.pct_change().rolling(20).std() * math.sqrt(252) * 100  # annualized %

    expirations = _find_monthly_expirations(hd, "2020-01-01", "2025-12-31")
    print(f"Found {len(expirations)} monthly expirations")

    trades: List[Dict] = []
    last_entry_date = None
    skipped = 0

    for exp in expirations:
        exp_dt = datetime.strptime(exp, "%Y-%m-%d")
        # Entry: ~30-45 DTE before expiration
        entry_dt = exp_dt - timedelta(days=37)
        # Find nearest trading day
        for offset in range(7):
            candidate = entry_dt + timedelta(days=offset)
            cand_str = candidate.strftime("%Y-%m-%d")
            if cand_str in spy_df.index.strftime("%Y-%m-%d").values:
                entry_dt = candidate
                break
        else:
            skipped += 1
            continue

        entry_str = entry_dt.strftime("%Y-%m-%d")

        # Enforce minimum interval between entries
        if last_entry_date and (entry_dt - last_entry_date).days < ENTRY_INTERVAL_DAYS:
            continue

        # Get SPY price on entry date
        try:
            spy_price = float(spy_close.loc[entry_str])
        except (KeyError, TypeError):
            skipped += 1
            continue

        # Find spread with real prices
        spread = _find_otm_spread(hd, exp, entry_str, spy_price)
        if spread is None:
            skipped += 1
            continue

        # Get context data
        try:
            vix_val = float(vix_series.loc[entry_str])
        except (KeyError, TypeError):
            vix_val = 20.0
        try:
            rvol = float(spy_rvol_20d.loc[entry_str])
        except (KeyError, TypeError):
            rvol = 15.0
        try:
            ret_20d = float(spy_ret_20d.loc[entry_str])
        except (KeyError, TypeError):
            ret_20d = 0.0

        if np.isnan(rvol):
            rvol = 15.0
        if np.isnan(ret_20d):
            ret_20d = 0.0

        regime = _classify_regime(vix_val, ret_20d)
        dte_at_entry = (exp_dt - entry_dt).days

        # ── Simulate trade: daily mark-to-market with real prices ──
        entry_credit = spread["entry_credit"]
        max_loss_per_contract = spread["max_loss"]
        contracts = min(MAX_CONTRACTS, max(1, int(STARTING_CAPITAL * 0.02 / (max_loss_per_contract * 100))))

        exit_date = None
        exit_reason = ""
        exit_spread_value = entry_credit  # if we can't find exit price
        hold_days = 0

        # Walk forward through trading days
        current = entry_dt + timedelta(days=1)
        while current <= exp_dt:
            curr_str = current.strftime("%Y-%m-%d")
            if curr_str not in spy_df.index.strftime("%Y-%m-%d").values:
                current += timedelta(days=1)
                continue

            hold_days += 1
            dte_remaining = (exp_dt - current).days

            # Get real spread price
            prices = hd.get_spread_prices(
                TICKER, exp_dt, spread["short_strike"], spread["long_strike"], "P", curr_str,
            )
            if prices is None:
                current += timedelta(days=1)
                continue

            current_spread_value = prices["short_close"] - prices["long_close"]

            # Profit target: spread value dropped to 50% of entry credit
            if current_spread_value <= entry_credit * (1 - PROFIT_TARGET_PCT):
                exit_date = curr_str
                exit_reason = "profit_target"
                exit_spread_value = current_spread_value
                break

            # Stop loss: loss exceeds 3.5× credit
            unrealized_loss = current_spread_value - entry_credit
            if unrealized_loss > entry_credit * STOP_LOSS_MULT:
                exit_date = curr_str
                exit_reason = "close_stop_loss"
                exit_spread_value = current_spread_value
                break

            # DTE exit
            if dte_remaining <= MIN_DTE_EXIT:
                exit_date = curr_str
                exit_reason = "dte_exit"
                exit_spread_value = current_spread_value
                break

            current += timedelta(days=1)

        if exit_date is None:
            # Expired — spread value goes to intrinsic or zero
            exit_date = exp
            exit_reason = "expiration"
            # Try to get final price
            final_prices = hd.get_spread_prices(
                TICKER, exp_dt, spread["short_strike"], spread["long_strike"], "P", exp,
            )
            if final_prices:
                exit_spread_value = final_prices["short_close"] - final_prices["long_close"]
            else:
                # At expiration, if short strike > SPY price, loss = intrinsic
                try:
                    final_spy = float(spy_close.loc[exp])
                    if final_spy < spread["short_strike"]:
                        intrinsic = min(spread["short_strike"] - final_spy, SPREAD_WIDTH)
                        exit_spread_value = intrinsic
                    else:
                        exit_spread_value = 0.0  # OTM, worthless
                except (KeyError, TypeError):
                    exit_spread_value = 0.0

        # Compute P&L (credit spread: profit = entry_credit - exit_value)
        pnl_per_contract = (entry_credit - exit_spread_value) * 100
        total_pnl = pnl_per_contract * contracts
        return_pct = ((entry_credit - exit_spread_value) / entry_credit * 100) if entry_credit > 0 else 0

        trades.append({
            "entry_date": entry_str,
            "exit_date": exit_date,
            "expiration": exp,
            "short_strike": spread["short_strike"],
            "long_strike": spread["long_strike"],
            "net_credit": entry_credit,
            "exit_value": round(exit_spread_value, 4),
            "contracts": contracts,
            "pnl": round(total_pnl, 2),
            "return_pct": round(return_pct, 2),
            "exit_reason": exit_reason,
            "dte_at_entry": dte_at_entry,
            "hold_days": hold_days,
            "vix": round(vix_val, 2),
            "realized_vol_20d": round(rvol, 2),
            "regime": regime,
            "spy_price_entry": round(spy_price, 2),
        })
        last_entry_date = entry_dt

    print(f"Completed {len(trades)} trades ({skipped} skipped due to missing data)")
    return pd.DataFrame(trades)


def _compute_yearly_stats(trades_df: pd.DataFrame) -> Dict[str, Dict]:
    """Compute yearly CAGR, max DD, Sharpe, win rate."""
    if trades_df.empty:
        return {}

    trades_df = trades_df.copy()
    trades_df["year"] = pd.to_datetime(trades_df["exit_date"]).dt.year

    results = {}
    for year, group in trades_df.groupby("year"):
        pnls = group["pnl"].values
        n = len(pnls)
        total_pnl = pnls.sum()
        wins = (pnls > 0).sum()
        win_rate = wins / n if n > 0 else 0

        # Equity curve for drawdown
        equity = np.cumsum(pnls) + STARTING_CAPITAL
        peak = np.maximum.accumulate(equity)
        dd = (peak - equity) / peak
        max_dd = float(dd.max())

        # Sharpe (annualized from per-trade returns)
        mean_pnl = pnls.mean()
        std_pnl = pnls.std(ddof=1) if n > 1 else 1.0
        # Assume ~12 trades/year for annualization
        trades_per_year = max(n, 1)
        sharpe = (mean_pnl / std_pnl * math.sqrt(trades_per_year)) if std_pnl > 0 else 0

        # CAGR (simple: total return over capital)
        annual_return = total_pnl / STARTING_CAPITAL

        results[int(year)] = {
            "n_trades": n,
            "total_pnl": round(total_pnl, 2),
            "win_rate": round(win_rate, 4),
            "max_dd": round(max_dd, 4),
            "sharpe": round(sharpe, 3),
            "annual_return": round(annual_return, 4),
            "avg_pnl": round(mean_pnl, 2),
        }

    return results


def _compute_overall_stats(trades_df: pd.DataFrame) -> Dict:
    """Compute overall backtest statistics."""
    if trades_df.empty:
        return {}

    pnls = trades_df["pnl"].values
    n = len(pnls)
    total_pnl = pnls.sum()
    wins = (pnls > 0).sum()

    equity = np.cumsum(pnls) + STARTING_CAPITAL
    peak = np.maximum.accumulate(equity)
    dd = (peak - equity) / peak
    max_dd = float(dd.max())

    mean_pnl = pnls.mean()
    std_pnl = pnls.std(ddof=1) if n > 1 else 1.0
    sharpe = (mean_pnl / std_pnl * math.sqrt(n)) if std_pnl > 0 else 0

    years = (pd.to_datetime(trades_df["exit_date"].iloc[-1]) -
             pd.to_datetime(trades_df["entry_date"].iloc[0])).days / 365.25
    cagr = ((1 + total_pnl / STARTING_CAPITAL) ** (1 / max(years, 0.5)) - 1) if years > 0 else 0

    return {
        "n_trades": n,
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(wins / n, 4),
        "max_dd": round(max_dd, 4),
        "sharpe": round(sharpe, 3),
        "cagr": round(cagr, 4),
        "avg_pnl": round(mean_pnl, 2),
        "years": round(years, 1),
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.WARNING)

    print("=" * 60)
    print("EXP-1270-real: Adaptive Stop-Loss — REAL DATA BACKTEST")
    print("=" * 60)

    # Initialize IronVault
    hd = IronVault.instance()
    cov = hd.coverage_report()
    print(f"IronVault: {cov['contracts_total']:,} contracts, "
          f"{cov['daily_bars_total']:,} daily bars")

    # Run backtest
    trades_df = _run_backtest(hd)

    if trades_df.empty:
        print("ERROR: No trades generated. Check data coverage.")
        return

    # Save trades
    trades_df.to_csv(OUTPUT_DIR / "trades_real.csv", index=False)
    print(f"\nSaved {len(trades_df)} trades to trades_real.csv")

    # Yearly stats
    yearly = _compute_yearly_stats(trades_df)
    overall = _compute_overall_stats(trades_df)

    print("\n── Yearly Performance ──")
    print(f"{'Year':>6} {'Trades':>7} {'P&L':>10} {'WinRate':>8} {'MaxDD':>8} {'Sharpe':>8} {'Return':>8}")
    for year in sorted(yearly.keys()):
        y = yearly[year]
        print(f"{year:>6} {y['n_trades']:>7} {y['total_pnl']:>10,.0f} "
              f"{y['win_rate']:>8.1%} {y['max_dd']:>8.1%} {y['sharpe']:>8.2f} {y['annual_return']:>8.1%}")

    print(f"\n── Overall (Real Data) ──")
    print(f"Trades:    {overall['n_trades']}")
    print(f"Total P&L: ${overall['total_pnl']:,.0f}")
    print(f"CAGR:      {overall['cagr']:.1%}")
    print(f"Win Rate:  {overall['win_rate']:.1%}")
    print(f"Max DD:    {overall['max_dd']:.1%}")
    print(f"Sharpe:    {overall['sharpe']:.2f}")

    # Run AdaptiveStopOptimizer on real trades
    print(f"\n── Adaptive Stop Optimization (Real Data) ──")
    optimizer = AdaptiveStopOptimizer(trades_df)
    opt_results = optimizer.optimize()

    # Find best strategy
    global_results = opt_results["global"]
    best = max(global_results.values(), key=lambda s: s.total_pnl)
    print(f"Best stop strategy: {best.name}")
    print(f"  Total P&L:  ${best.total_pnl:,.0f}")
    print(f"  Win Rate:   {best.win_rate:.1%}")
    print(f"  Sharpe:     {best.sharpe}")
    print(f"  Stop Rate:  {best.stop_rate:.1%}")
    print(f"  Premature:  {best.premature_stop_rate:.1%}")

    # Comparison to synthetic
    print(f"\n── Comparison: Real vs Synthetic (EXP-1270-max) ──")
    print(f"{'Metric':<20} {'Real':>12} {'Synthetic':>12}")
    print(f"{'Sharpe':<20} {overall['sharpe']:>12.2f} {'5.25':>12}")
    print(f"{'Max DD':<20} {overall['max_dd']:>12.1%} {'3.2%':>12}")
    print(f"{'Win Rate':<20} {overall['win_rate']:>12.1%} {'—':>12}")
    print(f"{'CAGR':<20} {overall['cagr']:>12.1%} {'163.1%':>12}")

    # Save results
    summary = {
        "experiment": "EXP-1270-real",
        "data_source": "IronVault (options_cache.db)",
        "synthetic_data_used": False,
        "overall": overall,
        "yearly": yearly,
        "best_stop_strategy": {
            "name": best.name,
            "total_pnl": best.total_pnl,
            "win_rate": best.win_rate,
            "sharpe": best.sharpe,
            "stop_rate": best.stop_rate,
        },
        "all_strategies": {
            name: {
                "total_pnl": s.total_pnl, "win_rate": s.win_rate,
                "sharpe": s.sharpe, "stop_rate": s.stop_rate,
            }
            for name, s in global_results.items()
        },
        "comparison_to_synthetic": {
            "synthetic_sharpe": 5.25,
            "real_sharpe": overall["sharpe"],
            "synthetic_max_dd": 0.032,
            "real_max_dd": overall["max_dd"],
            "synthetic_return": 1.631,
            "real_cagr": overall["cagr"],
        },
        "regime_optimals": [
            {"regime": r.regime, "best_strategy": r.best_strategy,
             "pnl": r.best_pnl, "win_rate": r.best_win_rate, "n_trades": r.n_trades}
            for r in opt_results.get("regime_optimals", [])
        ],
    }

    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nResults saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
