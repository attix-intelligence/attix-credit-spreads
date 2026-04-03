"""
EXP-1320-real — Intraday Volatility Clustering with REAL IronVault data.

Uses real intraday option bars from options_cache.db instead of
simulate_sessions_from_daily() which uses np.random.

Approach:
  1. For each trading day, fetch real intraday option bars from IronVault
  2. Compute intraday realized vol from real price changes
  3. Detect expansion/contraction regimes using VolClusterEngine
  4. Generate same-day signals (sell_premium / avoid / neutral)
  5. Overlay signals on real SPY credit spread trades
  6. Report yearly CAGR, max DD, Sharpe, win rate
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from shared.iron_vault import IronVault
from compass.intraday_vol_clustering import (
    VolClusterEngine,
    SessionProfile,
    ClusterSignal,
    OverlayResult,
    analyze_session,
    generate_session_signal,
    vol_autocorrelation,
    expansion_predicts_eod_auc,
)

logger = logging.getLogger(__name__)
OUTPUT_DIR = Path(__file__).resolve().parent / "results"

# ── Configuration ────────────────────────────────────────────────────────

TICKER = "SPY"
SPREAD_WIDTH = 5
STARTING_CAPITAL = 100_000
PROFIT_TARGET_PCT = 0.50
STOP_LOSS_MULT = 3.0
MIN_DTE_EXIT = 7
ENTRY_INTERVAL_DAYS = 20
MAX_CONTRACTS = 2


def _get_spy_prices() -> pd.DataFrame:
    """Get SPY daily OHLCV from yfinance."""
    import yfinance as yf
    df = yf.download("SPY", start="2019-12-01", end="2026-01-01", progress=False)
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


# ── Real intraday session builder ────────────────────────────────────────


def _fetch_real_intraday_sessions(hd: IronVault) -> List[Tuple[str, SessionProfile]]:
    """Build real intraday vol sessions from IronVault option bars.

    For each trading day with intraday data:
    1. Find all intraday bars for SPY puts on that day
    2. Pick the most liquid contract (most bars)
    3. Build a 5-min price series from real data
    4. Feed to analyze_session() for vol clustering
    """
    conn = sqlite3.connect(hd._db_path)
    cur = conn.cursor()

    # Get all dates with intraday SPY data
    cur.execute("""
        SELECT DISTINCT date FROM option_intraday
        WHERE contract_symbol LIKE 'O:SPY%' AND bar_time != 'FETCHED'
        AND date BETWEEN '2020-01-01' AND '2025-12-31'
        ORDER BY date
    """)
    dates = [r[0] for r in cur.fetchall()]
    print(f"Found {len(dates)} dates with intraday data")

    sessions: List[Tuple[str, SessionProfile]] = []
    n_good = 0
    n_skip = 0

    for date_str in dates:
        # Find all contracts with intraday bars on this date
        cur.execute("""
            SELECT contract_symbol, COUNT(*) as n_bars
            FROM option_intraday
            WHERE contract_symbol LIKE 'O:SPY%' AND date = ? AND bar_time != 'FETCHED'
            GROUP BY contract_symbol
            HAVING n_bars >= 10
            ORDER BY n_bars DESC
            LIMIT 5
        """, (date_str,))
        candidates = cur.fetchall()

        if not candidates:
            n_skip += 1
            continue

        # Use up to 3 most liquid contracts, merge their price series
        # to get a fuller picture of intraday vol
        all_prices = []
        for contract_sym, n_bars in candidates[:3]:
            cur.execute("""
                SELECT bar_time, close FROM option_intraday
                WHERE contract_symbol = ? AND date = ? AND bar_time != 'FETCHED'
                ORDER BY bar_time
            """, (contract_sym, date_str))
            bars = cur.fetchall()
            prices = [float(b[1]) for b in bars if b[1] is not None and b[1] > 0]
            if len(prices) >= 10:
                all_prices.append(np.array(prices))

        if not all_prices:
            n_skip += 1
            continue

        # Use the contract with the most bars as primary
        primary = max(all_prices, key=len)

        # Analyze session using real prices
        session = analyze_session(primary, date=date_str)
        if session.blocks:
            sessions.append((date_str, session))
            n_good += 1
        else:
            n_skip += 1

    conn.close()
    print(f"Built {n_good} real sessions ({n_skip} skipped)")
    return sessions


# ── Real trade generation ────────────────────────────────────────────────


def _find_monthly_expirations(hd: IronVault) -> List[str]:
    """Find monthly SPY expirations."""
    conn = sqlite3.connect(hd._db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT expiration FROM option_contracts
        WHERE ticker='SPY' AND option_type='P'
        AND expiration BETWEEN '2020-01-01' AND '2025-12-31'
        ORDER BY expiration
    """)
    all_exps = [r[0] for r in cur.fetchall()]
    conn.close()

    monthly = []
    last_month = ""
    for exp in all_exps:
        ym = exp[:7]
        day = int(exp[8:10])
        if ym != last_month and 15 <= day <= 21:
            monthly.append(exp)
            last_month = ym
    return monthly


def _generate_real_trades(hd: IronVault, spy_df: pd.DataFrame) -> pd.DataFrame:
    """Generate trades from real option prices (same approach as EXP-1270-real)."""
    spy_close = spy_df["Close"]
    expirations = _find_monthly_expirations(hd)
    print(f"Found {len(expirations)} monthly expirations for trades")

    trades: List[Dict] = []
    last_entry = None

    for exp in expirations:
        exp_dt = datetime.strptime(exp, "%Y-%m-%d")
        entry_dt = exp_dt - timedelta(days=37)

        for offset in range(7):
            cand = entry_dt + timedelta(days=offset)
            cand_str = cand.strftime("%Y-%m-%d")
            if cand_str in spy_df.index.strftime("%Y-%m-%d").values:
                entry_dt = cand
                break
        else:
            continue

        entry_str = entry_dt.strftime("%Y-%m-%d")
        if last_entry and (entry_dt - last_entry).days < ENTRY_INTERVAL_DAYS:
            continue

        try:
            spy_price = float(spy_close.loc[entry_str])
        except (KeyError, TypeError):
            continue

        # Find spread
        strikes = hd.get_available_strikes(TICKER, exp, entry_str, "P")
        if not strikes:
            continue

        target = spy_price * 0.93
        spread = None
        for short_k in sorted(strikes, key=lambda k: abs(k - target))[:10]:
            long_k = short_k - SPREAD_WIDTH
            if long_k not in strikes:
                continue
            prices = hd.get_spread_prices(TICKER, exp_dt, short_k, long_k, "P", entry_str)
            if prices is None:
                continue
            credit = prices["short_close"] - prices["long_close"]
            if credit > 0.20:
                spread = {"short": short_k, "long": long_k, "credit": round(credit, 2)}
                break

        if spread is None:
            continue

        contracts = min(MAX_CONTRACTS, max(1, int(STARTING_CAPITAL * 0.02 / ((SPREAD_WIDTH - spread["credit"]) * 100))))

        # Walk forward for exit
        exit_date = None
        exit_reason = ""
        exit_value = spread["credit"]
        hold_days = 0

        current = entry_dt + timedelta(days=1)
        while current <= exp_dt:
            curr_str = current.strftime("%Y-%m-%d")
            if curr_str not in spy_df.index.strftime("%Y-%m-%d").values:
                current += timedelta(days=1)
                continue

            hold_days += 1
            dte_rem = (exp_dt - current).days

            prices = hd.get_spread_prices(TICKER, exp_dt, spread["short"], spread["long"], "P", curr_str)
            if prices is None:
                current += timedelta(days=1)
                continue

            cv = prices["short_close"] - prices["long_close"]

            if cv <= spread["credit"] * (1 - PROFIT_TARGET_PCT):
                exit_date, exit_reason, exit_value = curr_str, "profit_target", cv
                break
            if cv - spread["credit"] > spread["credit"] * STOP_LOSS_MULT:
                exit_date, exit_reason, exit_value = curr_str, "close_stop_loss", cv
                break
            if dte_rem <= MIN_DTE_EXIT:
                exit_date, exit_reason, exit_value = curr_str, "dte_exit", cv
                break

            current += timedelta(days=1)

        if exit_date is None:
            exit_date = exp
            exit_reason = "expiration"
            fp = hd.get_spread_prices(TICKER, exp_dt, spread["short"], spread["long"], "P", exp)
            if fp:
                exit_value = fp["short_close"] - fp["long_close"]
            else:
                try:
                    final_spy = float(spy_close.loc[exp])
                    exit_value = min(max(spread["short"] - final_spy, 0), SPREAD_WIDTH) if final_spy < spread["short"] else 0
                except (KeyError, TypeError):
                    exit_value = 0

        pnl = (spread["credit"] - exit_value) * 100 * contracts
        ret_pct = (spread["credit"] - exit_value) / spread["credit"] * 100 if spread["credit"] > 0 else 0
        win = 1 if pnl > 0 else 0

        trades.append({
            "entry_date": entry_str,
            "exit_date": exit_date,
            "expiration": exp,
            "net_credit": spread["credit"],
            "pnl": round(pnl, 2),
            "return_pct": round(ret_pct, 2),
            "contracts": contracts,
            "win": win,
            "exit_reason": exit_reason,
            "hold_days": hold_days,
        })
        last_entry = entry_dt

    print(f"Generated {len(trades)} real trades")
    return pd.DataFrame(trades)


# ── Signal overlay on real trades ────────────────────────────────────────


def _overlay_signals_on_trades(
    sessions: List[Tuple[str, SessionProfile]],
    trades_df: pd.DataFrame,
) -> Tuple[OverlayResult, List[Dict]]:
    """Overlay real intraday vol signals on real trades."""
    # Build signal map: date → ClusterSignal
    signal_map: Dict[str, ClusterSignal] = {}
    for date_str, session in sessions:
        sig = generate_session_signal(session)
        signal_map[date_str] = sig

    sp_wins, sp_total, sp_pnls = 0, 0, []
    av_wins, av_total, av_pnls = 0, 0, []
    trade_signals = []

    for _, row in trades_df.iterrows():
        entry = str(row.get("entry_date", ""))[:10]
        pnl = float(row.get("pnl", 0))
        win = int(row.get("win", 0))

        sig = signal_map.get(entry)
        signal_label = sig.signal if sig else "no_data"

        if sig and sig.signal == "sell_premium":
            sp_total += 1
            sp_wins += win
            sp_pnls.append(pnl)
        elif sig and sig.signal == "avoid":
            av_total += 1
            av_wins += win
            av_pnls.append(pnl)
        else:
            # neutral or no data — still trade
            sp_pnls.append(pnl)  # include in general pool

        trade_signals.append({
            "entry_date": entry,
            "signal": signal_label,
            "pnl": pnl,
            "win": win,
        })

    sp_wr = sp_wins / sp_total if sp_total > 0 else 0
    av_wr = av_wins / av_total if av_total > 0 else 0

    overlay = OverlayResult(
        total_trades=sp_total + av_total,
        sell_prem_trades=sp_total,
        avoid_trades=av_total,
        sell_prem_wr=sp_wr,
        avoid_wr=av_wr,
        improvement_pp=(sp_wr - av_wr) * 100 if (sp_total > 0 and av_total > 0) else 0,
    )
    return overlay, trade_signals


# ── Standalone Sharpe from real signals ──────────────────────────────────


def _compute_real_standalone_sharpe(
    sessions: List[Tuple[str, SessionProfile]],
    spy_df: pd.DataFrame,
) -> float:
    """Compute standalone Sharpe from real vol clustering signals.

    sell_premium → go short vol (collect next-day premium)
    avoid → stay flat (avoid loss)
    """
    spy_ret = spy_df["Close"].pct_change().dropna()
    ret_map = {d.strftime("%Y-%m-%d"): float(r) for d, r in spy_ret.items()}

    pnls = []
    for date_str, session in sessions:
        sig = generate_session_signal(session)
        # Get next trading day return
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        for offset in range(1, 5):
            nxt = (dt + timedelta(days=offset)).strftime("%Y-%m-%d")
            if nxt in ret_map:
                nxt_ret = ret_map[nxt]
                break
        else:
            continue

        if sig.signal == "sell_premium":
            # Premium seller benefits when market is calm (small moves)
            # P&L proxy: collect premium, lose if big move
            pnls.append(-abs(nxt_ret) + 0.001)  # ~daily theta
        elif sig.signal == "avoid":
            pnls.append(0)  # flat
        # neutral: skip

    if len(pnls) < 20:
        return 0.0
    arr = np.array(pnls)
    mu, std = arr.mean(), arr.std(ddof=1)
    return float(mu / std * math.sqrt(252)) if std > 1e-12 else 0.0


# ── Yearly stats ────────────────────────────────────────────────────────


def _compute_yearly_stats(trades_df: pd.DataFrame, signal_trades: List[Dict]) -> Dict:
    """Compute yearly CAGR, max DD, Sharpe, win rate for signal-filtered trades."""
    if trades_df.empty:
        return {}

    # Use all trades for overall stats (signal overlay is analytical)
    trades_df = trades_df.copy()
    trades_df["year"] = pd.to_datetime(trades_df["exit_date"]).dt.year

    results = {}
    for year, group in trades_df.groupby("year"):
        pnls = group["pnl"].values
        n = len(pnls)
        if n == 0:
            continue
        total_pnl = pnls.sum()
        wins = (pnls > 0).sum()
        win_rate = wins / n

        equity = np.cumsum(pnls) + STARTING_CAPITAL
        peak = np.maximum.accumulate(equity)
        dd = (peak - equity) / peak
        max_dd = float(dd.max())

        mean_pnl = pnls.mean()
        std_pnl = pnls.std(ddof=1) if n > 1 else 1.0
        sharpe = (mean_pnl / std_pnl * math.sqrt(max(n, 1))) if std_pnl > 0 else 0

        results[int(year)] = {
            "n_trades": n,
            "total_pnl": round(total_pnl, 2),
            "win_rate": round(win_rate, 4),
            "max_dd": round(max_dd, 4),
            "sharpe": round(sharpe, 3),
            "annual_return": round(total_pnl / STARTING_CAPITAL, 4),
        }
    return results


def _compute_overall(trades_df: pd.DataFrame) -> Dict:
    if trades_df.empty:
        return {}
    pnls = trades_df["pnl"].values
    n = len(pnls)
    total = pnls.sum()
    wins = (pnls > 0).sum()

    equity = np.cumsum(pnls) + STARTING_CAPITAL
    peak = np.maximum.accumulate(equity)
    dd = (peak - equity) / peak

    mean_p = pnls.mean()
    std_p = pnls.std(ddof=1) if n > 1 else 1.0
    sharpe = (mean_p / std_p * math.sqrt(n)) if std_p > 0 else 0

    years = (pd.to_datetime(trades_df["exit_date"].iloc[-1]) -
             pd.to_datetime(trades_df["entry_date"].iloc[0])).days / 365.25
    cagr = ((1 + total / STARTING_CAPITAL) ** (1 / max(years, 0.5)) - 1) if years > 0 else 0

    return {
        "n_trades": n,
        "total_pnl": round(total, 2),
        "win_rate": round(wins / n, 4),
        "max_dd": round(float(dd.max()), 4),
        "sharpe": round(sharpe, 3),
        "cagr": round(cagr, 4),
        "avg_pnl": round(mean_p, 2),
        "years": round(years, 1),
    }


# ── Main ─────────────────────────────────────────────────────────────────


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.WARNING)

    print("=" * 60)
    print("EXP-1320-real: Intraday Vol Clustering — REAL DATA BACKTEST")
    print("=" * 60)

    hd = IronVault.instance()
    cov = hd.coverage_report()
    print(f"IronVault: {cov['contracts_total']:,} contracts, "
          f"{cov['intraday_bars_total']:,} intraday bars")

    # 1. Build real intraday sessions
    print("\n── Building real intraday sessions ──")
    real_sessions = _fetch_real_intraday_sessions(hd)

    # Compute real vol clustering metrics
    all_autocorrs = [s.vol_autocorrelation for _, s in real_sessions if s.blocks]
    all_sessions = [s for _, s in real_sessions if s.blocks]
    avg_autocorr = float(np.mean(all_autocorrs)) if all_autocorrs else 0
    auc = expansion_predicts_eod_auc(all_sessions)

    print(f"Real avg autocorrelation: {avg_autocorr:.4f}")
    print(f"Real expansion→EOD AUC:   {auc:.4f}")

    # Signal distribution
    signals = [generate_session_signal(s) for _, s in real_sessions]
    n_sell = sum(1 for s in signals if s.signal == "sell_premium")
    n_avoid = sum(1 for s in signals if s.signal == "avoid")
    n_neutral = sum(1 for s in signals if s.signal == "neutral")
    print(f"Signals: sell_premium={n_sell}, avoid={n_avoid}, neutral={n_neutral}")

    # 2. Generate real trades
    print("\n── Generating real trades ──")
    spy_df = _get_spy_prices()
    trades_df = _generate_real_trades(hd, spy_df)

    if trades_df.empty:
        print("ERROR: No trades generated")
        return

    trades_df.to_csv(OUTPUT_DIR / "trades_real.csv", index=False)

    # 3. Overlay signals on trades
    print("\n── Signal overlay on real trades ──")
    overlay, trade_signals = _overlay_signals_on_trades(real_sessions, trades_df)

    print(f"Sell premium trades: {overlay.sell_prem_trades} (WR: {overlay.sell_prem_wr:.1%})")
    print(f"Avoid trades:        {overlay.avoid_trades} (WR: {overlay.avoid_wr:.1%})")
    print(f"Improvement:         {overlay.improvement_pp:+.1f}pp")

    # 4. Standalone Sharpe from real signals
    standalone_sh = _compute_real_standalone_sharpe(real_sessions, spy_df)
    print(f"Real standalone Sharpe: {standalone_sh:.3f}")

    # 5. Yearly stats
    yearly = _compute_yearly_stats(trades_df, trade_signals)
    overall = _compute_overall(trades_df)

    print(f"\n── Yearly Performance (Real Trades) ──")
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

    # 6. Comparison to synthetic
    print(f"\n── Comparison: Real vs Synthetic (EXP-1320-max) ──")
    print(f"{'Metric':<25} {'Real':>12} {'Synthetic':>12}")
    print(f"{'Avg Autocorrelation':<25} {avg_autocorr:>12.4f} {'0.1258':>12}")
    print(f"{'Expansion→EOD AUC':<25} {auc:>12.4f} {'0.2916':>12}")
    print(f"{'Standalone Sharpe':<25} {standalone_sh:>12.3f} {'3.047':>12}")
    print(f"{'Trade Sharpe':<25} {overall['sharpe']:>12.2f} {'—':>12}")
    print(f"{'Overlay Improvement':<25} {overlay.improvement_pp:>+12.1f}pp {'-11.1pp':>12}")

    # Save results
    summary = {
        "experiment": "EXP-1320-real",
        "data_source": "IronVault (options_cache.db) — real intraday bars",
        "synthetic_data_used": False,
        "vol_clustering": {
            "n_sessions": len(real_sessions),
            "avg_autocorrelation": round(avg_autocorr, 4),
            "expansion_auc": round(auc, 4),
            "standalone_sharpe": round(standalone_sh, 3),
            "signals": {
                "sell_premium": n_sell,
                "avoid": n_avoid,
                "neutral": n_neutral,
            },
        },
        "overlay": {
            "sell_prem_wr": round(overlay.sell_prem_wr, 4),
            "avoid_wr": round(overlay.avoid_wr, 4),
            "improvement_pp": round(overlay.improvement_pp, 2),
            "sell_prem_trades": overlay.sell_prem_trades,
            "avoid_trades": overlay.avoid_trades,
        },
        "overall": overall,
        "yearly": yearly,
        "comparison_to_synthetic": {
            "synthetic_autocorrelation": 0.1258,
            "real_autocorrelation": round(avg_autocorr, 4),
            "synthetic_auc": 0.2916,
            "real_auc": round(auc, 4),
            "synthetic_sharpe": 3.047,
            "real_standalone_sharpe": round(standalone_sh, 3),
            "synthetic_overlay_pp": -11.1,
            "real_overlay_pp": round(overlay.improvement_pp, 2),
        },
    }

    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    pd.DataFrame(trade_signals).to_csv(OUTPUT_DIR / "trade_signals.csv", index=False)
    print(f"\nResults saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
